"""Resolve and open serial, raw-TCP, or UDP endpoints for CLI commands.

A CLI command that connects (``send`` / ``hex`` / ``listen`` / ``run`` /
``repl`` / ``quick send`` / ``files run``) decorates itself with
:func:`..options.endpoint_flags`, resolves a :class:`CliEndpoint` with
:func:`require_cli_endpoint`, builds a transport for ``endpoint.kind``, and
opens it with :func:`open_cli_endpoint`. ``--port`` stays serial; ``--host``
(or any TCP flag) selects raw TCP; ``--udp-host`` (or any UDP flag) selects
UDP — mixing flags from two transports is a usage error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import click

from ..core.models import AppSettings, LanProfile, SerialProfile, UdpProfile
from ..core.transport_kinds import is_transport_kind, transport_kind_info
from ..core.transports import TransportAdapter
from .config_resolver import (
    resolve_lan_profile,
    resolve_serial_profile,
    resolve_udp_profile,
)
from .exit_codes import ExitCode
from .serial_session import SerialSessionError, open_serial


_SERIAL_ONLY_FLAGS = (
    "port",
    "baud",
    "data_bits",
    "parity",
    "stop_bits",
    "flow_control",
    "dtr",
    "rts",
)
_TCP_ONLY_FLAGS = ("host", "tcp_port", "tcp_timeout_ms")
_UDP_ONLY_FLAGS = ("udp_host", "udp_port", "udp_timeout_ms")

# Transport-selecting flag groups, keyed by the kind each one implies.
# ``line_ending``, ``auto_reconnect`` and ``wait_seconds`` are deliberately in
# none of them: they are shared and must not pick a transport.
_KIND_FLAG_GROUPS = (
    ("serial", _SERIAL_ONLY_FLAGS),
    ("lan", _TCP_ONLY_FLAGS),
    ("udp", _UDP_ONLY_FLAGS),
)

# The default read window when a command opens a window with no explicit
# deadline. Serial/TCP stream continuously, so a short tick is enough; UDP
# gets its profile's reply-wait window instead (see
# :attr:`CliEndpoint.default_read_window_ms`).
STREAM_READ_WINDOW_MS = 50

# Flags forwarded to resolve_serial_profile when the endpoint is serial.
_SERIAL_RESOLVE_KEYS = (
    "port",
    "baud",
    "data_bits",
    "parity",
    "stop_bits",
    "flow_control",
    "line_ending",
    "dtr",
    "rts",
    "auto_reconnect",
)


class EndpointOptionError(ValueError):
    """Raised when one command mixes endpoint flags from two transports."""


class EndpointOpenError(Exception):
    """Endpoint-open failure carrying a stable CLI exit code."""

    def __init__(self, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(slots=True)
class CliEndpoint:
    kind: str
    profile: SerialProfile | LanProfile | UdpProfile

    @property
    def _is_network(self) -> bool:
        return isinstance(self.profile, (LanProfile, UdpProfile))

    @property
    def target(self) -> str:
        if self._is_network:
            label = transport_kind_info(self.kind).short_label
            return f"{label} {self.profile.endpoint() or '<unconfigured>'}"
        return self.profile.port or "<unconfigured serial port>"

    @property
    def connection_summary(self) -> str:
        if self._is_network:
            return self.target
        profile = self.profile
        return (
            f"{profile.port} @ {profile.baudrate} "
            f"{profile.bytesize}{profile.parity}{profile.stopbits:g}"
        )

    @property
    def default_read_window_ms(self) -> int:
        """How long to hold a read window open when the command has no
        explicit deadline. A datagram device answers once, in its own time, so
        UDP uses the profile's reply-wait window; byte streams keep the short
        tick they have always used."""
        if isinstance(self.profile, UdpProfile):
            return max(int(self.profile.timeout_ms), 1)
        return STREAM_READ_WINDOW_MS

    def rx_fields(self) -> dict[str, Any]:
        """Transport-identifying fields merged into JSON rx/status records."""
        if self._is_network:
            return {
                "transport": transport_kind_info(self.kind).rx_transport,
                "host": self.profile.host,
                "port": self.profile.port,
                "endpoint": self.profile.endpoint(),
            }
        return {"transport": "serial", "port": self.profile.port}


def endpoint_from_profile(profile: SerialProfile | LanProfile | UdpProfile) -> CliEndpoint:
    if isinstance(profile, LanProfile):
        return CliEndpoint(kind="lan", profile=profile)
    if isinstance(profile, UdpProfile):
        return CliEndpoint(kind="udp", profile=profile)
    return CliEndpoint(kind="serial", profile=profile)


def resolve_cli_endpoint(
    settings: AppSettings,
    endpoint_flag_values: dict[str, Any],
) -> CliEndpoint:
    """Choose serial, raw TCP, or UDP without overloading ``--port`` semantics."""
    chosen = [
        name
        for name, flags in _KIND_FLAG_GROUPS
        if any(endpoint_flag_values.get(flag) is not None for flag in flags)
    ]
    if len(chosen) > 1:
        raise EndpointOptionError(
            "Serial, TCP, and UDP flags cannot be combined. "
            "Use --port COMx for serial, --host with --tcp-port for raw TCP, "
            "or --udp-host with --udp-port for UDP."
        )

    if chosen:
        kind = chosen[0]
    elif is_transport_kind(settings.transport_kind):
        kind = settings.transport_kind
    else:
        kind = "serial"

    if kind == "lan":
        profile = resolve_lan_profile(
            settings=settings,
            host=endpoint_flag_values.get("host"),
            tcp_port=endpoint_flag_values.get("tcp_port"),
            tcp_timeout_ms=endpoint_flag_values.get("tcp_timeout_ms"),
            line_ending=endpoint_flag_values.get("line_ending"),
            auto_reconnect=endpoint_flag_values.get("auto_reconnect"),
        )
        return CliEndpoint(kind=kind, profile=profile)

    if kind == "udp":
        # --auto-reconnect is accepted and ignored: a UDP socket has no
        # connection to lose, so there is nothing to reconnect.
        profile = resolve_udp_profile(
            settings=settings,
            udp_host=endpoint_flag_values.get("udp_host"),
            udp_port=endpoint_flag_values.get("udp_port"),
            udp_timeout_ms=endpoint_flag_values.get("udp_timeout_ms"),
            line_ending=endpoint_flag_values.get("line_ending"),
        )
        return CliEndpoint(kind=kind, profile=profile)

    profile = resolve_serial_profile(
        settings=settings,
        **{key: endpoint_flag_values.get(key) for key in _SERIAL_RESOLVE_KEYS},
    )
    return CliEndpoint(kind=kind, profile=profile)


def require_cli_endpoint(
    ctx: click.Context,
    settings: AppSettings,
    endpoint_flag_values: dict[str, Any],
) -> CliEndpoint:
    """Resolve an endpoint or exit through the CLI output/exit-code contract."""
    try:
        return resolve_cli_endpoint(settings, endpoint_flag_values)
    except EndpointOptionError as exc:
        ctx.obj["output"].error(str(exc), code=ExitCode.USAGE_ERROR)
        ctx.exit(int(ExitCode.USAGE_ERROR))
        raise AssertionError("ctx.exit should stop endpoint resolution") from exc


def _connect_tcp_with_wait(
    transport: TransportAdapter,
    profile: LanProfile,
    wait_seconds: float,
) -> bool:
    """Connect to a TCP endpoint, retrying with exponential backoff for up to
    ``wait_seconds`` (mirrors :func:`serial_session.open_serial`'s ``--wait``)."""
    if transport.connect(profile):
        return True
    deadline = time.monotonic() + max(0.0, wait_seconds)
    delay = 0.1
    while time.monotonic() < deadline:
        time.sleep(min(delay, max(0.0, deadline - time.monotonic())))
        delay = min(delay * 2.0, 2.0)
        if transport.connect(profile):
            return True
    return False


def _open_udp(transport: TransportAdapter, profile: UdpProfile) -> None:
    """Open a UDP endpoint.

    No ``--wait`` backoff: creating a datagram socket performs no network I/O,
    so it fails only for deterministic reasons (blank/bad endpoint,
    unresolvable host) and retrying could not change the outcome. ``--wait`` is
    therefore accepted and ignored for UDP.
    """
    if not profile.host:
        raise EndpointOpenError(
            "No UDP host specified. Use --udp-host or configure a UDP endpoint.",
            ExitCode.GENERIC_ERROR,
        )
    if not 1 <= int(profile.port) <= 65535:
        raise EndpointOpenError(
            f"UDP port {profile.port!r} must be between 1 and 65535.",
            ExitCode.USAGE_ERROR,
        )
    if not transport.connect(profile):
        transport.disconnect()
        raise EndpointOpenError(
            f"Could not open UDP endpoint {profile.endpoint()}.",
            ExitCode.GENERIC_ERROR,
        )


def open_cli_endpoint(
    transport: TransportAdapter,
    endpoint: CliEndpoint,
    *,
    wait_seconds: float = 0.0,
) -> None:
    """Open ``endpoint``, normalizing failures to ``EndpointOpenError``.

    On any failure the transport is disconnected before raising, so a failed
    connect can never leave a background auto-reconnect thread running after a
    one-shot CLI command exits.
    """
    if isinstance(endpoint.profile, SerialProfile):
        try:
            open_serial(transport, endpoint.profile, wait_seconds=wait_seconds)
        except SerialSessionError as exc:
            transport.disconnect()
            raise EndpointOpenError(str(exc), exc.exit_code) from exc
        return

    if isinstance(endpoint.profile, UdpProfile):
        _open_udp(transport, endpoint.profile)
        return

    profile = endpoint.profile
    if not profile.host:
        raise EndpointOpenError(
            "No TCP host specified. Use --host or configure a TCP endpoint.",
            ExitCode.GENERIC_ERROR,
        )
    if not 1 <= int(profile.port) <= 65535:
        raise EndpointOpenError(
            f"TCP port {profile.port!r} must be between 1 and 65535.",
            ExitCode.USAGE_ERROR,
        )
    if not _connect_tcp_with_wait(transport, profile, wait_seconds):
        transport.disconnect()
        waited = f" after waiting {wait_seconds:.1f}s" if wait_seconds > 0 else ""
        raise EndpointOpenError(
            f"Could not connect to TCP endpoint {profile.endpoint()}{waited}.",
            ExitCode.GENERIC_ERROR,
        )
