from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Queue
from typing import Any, Protocol, runtime_checkable

from .models import SerialProfile
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

    def to_serial_profile(self) -> SerialProfile:
        return SerialProfile.from_dict(self.settings)


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

    def connect(self, profile: TransportProfile | SerialProfile) -> bool:
        ...

    def disconnect(self) -> None:
        ...

    def send_text(self, text: str, line_ending_override: str | None = None) -> None:
        ...

    def send_bytes(self, data: bytes) -> None:
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

    def subscribe_events(self) -> Queue[SerialEvent]:
        return self.client.subscribe_events()

    def unsubscribe_events(self, queue: Queue[SerialEvent]) -> None:
        self.client.unsubscribe_events(queue)
