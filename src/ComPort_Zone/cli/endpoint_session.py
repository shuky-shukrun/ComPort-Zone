"""Resolve and open serial or raw-TCP endpoints for CLI commands.

A CLI command that connects (``send`` / ``hex`` / ``listen`` / ``run`` /
``repl`` / ``quick send`` / ``files run``) decorates itself with
:func:`..options.endpoint_flags`, resolves a :class:`CliEndpoint` with
:func:`require_cli_endpoint`, builds a transport for ``endpoint.kind``, and
opens it with :func:`open_cli_endpoint`. ``--port`` stays serial; ``--host``
(or any TCP flag) selects raw TCP — mixing the two is a usage error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import click

from ..core.models import AppSettings, LanProfile, SerialProfile
from ..core.transports import TransportAdapter
from .config_resolver import resolve_lan_profile, resolve_serial_profile
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
    """Raised when one command mixes serial and raw-TCP endpoint flags."""


class EndpointOpenError(Exception):
    """Endpoint-open failure carrying a stable CLI exit code."""

    def __init__(self, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(slots=True)
class CliEndpoint:
    kind: str
    profile: SerialProfile | LanProfile

    @property
    def target(self) -> str:
        if isinstance(self.profile, LanProfile):
            return f"TCP {self.profile.endpoint() or '<unconfigured>'}"
        return self.profile.port or "<unconfigured serial port>"

    @property
    def connection_summary(self) -> str:
        if isinstance(self.profile, LanProfile):
            return self.target
        profile = self.profile
        return (
            f"{profile.port} @ {profile.baudrate} "
            f"{profile.bytesize}{profile.parity}{profile.stopbits:g}"
        )

    def rx_fields(self) -> dict[str, Any]:
        """Transport-identifying fields merged into JSON rx/status records."""
        if isinstance(self.profile, LanProfile):
            return {
                "transport": "tcp",
                "host": self.profile.host,
                "port": self.profile.port,
                "endpoint": self.profile.endpoint(),
            }
        return {"transport": "serial", "port": self.profile.port}


def endpoint_from_profile(profile: SerialProfile | LanProfile) -> CliEndpoint:
    if isinstance(profile, LanProfile):
        return CliEndpoint(kind="lan", profile=profile)
    return CliEndpoint(kind="serial", profile=profile)


def resolve_cli_endpoint(
    settings: AppSettings,
    endpoint_flag_values: dict[str, Any],
) -> CliEndpoint:
    """Choose serial or raw TCP without overloading ``--port`` semantics."""
    serial_overrides = [
        name for name in _SERIAL_ONLY_FLAGS if endpoint_flag_values.get(name) is not None
    ]
    tcp_overrides = [
        name for name in _TCP_ONLY_FLAGS if endpoint_flag_values.get(name) is not None
    ]
    if serial_overrides and tcp_overrides:
        raise EndpointOptionError(
            "Serial flags and TCP flags cannot be combined. "
            "Use --port COMx for serial, or --host with --tcp-port for raw TCP."
        )

    if tcp_overrides:
        kind = "lan"
    elif serial_overrides:
        kind = "serial"
    else:
        kind = "lan" if settings.transport_kind == "lan" else "serial"

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


def open_cli_endpoint(
    transport: TransportAdapter,
    endpoint: CliEndpoint,
    *,
    wait_seconds: float = 0.0,
) -> None:
    """Open ``endpoint``, normalizing serial/TCP failures to ``EndpointOpenError``.

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

    profile = endpoint.profile
    if not profile.host:
        raise EndpointOpenError(
            "No TCP host specified. Use --host or configure a LAN endpoint.",
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
