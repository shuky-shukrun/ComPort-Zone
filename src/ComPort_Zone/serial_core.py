from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Queue
from threading import Event, Lock, Thread, current_thread
from typing import Any

import serial
from serial import SerialException
from serial.tools import list_ports

from .models import SerialProfile, apply_line_ending

FLOW_CONTROL_FLAGS = {
    "None": {"rtscts": False, "xonxoff": False, "dsrdtr": False},
    "RTS/CTS": {"rtscts": True, "xonxoff": False, "dsrdtr": False},
    "XON/XOFF": {"rtscts": False, "xonxoff": True, "dsrdtr": False},
    "DSR/DTR": {"rtscts": False, "xonxoff": False, "dsrdtr": True},
}


@dataclass(slots=True)
class SerialEvent:
    kind: str
    message: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone()
    )


class SerialClient:
    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self._lock = Lock()
        self._serial: serial.Serial | None = None
        self._profile: SerialProfile | None = None
        self._desired_profile: SerialProfile | None = None
        self._reader_thread: Thread | None = None
        self._reader_stop = Event()
        self._reconnect_thread: Thread | None = None
        self._reconnect_stop = Event()
        self._user_disconnect = True

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._serial is not None and self._serial.is_open

    @property
    def active_profile(self) -> SerialProfile | None:
        with self._lock:
            return deepcopy(self._profile or self._desired_profile)

    def list_ports(self) -> list[dict[str, str]]:
        ports = []
        for item in list_ports.comports():
            ports.append(
                {
                    "device": item.device,
                    "description": item.description or item.device,
                    "hwid": item.hwid or "",
                }
            )
        ports.sort(key=lambda item: item["device"])
        return ports

    def connect(self, profile: SerialProfile) -> bool:
        self._desired_profile = deepcopy(profile)
        self._user_disconnect = False
        self._stop_reconnect_thread()
        self._close_serial(emit_event=False)
        success = self._attempt_connect(profile, reconnect_attempt=False)
        if not success and profile.auto_reconnect:
            self._start_reconnect_loop()
        return success

    def disconnect(self) -> None:
        self._user_disconnect = True
        self._stop_reconnect_thread()
        self._close_serial(emit_event=True, reason="Disconnected.", unexpected=False)

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        profile = self.active_profile
        if not profile:
            raise RuntimeError("No serial profile is active.")
        line_ending = line_ending_override or profile.line_ending
        payload = apply_line_ending(text, line_ending)
        self._write(payload, text)

    def send_bytes(self, data: bytes) -> None:
        display = "HEX " + " ".join(f"{byte:02X}" for byte in data)
        self._write(data, display)

    def _write(self, data: bytes, display_text: str) -> None:
        with self._lock:
            port = self._serial
        if not port or not port.is_open:
            raise RuntimeError("Serial port is not connected.")
        try:
            port.write(data)
            port.flush()
        except SerialException as exc:
            self._emit("error", f"Write failed: {exc}")
            self._handle_connection_loss(str(exc))
            raise RuntimeError(str(exc)) from exc
        self._emit("tx", display_text)

    def _attempt_connect(self, profile: SerialProfile, reconnect_attempt: bool) -> bool:
        flags = FLOW_CONTROL_FLAGS.get(profile.flow_control, FLOW_CONTROL_FLAGS["None"])
        try:
            port = serial.Serial(
                port=profile.port,
                baudrate=profile.baudrate,
                bytesize=profile.bytesize,
                parity=profile.parity,
                stopbits=profile.stopbits,
                timeout=max(profile.timeout_ms, 10) / 1000,
                write_timeout=1,
                **flags,
            )
            port.dtr = profile.dtr
            port.rts = profile.rts
        except SerialException as exc:
            prefix = "Reconnect" if reconnect_attempt else "Connect"
            self._emit("error", f"{prefix} failed: {exc}")
            return False
        with self._lock:
            self._serial = port
            self._profile = deepcopy(profile)
            self._reader_stop = Event()
            self._reader_thread = Thread(
                target=self._reader_loop,
                args=(port, self._reader_stop),
                daemon=True,
                name="serial-reader",
            )
            self._reader_thread.start()
        self._emit("connection", "connected")
        self._emit("status", f"Connected to {profile.port} at {profile.baudrate} baud.")
        return True

    def _reader_loop(self, port: serial.Serial, stop_event: Event) -> None:
        while not stop_event.is_set():
            try:
                waiting = port.in_waiting
                payload = port.read(waiting or 1)
            except SerialException as exc:
                if stop_event.is_set():
                    return
                self._handle_connection_loss(str(exc))
                return
            if payload:
                self._emit("rx", payload.decode("utf-8", errors="replace"))

    def _handle_connection_loss(self, reason: str) -> None:
        self._close_serial(
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
            name="serial-reconnect",
        )
        self._reconnect_thread.start()

    def _reconnect_loop(self, stop_event: Event) -> None:
        profile = self.active_profile
        if not profile:
            return
        delay_ms = max(profile.reconnect_initial_delay_ms, 200)
        max_delay_ms = max(profile.reconnect_max_delay_ms, delay_ms)
        self._emit("status", f"Auto-reconnect armed. Retrying in {delay_ms} ms.")
        while not stop_event.wait(delay_ms / 1000):
            if self._user_disconnect or self.is_connected:
                return
            profile = self.active_profile
            if not profile:
                return
            self._emit("status", f"Trying to reconnect to {profile.port}...")
            if self._attempt_connect(profile, reconnect_attempt=True):
                self._emit("status", "Auto-reconnect succeeded.")
                return
            delay_ms = min(delay_ms * 2, max_delay_ms)
            self._emit("status", f"Reconnect failed. Next attempt in {delay_ms} ms.")

    def _stop_reconnect_thread(self) -> None:
        thread = self._reconnect_thread
        if thread and thread.is_alive():
            self._reconnect_stop.set()
            if thread is not current_thread():
                thread.join(timeout=1.0)
        self._reconnect_thread = None

    def _close_serial(self, *, emit_event: bool, reason: str = "", unexpected: bool = False) -> None:
        with self._lock:
            port = self._serial
            reader_thread = self._reader_thread
            reader_stop = self._reader_stop
            self._serial = None
            self._profile = None
            self._reader_thread = None
            self._reader_stop = Event()
        if reader_stop:
            reader_stop.set()
        if port:
            try:
                port.close()
            except SerialException:
                pass
        if reader_thread and reader_thread.is_alive() and reader_thread is not current_thread():
            reader_thread.join(timeout=1.0)
        if emit_event and port:
            self._emit("connection", "disconnected")
            if reason:
                self._emit("error" if unexpected else "status", reason)

    def _emit(self, kind: str, message: str) -> None:
        self.events.put(SerialEvent(kind=kind, message=message))
