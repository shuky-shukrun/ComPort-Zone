from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Queue
from typing import Any, Protocol, runtime_checkable

from .lan_core import LanClient
from .models import LanProfile, SerialProfile, UdpProfile
from .port_channel import NORMAL, LineMatcher, Matcher, PortChannel, SerialEvent, TxResult
from .serial_core import SerialClient
from .udp_core import UdpClient


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

    @classmethod
    def from_udp_profile(cls, profile: UdpProfile) -> "TransportProfile":
        return cls(kind="udp", settings=profile.to_dict())

    def to_serial_profile(self) -> SerialProfile:
        return SerialProfile.from_dict(self.settings)

    def to_lan_profile(self) -> LanProfile:
        return LanProfile.from_dict(self.settings)

    def to_udp_profile(self) -> UdpProfile:
        return UdpProfile.from_dict(self.settings)


@runtime_checkable
class TransportAdapter(Protocol):
    @property
    def is_connected(self) -> bool: ...

    @property
    def is_reconnecting(self) -> bool: ...

    @property
    def channel(self) -> PortChannel | None: ...

    def list_endpoints(self) -> list[EndpointInfo]: ...

    def default_matcher(self) -> Matcher: ...

    def connect(
        self, profile: TransportProfile | SerialProfile | LanProfile | UdpProfile
    ) -> bool: ...

    def disconnect(self) -> None: ...

    def send_text(
        self, text: str, line_ending_override: str | None = None, *, source: str = ""
    ) -> None: ...

    def send_bytes(self, data: bytes, *, source: str = "") -> None: ...

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
    ) -> "Future[TxResult]": ...

    def query_bytes(
        self,
        data: bytes,
        *,
        matcher: Matcher,
        timeout: float,
        source: str = "",
        priority: int = NORMAL,
        pre_read_delay: float = 0.0,
    ) -> "Future[TxResult]": ...

    def set_dtr(self, value: bool) -> bool: ...

    def set_rts(self, value: bool) -> bool: ...

    def send_break(self, duration: float = 0.25) -> bool: ...

    def signal_state(self) -> tuple[bool, bool] | None: ...

    def supports_signals(self) -> bool: ...

    def subscribe_monitor(self) -> Queue[SerialEvent]: ...

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None: ...


class _ClientAdapter:
    """Shared adapter body over a SerialClient/LanClient. Subclasses set
    ``kind`` and the accepted profile type."""

    def __init__(self, client) -> None:
        self.client = client

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    @property
    def is_reconnecting(self) -> bool:
        return self.client.is_reconnecting

    @property
    def active_profile(self):
        return self.client.active_profile

    @property
    def channel(self) -> PortChannel | None:
        return self.client.channel

    def default_matcher(self) -> Matcher:
        """Framing to use when the caller has no rule of its own. Byte-stream
        transports line-frame; datagram transports return a whole datagram."""
        channel = self.client.channel
        return channel.default_matcher() if channel is not None else LineMatcher()

    def disconnect(self) -> None:
        self.client.disconnect()

    def send_text(
        self,
        text: str,
        line_ending_override: str | None = None,
        *,
        source: str = "",
        priority: int = NORMAL,
        quiet_read: float = 0.0,
    ) -> None:
        # Forward optional kwargs only when set so plain sends keep the
        # legacy two-arg call shape some test stubs are written against.
        kwargs: dict[str, Any] = {}
        if source:
            kwargs["source"] = source
        if priority != NORMAL:
            kwargs["priority"] = priority
        if quiet_read:
            kwargs["quiet_read"] = quiet_read
        return self.client.send_text(text, line_ending_override, **kwargs)

    def send_bytes(
        self,
        data: bytes,
        *,
        source: str = "",
        priority: int = NORMAL,
        quiet_read: float = 0.0,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if source:
            kwargs["source"] = source
        if priority != NORMAL:
            kwargs["priority"] = priority
        if quiet_read:
            kwargs["quiet_read"] = quiet_read
        return self.client.send_bytes(data, **kwargs)

    def query_text(self, text, line_ending_override=None, **kwargs) -> "Future[TxResult]":
        return self.client.query_text(text, line_ending_override, **kwargs)

    def query_bytes(self, data, **kwargs) -> "Future[TxResult]":
        return self.client.query_bytes(data, **kwargs)

    def subscribe_monitor(self) -> Queue[SerialEvent]:
        return self.client.subscribe_monitor()

    def unsubscribe_monitor(self, queue: Queue[SerialEvent]) -> None:
        self.client.unsubscribe_monitor(queue)

    def emit_event(self, event: SerialEvent) -> None:
        self.client.emit_event(event)


class SerialTransportAdapter(_ClientAdapter):
    kind = "serial"

    def __init__(self, client: SerialClient | None = None) -> None:
        super().__init__(client or SerialClient())

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
                raise ValueError(
                    f"Serial transport cannot connect profile kind {profile.kind!r}."
                )
            profile = profile.to_serial_profile()
        return self.client.connect(profile)

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


class LanTransportAdapter(_ClientAdapter):
    kind = "lan"

    def __init__(self, client: LanClient | None = None) -> None:
        super().__init__(client or LanClient())

    def list_endpoints(self) -> list[EndpointInfo]:
        return []

    def connect(self, profile: TransportProfile | LanProfile) -> bool:
        if isinstance(profile, TransportProfile):
            if profile.kind != self.kind:
                raise ValueError(
                    f"LAN transport cannot connect profile kind {profile.kind!r}."
                )
            profile = profile.to_lan_profile()
        return self.client.connect(profile)

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


class UdpTransportAdapter(_ClientAdapter):
    kind = "udp"

    def __init__(self, client: UdpClient | None = None) -> None:
        super().__init__(client or UdpClient())

    def list_endpoints(self) -> list[EndpointInfo]:
        return []

    def connect(self, profile: TransportProfile | UdpProfile) -> bool:
        if isinstance(profile, TransportProfile):
            if profile.kind != self.kind:
                raise ValueError(
                    f"UDP transport cannot connect profile kind {profile.kind!r}."
                )
            profile = profile.to_udp_profile()
        return self.client.connect(profile)

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


_ADAPTERS = {
    "serial": SerialTransportAdapter,
    "lan": LanTransportAdapter,
    "udp": UdpTransportAdapter,
}


def create_transport_adapter(kind: str) -> TransportAdapter:
    # Unknown kinds fall back to serial so a settings file written by a newer
    # build still opens rather than crashing on load.
    return _ADAPTERS.get(kind, SerialTransportAdapter)()
