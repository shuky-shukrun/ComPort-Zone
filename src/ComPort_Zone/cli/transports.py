"""Test seam for transport construction.

CLI commands obtain their :class:`SerialTransportAdapter` via the factory
declared here so unit tests can inject a fake transport without monkey-
patching pyserial. Production code uses the real adapter unchanged.
"""

from __future__ import annotations

from ..core.transports import LanTransportAdapter, SerialTransportAdapter


def make_serial_transport() -> SerialTransportAdapter:
    return SerialTransportAdapter()


def make_lan_transport() -> LanTransportAdapter:
    return LanTransportAdapter()
