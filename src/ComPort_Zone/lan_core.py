from __future__ import annotations

import socket
import time
from copy import deepcopy
from queue import Queue
from contextlib import contextmanager
from threading import Event, Lock, RLock, Thread, current_thread
from typing import Callable, Protocol

# When the dispatcher acquires :meth:`LanClient.hold_wire` after a
# different sender (typically the bound terminal) just released it,
# any in-flight reply to that previous send is still sitting in the
# socket buffer / between recv() and event emission. Sleep this long
# under the lock so the reader thread has time to push those events
# into rx_queue, where the dispatcher's drain can clean them up
# before our send goes out. Without this we get the "tile A receives
# tile B's value" cross-talk symptom on every concurrent send.
# 30 ms covers localhost (<1 ms RTT) and real LAN (1–20 ms RTT)
# comfortably without making polled tiles feel sluggish.
POST_ACQUIRE_SETTLE_S = 0.030

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
        # Wire-transaction lock. Mirrors :attr:`SerialClient._wire_lock`
        # — held end-to-end through each ``_write`` (so two threads can
        # never bisect a TCP ``sendall``) AND held by callers across
        # multi-step transactions via :meth:`hold_wire` (so the
        # dispatcher's RX window can't be polluted by a racing terminal
        # send). Reentrant so a holder can call ``send_text`` inside
        # the held region without deadlocking on its own write path.
        self._wire_lock = RLock()
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

    def send_text(
        self, text: str, line_ending_override: str | None = None, *, source: str = ""
    ) -> None:
        profile = self.active_profile
        if not profile:
            raise RuntimeError("No LAN profile is active.")
        line_ending = line_ending_override or profile.line_ending
        payload = apply_line_ending(text, line_ending)
        self._write(payload, text, source=source)

    def send_bytes(self, data: bytes, *, source: str = "") -> None:
        display = "HEX " + format_hex_bytes(data)
        self._write(data, display, source=source)

    def _write(self, data: bytes, display_text: str, *, source: str = "") -> None:
        # Hold the wire lock through the WHOLE send: two threads can
        # never bisect ``sendall`` (which on Windows / TCP doesn't
        # interleave the bytes of a single call, but DOES race for
        # ordering with another sendall — meaning the panel's MEAS?
        # could end up arriving after the terminal's *IDN?, and the
        # dispatcher's parse window would then capture the terminal's
        # reply). The hold also extends to anyone above us who entered
        # :meth:`hold_wire` for a multi-step transaction.
        with self._wire_lock:
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
            self._emit("tx", display_text, source=source)

    @contextmanager
    def hold_wire(self):
        """Reserve the wire for a multi-step transaction.

        Same contract as :meth:`SerialClient.hold_wire`. Without this
        the control-panel dispatcher's RX window would absorb the
        device's reply to a racing terminal send (visible as "tile shows
        a different tile's value"). Reentrant so the holder can call
        ``send_text`` inside.

        After acquiring the lock we wait briefly (``POST_ACQUIRE_SETTLE_S``)
        so any in-flight reply to the *previous* holder's send lands in
        the subscriber queues before our drain runs. Without this the
        dispatcher's drain races the reader thread — TCP delivers bytes
        asynchronously, and the GIL can delay the reader thread by
        milliseconds, leaving stale bytes that only show up after our
        send. Settling here means the dispatcher's drain catches them.
        """
        with self._wire_lock:
            time.sleep(POST_ACQUIRE_SETTLE_S)
            yield

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

    def _emit(self, kind: str, message: str, *, raw: bytes = b"", source: str = "") -> None:
        event = SerialEvent(kind=kind, message=message, raw=raw, source=source)
        self.events.put(event)
        with self._lock:
            subscribers = list(self._event_subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
