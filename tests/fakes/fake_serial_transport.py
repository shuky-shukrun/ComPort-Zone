"""In-memory ``SerialTransportAdapter`` stand-in used by CLI and control-panel
tests.

Backed by a real :class:`~ComPort_Zone.port_channel.PortChannel` over a
:class:`tests.fakes.fake_raw_transport.FakeRawTransport`, so ``query_text`` /
``query_bytes`` / ``send_text`` / ``subscribe_monitor`` behave exactly like the
production adapter — structural request/response correlation included — while
still recording high-level calls and letting tests stage device replies.

* ``queue_response(raw)`` — delivered as the reply to the next write (use for
  send/query-with-reply tests where the device answers a command).
* ``stage_rx(raw)`` — delivered to a subscriber as soon as it subscribes (use
  for listen-style tests where the device is already chattering).
* ``push_rx_now(raw)`` — delivered to current subscribers immediately.
"""

from __future__ import annotations

from collections import deque
from queue import Queue
from threading import Lock
from typing import Any

from ComPort_Zone.core.models import apply_line_ending
from ComPort_Zone.core.port_channel import (
    NORMAL,
    MonitorHub,
    PortChannel,
    SerialEvent,
    decode_serial_bytes,
    format_hex_bytes,
)
from ComPort_Zone.core.transports import EndpointInfo

from tests.fakes.fake_raw_transport import FakeRawTransport


class FakeSerialTransport:
    kind = "serial"

    def __init__(self) -> None:
        self._raw = FakeRawTransport(read_timeout=0.005)
        self._raw.open()
        self._raw.set_responder(self._respond)
        self._hub = MonitorHub()
        self._channel = PortChannel(self._raw, hub=self._hub)
        self._channel.start()
        self._lock = Lock()
        self._response_queue: deque[bytes] = deque()
        self._pending_rx: list[bytes] = []
        self._connected = False
        self.connect_returns = True
        self._ports: list[dict[str, Any]] = []
        self._endpoints: list[EndpointInfo] = []
        # Recording surfaces for assertions:
        self.connect_calls: list[Any] = []
        self.disconnect_calls: int = 0
        self.sent_text: list[tuple[str, str | None]] = []
        self.sent_bytes: list[bytes] = []
        # TX origin per send, in call order ("" = user/batch, "control_panel" = poll).
        self.sent_sources: list[str] = []
        self.dtr: bool = True
        self.rts: bool = True
        self.break_count: int = 0

    def _respond(self, payload: bytes) -> bytes | None:
        with self._lock:
            if self._response_queue:
                return self._response_queue.popleft()
        return None

    # ----------------------------------- TransportAdapter Protocol surface

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_reconnecting(self) -> bool:
        return False

    @property
    def channel(self) -> PortChannel:
        return self._channel

    def list_endpoints(self) -> list[EndpointInfo]:
        if self._endpoints:
            return list(self._endpoints)
        return [
            EndpointInfo(
                id=str(item.get("device", "")),
                label=str(item.get("device", "")),
                description=str(item.get("description", "")),
                metadata={k: str(v) for k, v in item.items()},
            )
            for item in self._ports
        ]

    def list_ports(self) -> list[dict[str, str]]:
        return list(self._ports)

    def connect(self, profile: Any) -> bool:
        self.connect_calls.append(profile)
        if self.connect_returns:
            self._connected = True
        return self.connect_returns

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    def send_text(
        self,
        text: str,
        line_ending_override: str | None = None,
        *,
        source: str = "",
        priority: int = NORMAL,
        quiet_read: float = 0.0,
    ):
        self.sent_text.append((text, line_ending_override))
        self.sent_sources.append(source)
        payload = apply_line_ending(text, line_ending_override or "CRLF")
        return self._channel.write(
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
        self.sent_bytes.append(data)
        self.sent_sources.append(source)
        return self._channel.write(
            data,
            source=source,
            display="HEX " + format_hex_bytes(data),
            priority=priority,
            quiet_read=quiet_read,
        )

    def query_text(
        self,
        text: str,
        line_ending_override: str | None = None,
        *,
        matcher,
        timeout: float,
        source: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ):
        self.sent_text.append((text, line_ending_override))
        self.sent_sources.append(source)
        payload = apply_line_ending(text, line_ending_override or "CRLF")
        return self._channel.query(
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
        matcher,
        timeout: float,
        source: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ):
        self.sent_bytes.append(data)
        self.sent_sources.append(source)
        return self._channel.query(
            data,
            matcher=matcher,
            timeout=timeout,
            source=source,
            display="HEX " + format_hex_bytes(data),
            priority=priority,
            pre_read_delay=pre_read_delay,
        )

    def set_dtr(self, value: bool) -> bool:
        if not self._connected:
            return False
        self.dtr = bool(value)
        return True

    def set_rts(self, value: bool) -> bool:
        if not self._connected:
            return False
        self.rts = bool(value)
        return True

    def send_break(self, duration: float = 0.25) -> bool:
        if not self._connected:
            return False
        self.break_count += 1
        return True

    def signal_state(self) -> tuple[bool, bool] | None:
        if not self._connected:
            return None
        return (self.dtr, self.rts)

    def supports_signals(self) -> bool:
        return True

    def subscribe_monitor(self) -> Queue[SerialEvent]:
        queue = self._hub.subscribe()
        # Replay any staged "already chattering" RX as discrete events (so a
        # per-line filter sees each one separately, matching real framing).
        for raw in self._pending_rx:
            self._hub.publish(SerialEvent(kind="rx", message=decode_serial_bytes(raw), raw=raw))
        return queue

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None:
        self._hub.unsubscribe(queue)

    def emit_event(self, event: SerialEvent) -> None:
        self._hub.publish(event)

    # --------------------------------------------- test-fixture helpers

    def set_ports(self, ports: list[dict[str, Any]]) -> None:
        self._ports = list(ports)

    def set_endpoints(self, endpoints: list[EndpointInfo]) -> None:
        self._endpoints = list(endpoints)

    def stage_rx(self, raw: bytes) -> None:
        """Queue an RX payload delivered as soon as a subscriber subscribes."""
        self._pending_rx.append(raw)

    def queue_response(self, raw: bytes) -> None:
        """Queue an RX payload delivered as the reply to the next send/query."""
        with self._lock:
            self._response_queue.append(raw)

    def push_rx_now(self, raw: bytes) -> None:
        """Deliver an RX payload to current subscribers immediately."""
        self._hub.publish(SerialEvent(kind="rx", message=decode_serial_bytes(raw), raw=raw))

    def shutdown(self) -> None:
        self._channel.stop()
