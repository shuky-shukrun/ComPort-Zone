"""Test seam for transport construction.

CLI commands obtain their :class:`SerialTransportAdapter` via the factory
declared here so unit tests can inject a fake transport without monkey-
patching pyserial. Production code uses the real adapter unchanged.
"""

from __future__ import annotations

from ..core.transports import (
    LanTransportAdapter,
    SerialTransportAdapter,
    UdpTransportAdapter,
)


def make_serial_transport() -> SerialTransportAdapter:
    return SerialTransportAdapter()


def make_lan_transport() -> LanTransportAdapter:
    return LanTransportAdapter()


def make_udp_transport() -> UdpTransportAdapter:
    return UdpTransportAdapter()


def make_transport(kind: str):
    """Build the adapter for a resolved endpoint kind.

    Written as an if/elif over module globals rather than a name->factory dict
    so ``patch("...cli.transports.make_lan_transport")`` still takes effect —
    a dict would capture the original function objects at import time.
    Unknown kinds fall back to serial, matching ``create_transport_adapter``.
    """
    if kind == "lan":
        return make_lan_transport()
    if kind == "udp":
        return make_udp_transport()
    return make_serial_transport()
