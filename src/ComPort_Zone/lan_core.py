from __future__ import annotations

import socket
from copy import deepcopy
from queue import Queue
from threading import Event, Lock, Thread, current_thread
from typing import Callable, Protocol

from .models import LanProfile, apply_line_ending
from .serial_core import SerialEvent, decode_serial_bytes, format_hex_bytes

LAN_RECONNECT_RETRY_INTERVAL_MS = 1000


class SocketLike(Protocol):
    def recv(self, size: int) -> bytes:
        ...

    def sendall(self, data: bytes) -> None:
        ...

    def close(self) -> None:
        ...

    def settimeout(self, value: float | None) -> None:
        ...


SocketFactory = Callable[[tuple[str, int], float], SocketLike]


def _default_socket_factory(address: tuple[str, int], timeout: float) -> SocketLike:
    return socket.create_connection(address, timeout=timeout)


class LanClient:
    def __init__(self, socket_factory: SocketFactory | None = None) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self._lock = Lock()
        self._event_subscribers: list[Queue[SerialEvent]] = []
        self._socket_factory = socket_factory or _default_socket_factory
        self._socket: SocketLike | None = None
        self._profile: LanProfile | None = None
        self._desired_profile: LanProfile | None = None
        self._reader_thread: Thread | None = None
        self._reader_stop = Event()
        self._reconnect_thread: Thread | None = None
        self._reconnect_stop = Event()
        self._user_disconnect = True

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._socket is not None

    @property
    def is_reconnecting(self) -> bool:
        thread = self._reconnect_thread
        return bool(thread and thread.is_alive())

    @property
    def active_profile(self) -> LanProfile | None:
        with self._lock:
            return deepcopy(self._profile or self._desired_profile)

    def subscribe_events(self) -> Queue[SerialEvent]:
        queue: Queue[SerialEvent] = Queue()
        with self._lock:
            self._event_subscribers.append(queue)
        return queue

    def unsubscribe_events(self, queue: Queue[SerialEvent]) -> None:
        with self._lock:
            self._event_subscribers = [
                subscriber
                for subscriber in self._event_subscribers
                if subscriber is not queue
            ]

    def connect(self, profile: LanProfile) -> bool:
        self._desired_profile = deepcopy(profile)
        self._user_disconnect = False
        self._stop_reconnect_thread()
        self._close_socket(emit_event=False)
        success = self._attempt_connect(profile, reconnect_attempt=False)
        if not success and profile.auto_reconnect:
            self._start_reconnect_loop()
        return success

    def disconnect(self) -> None:
        self._user_disconnect = True
        self._stop_reconnect_thread()
        self._close_socket(emit_event=True, reason="Disconnected.", unexpected=False)

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        profile = self.active_profile
        if not profile:
            raise RuntimeError("No LAN profile is active.")
        line_ending = line_ending_override or profile.line_ending
        payload = apply_line_ending(text, line_ending)
        self._write(payload, text)

    def send_bytes(self, data: bytes) -> None:
        display = "HEX " + format_hex_bytes(data)
        self._write(data, display)

    def _write(self, data: bytes, display_text: str) -> None:
        with self._lock:
            connection = self._socket
        if connection is None:
            raise RuntimeError("LAN endpoint is not connected.")
        try:
            connection.sendall(data)
        except OSError as exc:
            self._emit("error", f"Write failed: {exc}")
            self._handle_connection_loss(str(exc))
            raise RuntimeError(str(exc)) from exc
        self._emit("tx", display_text)

    def _attempt_connect(self, profile: LanProfile, reconnect_attempt: bool) -> bool:
        if not profile.host.strip() or not 1 <= int(profile.port) <= 65535:
            if not reconnect_attempt:
                self._emit("error", "Connect failed: LAN host and port are required.")
            return False
        timeout = max(profile.timeout_ms, 10) / 1000
        try:
            connection = self._socket_factory((profile.host, int(profile.port)), timeout)
            connection.settimeout(timeout)
        except OSError as exc:
            if not reconnect_attempt:
                self._emit("error", f"Connect failed: {exc}")
            return False
        with self._lock:
            self._socket = connection
            self._profile = deepcopy(profile)
            self._reader_stop = Event()
            self._reader_thread = Thread(
                target=self._reader_loop,
                args=(connection, self._reader_stop),
                daemon=True,
                name="lan-reader",
            )
            self._reader_thread.start()
        endpoint = profile.endpoint()
        self._emit("connection", "connected")
        self._emit("status", f"Connected to {endpoint}.")
        return True

    def _reader_loop(self, connection: SocketLike, stop_event: Event) -> None:
        while not stop_event.is_set():
            try:
                payload = connection.recv(4096)
            except socket.timeout:
                continue
            except OSError as exc:
                if stop_event.is_set():
                    return
                self._handle_connection_loss(str(exc))
                return
            if not payload:
                if not stop_event.is_set():
                    self._handle_connection_loss("Remote host closed the connection.")
                return
            self._emit("rx", decode_serial_bytes(payload), raw=payload)

    def _handle_connection_loss(self, reason: str) -> None:
        self._close_socket(
            emit_event=True,
            reason=f"Connection lost: {reason}",
            unexpected=True,
        )
        profile = self.active_profile
        if profile and profile.auto_reconnect and not self._user_disconnect:
            self._start_reconnect_loop()

    def _start_reconnect_loop(self) -> None:
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        self._reconnect_stop = Event()
        self._reconnect_thread = Thread(
            target=self._reconnect_loop,
            args=(self._reconnect_stop,),
            daemon=True,
            name="lan-reconnect",
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self, stop_event: Event) -> None:
        profile = self.active_profile
        if not profile:
            return
        interval_ms = max(
            int(getattr(profile, "reconnect_initial_delay_ms", LAN_RECONNECT_RETRY_INTERVAL_MS)),
            100,
        )
        self._emit(
            "status",
            f"Auto-reconnect armed. Retrying every {interval_ms} ms.",
        )
        while not stop_event.wait(interval_ms / 1000):
            if self._user_disconnect or self.is_connected:
                return
            profile = self.active_profile
            if not profile:
                return
            if self._attempt_connect(profile, reconnect_attempt=True):
                self._emit("status", "Auto-reconnect succeeded.")
                return
            # No per-attempt "." here: the retry state lives in the connection chip
            # (pulsing "Retrying" pill), not as transcript/log spam.

    def _stop_reconnect_thread(self) -> None:
        thread = self._reconnect_thread
        if thread and thread.is_alive():
            self._reconnect_stop.set()
            if thread is not current_thread():
                thread.join(timeout=1.0)
        self._reconnect_thread = None

    def _close_socket(self, *, emit_event: bool, reason: str = "", unexpected: bool = False) -> None:
        with self._lock:
            connection = self._socket
            reader_thread = self._reader_thread
            reader_stop = self._reader_stop
            self._socket = None
            self._profile = None
            self._reader_thread = None
            self._reader_stop = Event()
        if reader_stop:
            reader_stop.set()
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        if reader_thread and reader_thread.is_alive() and reader_thread is not current_thread():
            reader_thread.join(timeout=1.0)
        if emit_event and connection is not None:
            self._emit("connection", "disconnected")
            if reason:
                self._emit("error" if unexpected else "status", reason)

    def _emit(self, kind: str, message: str, *, raw: bytes = b"") -> None:
        event = SerialEvent(kind=kind, message=message, raw=raw)
        self.events.put(event)
        with self._lock:
            subscribers = list(self._event_subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
