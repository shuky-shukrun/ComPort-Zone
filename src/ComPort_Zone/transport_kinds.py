"""One table of everything a transport kind is *called*.

The kind discriminator itself is a bare string — ``"serial"``, ``"lan"``,
``"udp"`` — because it is persisted in settings.json and there is no migration
path (see ``settings_service.settings_from_payload``, which gates but never
upgrades). What used to be scattered were the ~15 ``"LAN" if kind == "lan" else
"COM port"`` label ternaries in the UI and the lone ``"transport": "tcp"``
literal in the CLI's JSON records; those all read from here now, so adding a
transport is one row rather than a grep.

Deliberately imports nothing from ``models``/``transports``/Qt: presentation
data only, importable from anywhere including the headless CLI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TransportKindInfo:
    kind: str
    """Persisted discriminator: ``"serial"`` | ``"lan"`` | ``"udp"``."""

    ui_label: str
    """Name shown in the connection-type combo and endpoint hints."""

    short_label: str
    """Compact type name for run-target lists ("COM3 · TCP")."""

    status_prefix: str
    """Prefix before the endpoint in status text; empty for serial, which
    shows the bare port name."""

    no_endpoint_label: str
    """Placeholder tab title / state label when nothing is configured."""

    no_endpoint_selected: str
    """Longer form of the above, for the status bar."""

    set_endpoint_action: str
    """Connect-button text when there is nothing to connect to yet."""

    choose_hint: str
    """Tooltip telling the user what to configure."""

    rx_transport: str
    """Value of the ``transport`` field in CLI JSON records. This is the only
    sanctioned place the internal ``"lan"`` becomes the user-facing ``"tcp"``."""

    datagram: bool
    """True when one read yields one whole message rather than a byte stream."""


SERIAL = TransportKindInfo(
    kind="serial",
    ui_label="Serial",
    short_label="Serial",
    status_prefix="",
    no_endpoint_label="No port",
    no_endpoint_selected="No port selected",
    set_endpoint_action="Set Port",
    choose_hint="Choose a COM port and connect.",
    rx_transport="serial",
    datagram=False,
)

LAN = TransportKindInfo(
    kind="lan",
    ui_label="LAN",
    short_label="TCP",
    status_prefix="LAN",
    no_endpoint_label="No endpoint",
    no_endpoint_selected="No endpoint selected",
    set_endpoint_action="Set Endpoint",
    choose_hint="Choose a LAN host and port.",
    rx_transport="tcp",
    datagram=False,
)

UDP = TransportKindInfo(
    kind="udp",
    ui_label="UDP",
    short_label="UDP",
    status_prefix="UDP",
    no_endpoint_label="No endpoint",
    no_endpoint_selected="No endpoint selected",
    set_endpoint_action="Set Endpoint",
    choose_hint="Choose a UDP host and port.",
    rx_transport="udp",
    datagram=True,
)

TRANSPORT_KINDS: dict[str, TransportKindInfo] = {
    SERIAL.kind: SERIAL,
    LAN.kind: LAN,
    UDP.kind: UDP,
}

#: Order the connection-type combo is built in.
TRANSPORT_KIND_ORDER: tuple[str, ...] = (SERIAL.kind, LAN.kind, UDP.kind)


def transport_kind_info(kind: str) -> TransportKindInfo:
    """Describe ``kind``, falling back to serial for anything unrecognised —
    matching ``create_transport_adapter``'s behaviour on stale settings."""
    return TRANSPORT_KINDS.get(kind, SERIAL)


def is_transport_kind(kind: str) -> bool:
    return kind in TRANSPORT_KINDS


__all__ = [
    "LAN",
    "SERIAL",
    "TRANSPORT_KINDS",
    "TRANSPORT_KIND_ORDER",
    "UDP",
    "TransportKindInfo",
    "is_transport_kind",
    "transport_kind_info",
]
