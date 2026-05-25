"""In-memory ``SerialTransportAdapter`` stand-in used by CLI tests.

Implements the same surface as :class:`ComPort_Zone.core.transports.SerialTransportAdapter`
without touching pyserial. RX events are seeded on construction (or via
:meth:`push_rx`) and delivered to subscribers as soon as they subscribe,
which makes the CLI's RX timing deterministic under test.
"""

from __future__ import annotations

from queue import Queue
from typing import Any

from ComPort_Zone.core.serial_core import SerialEvent
from ComPort_Zone.core.transports import EndpointInfo


class FakeSerialTransport:
    kind = "serial"

    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self._subscribers: list[Queue[SerialEvent]] = []
        self._connected: bool = False
        self._ports: list[dict[str, Any]] = []
        self._endpoints: list[EndpointInfo] = []
        # ``_pending_rx`` is delivered to every NEW subscriber on subscribe —
        # use for listen-style tests where the device is already chattering.
        # ``_response_queue`` is delivered to CURRENT subscribers AFTER the
        # next send call — use for run/send-with-expect tests where the
        # device responds to commands.
        self._pending_rx: list[bytes] = []
        self._response_queue: list[bytes] = []
        self.connect_returns: bool = True
        # Recording surfaces for assertions:
        self.connect_calls: list[Any] = []
        self.disconnect_calls: int = 0
        self.sent_text: list[tuple[str, str | None]] = []
        self.sent_bytes: list[bytes] = []

    # ----------------------------------- TransportAdapter Protocol surface

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_reconnecting(self) -> bool:
        return False

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

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        self.sent_text.append((text, line_ending_override))
        self._deliver_next_response()

    def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)
        self._deliver_next_response()

    def _deliver_next_response(self) -> None:
        if not self._response_queue:
            return
        raw = self._response_queue.pop(0)
        event = SerialEvent(kind="rx", message=raw.decode("utf-8", "replace"), raw=raw)
        for subscriber in self._subscribers:
            subscriber.put(event)

    def subscribe_events(self) -> Queue[SerialEvent]:
        queue: Queue[SerialEvent] = Queue()
        self._subscribers.append(queue)
        for raw in self._pending_rx:
            queue.put(SerialEvent(kind="rx", message=raw.decode("utf-8", "replace"), raw=raw))
        return queue

    def unsubscribe_events(self, queue: Queue[SerialEvent]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    # --------------------------------------------- test-fixture helpers

    def set_ports(self, ports: list[dict[str, Any]]) -> None:
        self._ports = list(ports)

    def set_endpoints(self, endpoints: list[EndpointInfo]) -> None:
        self._endpoints = list(endpoints)

    def stage_rx(self, raw: bytes) -> None:
        """Queue an RX payload that every future subscriber will receive."""
        self._pending_rx.append(raw)

    def queue_response(self, raw: bytes) -> None:
        """Queue an RX payload delivered to current subscribers after the
        next ``send_text``/``send_bytes`` call. Use this for run/send tests
        where the device responds to a command rather than chattering on
        its own.
        """
        self._response_queue.append(raw)

    def push_rx_now(self, raw: bytes) -> None:
        """Deliver an RX event to all current subscribers immediately."""
        event = SerialEvent(kind="rx", message=raw.decode("utf-8", "replace"), raw=raw)
        for subscriber in self._subscribers:
            subscriber.put(event)
