"""Resolve a serial profile from CLI flags / env / settings.json / defaults.

Precedence, highest first (per the CLI spec):

1. CLI flags
2. ``COMPORTZONE_*`` environment variables
3. ``--config <path>`` (a custom settings.json location)
4. ``%LOCALAPPDATA%\\ComPortZone\\settings.json`` defaults
5. Hard-coded fallbacks (9600 8N1, no flow control)

The resolver returns a fully-populated :class:`SerialProfile` ready to hand
to :class:`SerialClient`. The CLI's ``None`` for an unspecified flag is
preserved upstream - the helpers here never accept defaults disguised as
``None``.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.models import AppSettings, LanProfile, SerialProfile
from ..core.settings_service import SettingsService
from ..core.storage import SettingsStore


# ----------------------------------------------------- flag-value normalisation

_FLOW_CONTROL_MAP = {
    "none": "None",
    "xonxoff": "XON/XOFF",
    "rtscts": "RTS/CTS",
    "dsrdtr": "DSR/DTR",
}

_LINE_ENDING_MAP = {
    "none": "None",
    "cr": "CR",
    "lf": "LF",
    "crlf": "CRLF",
}


def _normalize_flow_control(value: str | None) -> str | None:
    if value is None:
        return None
    return _FLOW_CONTROL_MAP[value.lower()]


def _normalize_line_ending(value: str | None) -> str | None:
    if value is None:
        return None
    return _LINE_ENDING_MAP[value.lower()]


def _normalize_parity(value: str | None) -> str | None:
    if value is None:
        return None
    return value.upper()


def _normalize_onoff(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "on"


# --------------------------------------------------------------------- env vars

_ENV_PREFIX = "COMPORTZONE_"


def _env(name: str) -> str | None:
    raw = os.environ.get(f"{_ENV_PREFIX}{name}")
    if raw is None or raw == "":
        return None
    return raw


def _env_int(name: str) -> int | None:
    raw = _env(name)
    return int(raw) if raw is not None else None


def _env_float(name: str) -> float | None:
    raw = _env(name)
    return float(raw) if raw is not None else None


def _env_bool(name: str) -> bool | None:
    raw = _env(name)
    if raw is None:
        return None
    return raw.lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------- settings loading

def load_app_settings(config_path: Path | None) -> AppSettings:
    """Load ``AppSettings`` from the configured settings.json (or its
    ``.bak`` fallback). A missing file yields a fresh ``AppSettings()`` so
    the CLI keeps working before the GUI has ever run.
    """
    store = SettingsStore(config_path) if config_path else SettingsStore()
    return SettingsService(store).load()


def save_app_settings(config_path: Path | None, settings: AppSettings) -> bool:
    """Persist ``settings`` to the configured settings.json.

    Uses the same store as :func:`load_app_settings`, so the Stage 1
    advisory lock + atomic temp-rename applies — concurrent CLI / GUI
    writes won't tear the file.
    """
    store = SettingsStore(config_path) if config_path else SettingsStore()
    return SettingsService(store).save(settings)


# --------------------------------------------------------------- main resolver

def resolve_serial_profile(
    *,
    settings: AppSettings,
    port: str | None = None,
    baud: int | None = None,
    data_bits: str | None = None,
    parity: str | None = None,
    stop_bits: str | None = None,
    flow_control: str | None = None,
    line_ending: str | None = None,
    dtr: str | None = None,
    rts: str | None = None,
    auto_reconnect: bool | None = None,
) -> SerialProfile:
    """Resolve a :class:`SerialProfile` from inputs in precedence order.

    Each parameter is the raw CLI flag value (or ``None`` if not passed).
    Settings-derived defaults come from ``settings.serial``. Env vars fill
    the gap between flags and settings.
    """

    base = settings.serial if settings.serial else SerialProfile()

    resolved_port = (
        port
        if port is not None
        else _env("PORT") or base.port
    )

    resolved_baud = (
        baud
        if baud is not None
        else _env_int("BAUD") or base.baudrate
    )

    resolved_bytesize = int(data_bits) if data_bits is not None else (
        _env_int("DATA_BITS") or base.bytesize
    )

    resolved_parity = _normalize_parity(parity) or _normalize_parity(_env("PARITY")) or base.parity

    resolved_stopbits = (
        float(stop_bits)
        if stop_bits is not None
        else _env_float("STOP_BITS") or base.stopbits
    )

    resolved_flow = (
        _normalize_flow_control(flow_control)
        or _normalize_flow_control(_env("FLOW_CONTROL"))
        or base.flow_control
    )

    resolved_line_ending = (
        _normalize_line_ending(line_ending)
        or _normalize_line_ending(_env("LINE_ENDING"))
        or base.line_ending
    )

    resolved_dtr = _normalize_onoff(dtr)
    if resolved_dtr is None:
        resolved_dtr = _env_bool("DTR")
    if resolved_dtr is None:
        resolved_dtr = base.dtr

    resolved_rts = _normalize_onoff(rts)
    if resolved_rts is None:
        resolved_rts = _env_bool("RTS")
    if resolved_rts is None:
        resolved_rts = base.rts

    resolved_auto_reconnect = (
        auto_reconnect
        if auto_reconnect is not None
        else (_env_bool("AUTO_RECONNECT") if _env("AUTO_RECONNECT") is not None else base.auto_reconnect)
    )

    return replace(
        base,
        port=resolved_port,
        baudrate=resolved_baud,
        bytesize=resolved_bytesize,
        parity=resolved_parity,
        stopbits=resolved_stopbits,
        flow_control=resolved_flow,
        line_ending=resolved_line_ending,
        dtr=resolved_dtr,
        rts=resolved_rts,
        auto_reconnect=resolved_auto_reconnect,
    )


def resolve_lan_profile(
    *,
    settings: AppSettings,
    host: str | None = None,
    tcp_port: int | None = None,
    tcp_timeout_ms: int | None = None,
    line_ending: str | None = None,
    auto_reconnect: bool | None = None,
) -> LanProfile:
    """Resolve a raw TCP/LAN profile from flags, env, settings, defaults.

    Mirrors :func:`resolve_serial_profile`'s precedence for the LAN-relevant
    fields (``host`` / ``port`` / ``timeout_ms`` / ``line_ending`` /
    ``auto_reconnect``). Env vars: ``COMPORTZONE_HOST`` / ``COMPORTZONE_TCP_PORT``
    / ``COMPORTZONE_TCP_TIMEOUT_MS``.
    """
    base = settings.lan if settings.lan else LanProfile()
    resolved_auto_reconnect = (
        auto_reconnect
        if auto_reconnect is not None
        else (
            _env_bool("AUTO_RECONNECT")
            if _env("AUTO_RECONNECT") is not None
            else base.auto_reconnect
        )
    )
    return replace(
        base,
        host=(host if host is not None else _env("HOST") or base.host).strip(),
        port=(
            tcp_port
            if tcp_port is not None
            else _env_int("TCP_PORT") or base.port
        ),
        timeout_ms=(
            tcp_timeout_ms
            if tcp_timeout_ms is not None
            else _env_int("TCP_TIMEOUT_MS") or base.timeout_ms
        ),
        line_ending=(
            _normalize_line_ending(line_ending)
            or _normalize_line_ending(_env("LINE_ENDING"))
            or base.line_ending
        ),
        auto_reconnect=resolved_auto_reconnect,
    )
