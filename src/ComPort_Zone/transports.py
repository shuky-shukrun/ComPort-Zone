from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Queue
from typing import Any, Protocol, runtime_checkable

from .lan_core import LanClient
from .models import LanProfile, SerialProfile
from .serial_core import SerialClient, SerialEvent


@dataclass(slots=True)
class TransportEvent:
    kind: str
    message: str
    raw: bytes = b""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone()
    )


@dataclass(slots=True)
class EndpointInfo:
    id: str
    label: str
    description: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TransportProfile:
    kind: str = "serial"
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_serial_profile(cls, profile: SerialProfile) -> "TransportProfile":
        return cls(kind="serial", settings=profile.to_dict())

    @classmethod
    def from_lan_profile(cls, profile: LanProfile) -> "TransportProfile":
        return cls(kind="lan", settings=profile.to_dict())

    def to_serial_profile(self) -> SerialProfile:
        return SerialProfile.from_dict(self.settings)

    def to_lan_profile(self) -> LanProfile:
        return LanProfile.from_dict(self.settings)


@runtime_checkable
class TransportAdapter(Protocol):
    events: Queue[SerialEvent]

    @property
    def is_connected(self) -> bool:
        ...

    @property
    def is_reconnecting(self) -> bool:
        ...

    def list_endpoints(self) -> list[EndpointInfo]:
        ...

    def connect(self, profile: TransportProfile | SerialProfile | LanProfile) -> bool:
        ...

    def disconnect(self) -> None:
        ...

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        ...

    def send_bytes(self, data: bytes) -> None:
        ...

    def set_dtr(self, value: bool) -> bool:
        ...

    def set_rts(self, value: bool) -> bool:
        ...

    def send_break(self, duration: float = 0.25) -> bool:
        ...

    def signal_state(self) -> tuple[bool, bool] | None:
        ...

    def supports_signals(self) -> bool:
        ...

    def subscribe_events(self) -> Queue[SerialEvent]:
        ...

    def unsubscribe_events(self, queue: Queue[SerialEvent]) -> None:
        ...


class SerialTransportAdapter:
    kind = "serial"

    def __init__(self, client: SerialClient | None = None) -> None:
        self.client = client or SerialClient()

    @property
    def events(self) -> Queue[SerialEvent]:
        return self.client.events

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    @property
    def is_reconnecting(self) -> bool:
        return self.client.is_reconnecting

    @property
    def active_profile(self) -> SerialProfile | None:
        return self.client.active_profile

    def list_endpoints(self) -> list[EndpointInfo]:
        endpoints: list[EndpointInfo] = []
        for port in self.client.list_ports():
            device = str(port.get("device", "")).strip()
            description = str(port.get("description", "")).strip()
            endpoints.append(
                EndpointInfo(
                    id=device,
                    label=device,
                    description=description,
                    metadata={key: str(value) for key, value in port.items()},
                )
            )
        return endpoints

    def list_ports(self) -> list[dict[str, str]]:
        return [
            {
                "device": endpoint.id,
                "description": endpoint.description or endpoint.label,
                "hwid": endpoint.metadata.get("hwid", ""),
            }
            for endpoint in self.list_endpoints()
        ]

    def connect(self, profile: TransportProfile | SerialProfile) -> bool:
        if isinstance(profile, TransportProfile):
            if profile.kind != self.kind:
                raise ValueError(f"Serial transport cannot connect profile kind {profile.kind!r}.")
            profile = profile.to_serial_profile()
        return self.client.connect(profile)

    def disconnect(self) -> None:
        self.client.disconnect()

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        self.client.send_text(text, line_ending_override)

    def send_bytes(self, data: bytes) -> None:
        self.client.send_bytes(data)

    def set_dtr(self, value: bool) -> bool:
        return self.client.set_dtr(value)

    def set_rts(self, value: bool) -> bool:
        return self.client.set_rts(value)

    def send_break(self, duration: float = 0.25) -> bool:
        return self.client.send_break(duration)

    def signal_state(self) -> tuple[bool, bool] | None:
        return self.client.current_signal_state()

    def supports_signals(self) -> bool:
        return True

    def subscribe_events(self) -> Queue[SerialEvent]:
        return self.client.subscribe_events()

    def unsubscribe_events(self, queue: Queue[SerialEvent]) -> None:
        self.client.unsubscribe_events(queue)


class LanTransportAdapter:
    kind = "lan"

    def __init__(self, client: LanClient | None = None) -> None:
        self.client = client or LanClient()

    @property
    def events(self) -> Queue[SerialEvent]:
        return self.client.events

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    @property
    def is_reconnecting(self) -> bool:
        return self.client.is_reconnecting

    @property
    def active_profile(self) -> LanProfile | None:
        return self.client.active_profile

    def list_endpoints(self) -> list[EndpointInfo]:
        return []

    def connect(self, profile: TransportProfile | LanProfile) -> bool:
        if isinstance(profile, TransportProfile):
            if profile.kind != self.kind:
                raise ValueError(f"LAN transport cannot connect profile kind {profile.kind!r}.")
            profile = profile.to_lan_profile()
        return self.client.connect(profile)

    def disconnect(self) -> None:
        self.client.disconnect()

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        self.client.send_text(text, line_ending_override)

    def send_bytes(self, data: bytes) -> None:
        self.client.send_bytes(data)

    def set_dtr(self, value: bool) -> bool:
        return False

    def set_rts(self, value: bool) -> bool:
        return False

    def send_break(self, duration: float = 0.25) -> bool:
        return False

    def signal_state(self) -> tuple[bool, bool] | None:
        return None

    def supports_signals(self) -> bool:
        return False

    def subscribe_events(self) -> Queue[SerialEvent]:
        return self.client.subscribe_events()

    def unsubscribe_events(self, queue: Queue[SerialEvent]) -> None:
        self.client.unsubscribe_events(queue)


def create_transport_adapter(kind: str) -> TransportAdapter:
    if kind == "lan":
        return LanTransportAdapter()
    return SerialTransportAdapter()
