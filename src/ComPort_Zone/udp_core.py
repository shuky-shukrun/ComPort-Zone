"""UDP connection management on top of the serialized port channel.

Mirrors :class:`ComPort_Zone.lan_core.LanClient` — same lifecycle, monitor hub,
and send/query surface — with two deliberate differences:

* **No reconnect loop.** Opening a datagram socket is ``socket()`` +
  ``connect()``, which performs no network I/O. It fails only on a blank/bad
  endpoint, an unresolvable host, or local resource exhaustion — all
  deterministic. Retrying on a timer would be a busy-wait that cannot change
  the outcome, and there is no link-loss signal to retry *after*.
* **Datagram framing.** The channel is built with a
  :class:`~ComPort_Zone.port_channel.DatagramMatcher` default, so a caller with
  no explicit parse rule gets one whole datagram as the reply rather than
  waiting for a CR/LF that many UDP devices never send.
"""

from __future__ import annotations

from copy import deepcopy
from threading import Lock

from .models import UdpProfile, apply_line_ending
from .port_channel import (
    NORMAL,
    DatagramMatcher,
    Matcher,
    MonitorHub,
    PortChannel,
    SerialEvent,
    format_hex_bytes,
)
from .raw_transport import TransportError, UdpRawTransport, UdpSocketFactory

__all__ = [
    "UdpClient",
]


class UdpClient:
    def __init__(self, socket_factory: UdpSocketFactory | None = None) -> None:
        self._hub = MonitorHub()
        self._lock = Lock()
        self._socket_factory = socket_factory
        self._raw: UdpRawTransport | None = None
        self._channel: PortChannel | None = None
        self._profile: UdpProfile | None = None
        self._desired_profile: UdpProfile | None = None

    # -- state --------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        channel = self._channel
        return channel is not None and channel.is_open

    @property
    def is_reconnecting(self) -> bool:
        # Kept as a property so the adapter and the GUI's connection_state()
        # need no UDP special case; there is simply never a retry in flight.
        return False

    @property
    def active_profile(self) -> UdpProfile | None:
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
        the monitor stream, independent of any active socket."""
        self._hub.publish(event)

    # -- connection lifecycle ----------------------------------------------

    def connect(self, profile: UdpProfile) -> bool:
        self._desired_profile = deepcopy(profile)
        self._teardown_channel()
        return self._attempt_connect(profile)

    def disconnect(self) -> None:
        self._teardown_channel(emit_disconnect=True, reason="Disconnected.")

    def _attempt_connect(self, profile: UdpProfile) -> bool:
        raw = UdpRawTransport(deepcopy(profile), socket_factory=self._socket_factory)
        try:
            raw.open()
        except TransportError as exc:
            self._emit("error", f"Connect failed: {exc}")
            return False
        channel = PortChannel(
            raw,
            hub=self._hub,
            on_connection_lost=self._on_channel_loss,
            default_matcher=DatagramMatcher,
        )
        channel.start()
        with self._lock:
            self._raw = raw
            self._channel = channel
            self._profile = deepcopy(profile)
        self._emit("connection", "connected")
        self._emit("status", f"UDP socket open to {profile.endpoint()}.")
        return True

    def _on_channel_loss(self, reason: str) -> None:
        # Runs on the channel's own thread, so do not join the channel here —
        # just release the socket. A genuine OSError on the socket is the only
        # way to get here; there is nothing to reconnect to.
        with self._lock:
            raw = self._raw
            self._raw = None
            self._channel = None
            self._profile = None
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass

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
            raise RuntimeError("No UDP profile is active.")
        channel = self._channel
        if channel is None:
            raise RuntimeError("UDP endpoint is not open.")
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
            raise RuntimeError("UDP endpoint is not open.")
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
            raise RuntimeError("UDP endpoint is not open.")
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
            raise RuntimeError("No UDP profile is active.")
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

    # -- control lines (not supported on UDP) ------------------------------

    def set_dtr(self, value: bool) -> bool:
        return False

    def set_rts(self, value: bool) -> bool:
        return False

    def send_break(self, duration: float = 0.25) -> bool:
        return False

    def current_signal_state(self) -> tuple[bool, bool] | None:
        return None

    # -- helpers ------------------------------------------------------------

    def _emit(self, kind: str, message: str, *, source: str = "") -> None:
        self._hub.publish(SerialEvent(kind=kind, message=message, source=source))
