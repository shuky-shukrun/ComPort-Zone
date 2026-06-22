"""LAN (TCP) connection management on top of the serialized port channel.

Mirrors :class:`ComPort_Zone.serial_core.SerialClient` exactly — same
lifecycle, monitor hub, and reconnect — differing only in the underlying
:class:`~ComPort_Zone.raw_transport.LanRawTransport`. The channel above is
identical, which is what makes serial and LAN behave the same.
"""

from __future__ import annotations

from copy import deepcopy
from threading import Event, Lock, Thread, current_thread

from .models import LanProfile, apply_line_ending
from .port_channel import (
    NORMAL,
    Matcher,
    MonitorHub,
    PortChannel,
    SerialEvent,
    decode_serial_bytes,
    format_hex_bytes,
)
from .raw_transport import LanRawTransport, SocketFactory, TransportError

# Back-compat alias: callers/tests historically referenced ``SocketLike`` from
# this module. The protocol now lives in raw_transport.
from .raw_transport import _SocketLike as SocketLike  # noqa: F401

__all__ = [
    "LAN_RECONNECT_RETRY_INTERVAL_MS",
    "LanClient",
    "SocketLike",
]

LAN_RECONNECT_RETRY_INTERVAL_MS = 1000


class LanClient:
    def __init__(self, socket_factory: SocketFactory | None = None) -> None:
        self._hub = MonitorHub()
        self._lock = Lock()
        self._socket_factory = socket_factory
        self._raw: LanRawTransport | None = None
        self._channel: PortChannel | None = None
        self._profile: LanProfile | None = None
        self._desired_profile: LanProfile | None = None
        self._reconnect_thread: Thread | None = None
        self._reconnect_stop = Event()
        self._user_disconnect = True

    # -- state --------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        channel = self._channel
        return channel is not None and channel.is_open

    @property
    def is_reconnecting(self) -> bool:
        thread = self._reconnect_thread
        return bool(thread and thread.is_alive())

    @property
    def active_profile(self) -> LanProfile | None:
        with self._lock:
            return deepcopy(self._profile or self._desired_profile)

    @property
    def channel(self) -> PortChannel | None:
        return self._channel

    # -- monitor ------------------------------------------------------------

    def subscribe_monitor(self):
        return self._hub.subscribe()

    def unsubscribe_monitor(self, queue) -> None:
        self._hub.unsubscribe(queue)

    def emit_event(self, event: SerialEvent) -> None:
        """Publish a display/log event (e.g. a batch-runner status line) on
        the monitor stream, independent of any active connection."""
        self._hub.publish(event)

    # -- connection lifecycle ----------------------------------------------

    def connect(self, profile: LanProfile) -> bool:
        self._desired_profile = deepcopy(profile)
        self._user_disconnect = False
        self._stop_reconnect_thread()
        self._teardown_channel()
        success = self._attempt_connect(profile, reconnect_attempt=False)
        if not success and profile.auto_reconnect:
            self._start_reconnect_loop()
        return success

    def disconnect(self) -> None:
        self._user_disconnect = True
        self._stop_reconnect_thread()
        self._teardown_channel(emit_disconnect=True, reason="Disconnected.")

    def _attempt_connect(self, profile: LanProfile, reconnect_attempt: bool) -> bool:
        raw = LanRawTransport(deepcopy(profile), socket_factory=self._socket_factory)
        try:
            raw.open()
        except TransportError as exc:
            if not reconnect_attempt:
                self._emit("error", f"Connect failed: {exc}")
            return False
        channel = PortChannel(
            raw, hub=self._hub, on_connection_lost=self._on_channel_loss
        )
        channel.start()
        with self._lock:
            self._raw = raw
            self._channel = channel
            self._profile = deepcopy(profile)
        self._emit("connection", "connected")
        self._emit("status", f"Connected to {profile.endpoint()}.")
        return True

    def _on_channel_loss(self, reason: str) -> None:
        with self._lock:
            raw = self._raw
            self._raw = None
            self._channel = None
            profile = self._profile
            self._profile = None
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
        if profile and profile.auto_reconnect and not self._user_disconnect:
            self._start_reconnect_loop()

    def _teardown_channel(self, *, emit_disconnect: bool = False, reason: str = "") -> None:
        with self._lock:
            channel = self._channel
            raw = self._raw
            had_connection = self._profile is not None
            self._channel = None
            self._raw = None
            self._profile = None
        if channel is not None:
            channel.stop()
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass
        if emit_disconnect and had_connection:
            self._emit("connection", "disconnected")
            if reason:
                self._emit("status", reason)

    # -- sending ------------------------------------------------------------

    def send_text(
        self,
        text: str,
        line_ending_override: str | None = None,
        *,
        source: str = "",
        priority: int = NORMAL,
        quiet_read: float = 0.0,
    ):
        profile = self.active_profile
        if not profile:
            raise RuntimeError("No LAN profile is active.")
        channel = self._channel
        if channel is None:
            raise RuntimeError("LAN endpoint is not connected.")
        payload = apply_line_ending(text, line_ending_override or profile.line_ending)
        return channel.write(
            payload, source=source, display=text, priority=priority, quiet_read=quiet_read
        )

    def send_bytes(
        self,
        data: bytes,
        *,
        source: str = "",
        priority: int = NORMAL,
        quiet_read: float = 0.0,
    ):
        channel = self._channel
        if channel is None:
            raise RuntimeError("LAN endpoint is not connected.")
        display = "HEX " + format_hex_bytes(data)
        return channel.write(
            data, source=source, display=display, priority=priority, quiet_read=quiet_read
        )

    def query(
        self,
        payload: bytes,
        *,
        matcher: Matcher,
        timeout: float,
        source: str = "",
        display: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ):
        channel = self._channel
        if channel is None:
            raise RuntimeError("LAN endpoint is not connected.")
        return channel.query(
            payload,
            matcher=matcher,
            timeout=timeout,
            source=source,
            display=display,
            priority=priority,
            pre_read_delay=pre_read_delay,
        )

    def query_text(
        self,
        text: str,
        line_ending_override: str | None = None,
        *,
        matcher: Matcher,
        timeout: float,
        source: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ):
        profile = self.active_profile
        if not profile:
            raise RuntimeError("No LAN profile is active.")
        payload = apply_line_ending(text, line_ending_override or profile.line_ending)
        return self.query(
            payload,
            matcher=matcher,
            timeout=timeout,
            source=source,
            display=text,
            priority=priority,
            pre_read_delay=pre_read_delay,
        )

    def query_bytes(
        self,
        data: bytes,
        *,
        matcher: Matcher,
        timeout: float,
        source: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ):
        return self.query(
            data,
            matcher=matcher,
            timeout=timeout,
            source=source,
            display="HEX " + format_hex_bytes(data),
            priority=priority,
            pre_read_delay=pre_read_delay,
        )

    # -- control lines (not supported on LAN) ------------------------------

    def set_dtr(self, value: bool) -> bool:
        return False

    def set_rts(self, value: bool) -> bool:
        return False

    def send_break(self, duration: float = 0.25) -> bool:
        return False

    def current_signal_state(self) -> tuple[bool, bool] | None:
        return None

    # -- reconnect ----------------------------------------------------------

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
        self._emit("status", f"Auto-reconnect armed. Retrying every {interval_ms} ms.")
        while not stop_event.wait(interval_ms / 1000):
            if self._user_disconnect or self.is_connected:
                return
            profile = self.active_profile
            if not profile:
                return
            if self._attempt_connect(profile, reconnect_attempt=True):
                self._emit("status", "Auto-reconnect succeeded.")
                return

    def _stop_reconnect_thread(self) -> None:
        thread = self._reconnect_thread
        if thread and thread.is_alive():
            self._reconnect_stop.set()
            if thread is not current_thread():
                thread.join(timeout=1.0)
        self._reconnect_thread = None

    # -- helpers ------------------------------------------------------------

    def _emit(self, kind: str, message: str, *, source: str = "") -> None:
        self._hub.publish(SerialEvent(kind=kind, message=message, source=source))
