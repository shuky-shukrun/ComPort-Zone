"""Qt-free domain models for the Dashboard View feature.

A dashboard (``DashboardConfig``) is a named collection of polled entries
(``DashboardEntry``). Each entry describes one command that is sent
periodically over a bound terminal session, how its response is parsed
(``ParseRule``), how the parsed value maps to a semantic tile state
(``ColorRule``), and where its tile sits on the dashboard grid
(``TilePlacement``).

This module must stay importable without Qt and without the transport
stack: ``models.py`` imports it (settings own the dashboard library), and
the transport modules import ``models.py`` — so importing ``batch`` or
``serial_core`` from here would create a cycle. The few helpers shared
with those modules (hex validation, UTC timestamps) are intentionally
re-implemented locally.

Requirements: docs/dashboard-view-requirements.md (FR-18, FR-19, FR-29,
FR-30, FR-33, FR-35, FR-37).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

TILE_KINDS = ("value", "led")
# Semantic states a tile can render. "ok"/"warn"/"fail" come from color
# rules, "neutral" is the no-rule-matched default, "stale" means no recent
# successful poll, "error" covers send/parse failures.
TILE_STATES = ("ok", "warn", "fail", "neutral", "stale", "error")
RULE_STATES = ("ok", "warn", "fail")
COLOR_RULE_OPS = (
    "lt",
    "le",
    "gt",
    "ge",
    "eq_num",
    "ne_num",
    "between",
    "eq_text",
    "contains",
    "matches",
)
NUMERIC_RULE_OPS = ("lt", "le", "gt", "ge", "eq_num", "ne_num", "between")
PARSE_RULE_KINDS = ("line", "regex")
PARSE_VALUE_TYPES = ("text", "number")
DASHBOARD_SEND_MODES = ("Text", "Hex Bytes")
# "" = use the bound session's configured line ending.
LINE_ENDING_OVERRIDE_OPTIONS = ("", "None", "CR", "LF", "CRLF")

MIN_POLL_INTERVAL_MS = 100
MAX_POLL_INTERVAL_MS = 3_600_000
MIN_POLL_TIMEOUT_MS = 50
MAX_POLL_TIMEOUT_MS = 30_000
DEFAULT_POLL_INTERVAL_MS = 1000
DEFAULT_POLL_TIMEOUT_MS = 500

GRID_COLUMNS_MIN = 2
GRID_COLUMNS_MAX = 6
DEFAULT_GRID_COLUMNS = 4
MAX_TILE_SPAN = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _choice(value: Any, options: tuple[str, ...], default: str) -> str:
    text = str(value) if value is not None else default
    return text if text in options else default


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def hex_payload_error(text: str) -> str:
    """Validate a hex-bytes payload, returning "" when valid.

    Mirrors the accepted syntax of ``batch.parse_hex_payload`` ("AB CD",
    "0xAB,0xCD", "AB-CD"); duplicated here because this module must not
    import the transport stack (see module docstring).
    """
    normalized = text.replace(",", " ").replace("-", " ")
    parts = [part.removeprefix("0x").removeprefix("0X") for part in normalized.split()]
    compact = "".join(parts)
    if not compact:
        return "Provide at least one byte."
    if len(compact) % 2 != 0:
        return "HEX byte count must be even."
    try:
        bytes.fromhex(compact)
    except ValueError:
        return "HEX payload contains invalid characters."
    return ""


@dataclass(slots=True)
class ParseRule:
    """How an entry extracts a value from the post-send RX window.

    ``kind`` is "line" (first complete line after the send) or "regex"
    (search ``pattern`` over the window and take capture ``group``).
    ``group`` may be an index (0 = whole match) or a group name.
    ``value_type`` "number" converts the captured text to float.
    """

    kind: str = "line"
    pattern: str = ""
    group: int | str = 1
    value_type: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "pattern": self.pattern,
            "group": self.group,
            "value_type": self.value_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ParseRule":
        if not data:
            return cls()
        group_raw = data.get("group", 1)
        group: int | str
        if isinstance(group_raw, str) and not group_raw.lstrip("-").isdigit():
            group = group_raw
        else:
            try:
                group = int(group_raw)
            except (TypeError, ValueError):
                group = 1
        return cls(
            kind=_choice(data.get("kind"), PARSE_RULE_KINDS, "line"),
            pattern=str(data.get("pattern", "")),
            group=group,
            value_type=_choice(data.get("value_type"), PARSE_VALUE_TYPES, "text"),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if self.kind != "regex":
            return errors
        if not self.pattern:
            errors.append("Regex parse rule requires a pattern.")
            return errors
        try:
            compiled = re.compile(self.pattern)
        except re.error as exc:
            errors.append(f"Invalid regex pattern: {exc}")
            return errors
        if isinstance(self.group, str):
            if self.group not in compiled.groupindex:
                errors.append(f"Regex has no capture group named '{self.group}'.")
        elif self.group < 0 or self.group > compiled.groups:
            errors.append(
                f"Capture group {self.group} is out of range (pattern has {compiled.groups})."
            )
        return errors


@dataclass(slots=True)
class ColorRule:
    """One ordered rule mapping a parsed value to a semantic tile state.

    Numeric operators compare against ``operand`` (and ``operand2`` for
    inclusive "between"); textual operators compare the value text.
    ``label`` optionally overrides the displayed state text (e.g. "FAULT").
    """

    op: str = "eq_text"
    operand: str = ""
    operand2: str = ""
    state: str = "ok"
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "operand": self.operand,
            "operand2": self.operand2,
            "state": self.state,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ColorRule":
        if not data:
            return cls()
        return cls(
            op=_choice(data.get("op"), COLOR_RULE_OPS, "eq_text"),
            operand=str(data.get("operand", "")),
            operand2=str(data.get("operand2", "")),
            state=_choice(data.get("state"), RULE_STATES, "ok"),
            label=str(data.get("label", "")),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if self.op in NUMERIC_RULE_OPS:
            if not _is_number(self.operand):
                errors.append(f"Rule operand '{self.operand}' must be a number for '{self.op}'.")
            if self.op == "between" and not _is_number(self.operand2):
                errors.append(
                    f"Rule upper bound '{self.operand2}' must be a number for 'between'."
                )
        elif self.op == "matches":
            try:
                re.compile(self.operand)
            except re.error as exc:
                errors.append(f"Invalid rule regex '{self.operand}': {exc}")
        return errors


def _is_number(text: str) -> bool:
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


@dataclass(slots=True)
class TilePlacement:
    """Grid position and footprint of an entry's tile."""

    col: int = 0
    row: int = 0
    span_w: int = 1
    span_h: int = 1
    kind: str = "value"

    def to_dict(self) -> dict[str, Any]:
        return {
            "col": self.col,
            "row": self.row,
            "span_w": self.span_w,
            "span_h": self.span_h,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TilePlacement":
        if not data:
            return cls()
        return cls(
            col=_clamp_int(data.get("col", 0), 0, GRID_COLUMNS_MAX - 1, 0),
            row=max(0, _clamp_int(data.get("row", 0), 0, 10_000, 0)),
            span_w=_clamp_int(data.get("span_w", 1), 1, MAX_TILE_SPAN, 1),
            span_h=_clamp_int(data.get("span_h", 1), 1, MAX_TILE_SPAN, 1),
            kind=_choice(data.get("kind"), TILE_KINDS, "value"),
        )


@dataclass(slots=True)
class DashboardEntry:
    """One polled command and everything about how it is shown."""

    id: str = field(default_factory=lambda: uuid4().hex)
    label: str = ""
    unit: str = ""
    command: str = ""
    send_mode: str = "Text"
    line_ending_override: str = ""
    interval_ms: int = DEFAULT_POLL_INTERVAL_MS
    timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS
    stale_after_ms: int = 0
    parse: ParseRule = field(default_factory=ParseRule)
    tile: TilePlacement = field(default_factory=TilePlacement)
    rules: list[ColorRule] = field(default_factory=list)
    enabled: bool = True
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def display_label(self) -> str:
        return self.label or self.command

    def effective_stale_after_ms(self) -> int:
        """Staleness threshold; 0 means automatic (FR-32)."""
        if self.stale_after_ms > 0:
            return self.stale_after_ms
        return max(3 * self.interval_ms, self.interval_ms + self.timeout_ms + 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "unit": self.unit,
            "command": self.command,
            "send_mode": self.send_mode,
            "line_ending_override": self.line_ending_override,
            "interval_ms": self.interval_ms,
            "timeout_ms": self.timeout_ms,
            "stale_after_ms": self.stale_after_ms,
            "parse": self.parse.to_dict(),
            "tile": self.tile.to_dict(),
            "rules": [rule.to_dict() for rule in self.rules],
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DashboardEntry":
        if not data:
            return cls()
        line_ending = str(data.get("line_ending_override", ""))
        if line_ending not in LINE_ENDING_OVERRIDE_OPTIONS:
            line_ending = ""
        return cls(
            id=str(data.get("id") or uuid4().hex),
            label=str(data.get("label", "")).strip(),
            unit=str(data.get("unit", "")).strip(),
            command=str(data.get("command", "")),
            send_mode=_choice(data.get("send_mode"), DASHBOARD_SEND_MODES, "Text"),
            line_ending_override=line_ending,
            interval_ms=_clamp_int(
                data.get("interval_ms", DEFAULT_POLL_INTERVAL_MS),
                MIN_POLL_INTERVAL_MS,
                MAX_POLL_INTERVAL_MS,
                DEFAULT_POLL_INTERVAL_MS,
            ),
            timeout_ms=_clamp_int(
                data.get("timeout_ms", DEFAULT_POLL_TIMEOUT_MS),
                MIN_POLL_TIMEOUT_MS,
                MAX_POLL_TIMEOUT_MS,
                DEFAULT_POLL_TIMEOUT_MS,
            ),
            stale_after_ms=_clamp_int(data.get("stale_after_ms", 0), 0, MAX_POLL_INTERVAL_MS * 4, 0),
            parse=ParseRule.from_dict(_dict_value(data.get("parse"))),
            tile=TilePlacement.from_dict(_dict_value(data.get("tile"))),
            rules=[ColorRule.from_dict(_dict_value(item)) for item in _list_value(data.get("rules"))],
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
        )

    def validation_errors(self) -> list[str]:
        """Human-readable problems that should block saving this entry."""
        errors: list[str] = []
        if not self.command.strip():
            errors.append("Command must not be empty.")
        elif self.send_mode == "Hex Bytes":
            hex_error = hex_payload_error(self.command)
            if hex_error:
                errors.append(hex_error)
        if self.interval_ms < MIN_POLL_INTERVAL_MS:
            errors.append(f"Poll interval must be at least {MIN_POLL_INTERVAL_MS} ms.")
        if not MIN_POLL_TIMEOUT_MS <= self.timeout_ms <= MAX_POLL_TIMEOUT_MS:
            errors.append(
                f"Timeout must be between {MIN_POLL_TIMEOUT_MS} and {MAX_POLL_TIMEOUT_MS} ms."
            )
        errors.extend(self.parse.validation_errors())
        for index, rule in enumerate(self.rules, start=1):
            errors.extend(f"Rule {index}: {error}" for error in rule.validation_errors())
        return errors


@dataclass(slots=True)
class DashboardConfig:
    """A named dashboard: grid settings plus its entries."""

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "Dashboard"
    description: str = ""
    columns: int = DEFAULT_GRID_COLUMNS
    entries: list[DashboardEntry] = field(default_factory=list)
    favorite: bool = False
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def entry_by_id(self, entry_id: str) -> DashboardEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        # Entries serialize in visual order so saved/exported files diff
        # deterministically (FR-35).
        ordered = sorted(self.entries, key=lambda entry: (entry.tile.row, entry.tile.col, entry.id))
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "columns": self.columns,
            "entries": [entry.to_dict() for entry in ordered],
            "favorite": self.favorite,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DashboardConfig":
        if not data:
            return cls()
        config = cls(
            id=str(data.get("id") or uuid4().hex),
            name=str(data.get("name", "Dashboard")).strip() or "Dashboard",
            description=str(data.get("description", "")),
            columns=_clamp_int(
                data.get("columns", DEFAULT_GRID_COLUMNS),
                GRID_COLUMNS_MIN,
                GRID_COLUMNS_MAX,
                DEFAULT_GRID_COLUMNS,
            ),
            entries=[
                DashboardEntry.from_dict(_dict_value(item))
                for item in _list_value(data.get("entries"))
            ],
            favorite=bool(data.get("favorite", False)),
            created_at=str(data.get("created_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
        )
        normalize_layout(config.entries, config.columns)
        return config

    def touch(self) -> None:
        self.updated_at = _utc_now_iso()


@dataclass(slots=True)
class DashboardTabState:
    """Persisted runtime state of one open dashboard tab (FR-37)."""

    dashboard_id: str = ""
    target_endpoint: str = ""
    target_title: str = ""
    polling_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "dashboard_id": self.dashboard_id,
            "target_endpoint": self.target_endpoint,
            "target_title": self.target_title,
            "polling_enabled": self.polling_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DashboardTabState":
        if not data:
            return cls()
        return cls(
            dashboard_id=str(data.get("dashboard_id", "")),
            target_endpoint=str(data.get("target_endpoint", "")),
            target_title=str(data.get("target_title", "")),
            polling_enabled=bool(data.get("polling_enabled", True)),
        )


def _clamp_placement(tile: TilePlacement, columns: int) -> None:
    tile.span_w = max(1, min(MAX_TILE_SPAN, tile.span_w, columns))
    tile.span_h = max(1, min(MAX_TILE_SPAN, tile.span_h))
    tile.col = max(0, min(tile.col, columns - tile.span_w))
    tile.row = max(0, tile.row)


def _cells(tile: TilePlacement) -> list[tuple[int, int]]:
    return [
        (tile.col + dx, tile.row + dy)
        for dx in range(tile.span_w)
        for dy in range(tile.span_h)
    ]


def _normalize(entries: list[DashboardEntry], columns: int, priority_id: str | None) -> None:
    columns = max(GRID_COLUMNS_MIN, min(GRID_COLUMNS_MAX, columns))
    ordered = sorted(entries, key=lambda entry: (entry.tile.row, entry.tile.col, entry.id))
    if priority_id is not None:
        prioritized = [entry for entry in ordered if entry.id == priority_id]
        ordered = prioritized + [entry for entry in ordered if entry.id != priority_id]
    occupied: set[tuple[int, int]] = set()
    for entry in ordered:
        tile = entry.tile
        _clamp_placement(tile, columns)
        while any(cell in occupied for cell in _cells(tile)):
            tile.row += 1
        occupied.update(_cells(tile))


def normalize_layout(entries: list[DashboardEntry], columns: int) -> None:
    """Clamp placements to the grid and deterministically resolve overlaps.

    Tiles are processed in (row, col, id) order; a tile whose cells are
    taken is pushed down one row at a time until it fits. Same input
    always produces the same layout (FR-35). Mutates ``entries`` in place.
    """
    _normalize(entries, columns, priority_id=None)


def place_tile(entries: list[DashboardEntry], columns: int, entry_id: str, col: int, row: int) -> bool:
    """Move an entry's tile to (col, row), pushing displaced tiles down.

    The moved tile wins the target cells; everything else re-normalizes
    around it. Returns False when ``entry_id`` is unknown.
    """
    target: DashboardEntry | None = None
    for entry in entries:
        if entry.id == entry_id:
            target = entry
            break
    if target is None:
        return False
    target.tile.col = col
    target.tile.row = row
    _normalize(entries, columns, priority_id=entry_id)
    return True


def set_tile_span(
    entries: list[DashboardEntry], columns: int, entry_id: str, span_w: int, span_h: int
) -> bool:
    """Resize an entry's tile footprint, pushing displaced tiles down.

    Returns False when ``entry_id`` is unknown.
    """
    target: DashboardEntry | None = None
    for entry in entries:
        if entry.id == entry_id:
            target = entry
            break
    if target is None:
        return False
    target.tile.span_w = span_w
    target.tile.span_h = span_h
    _normalize(entries, columns, priority_id=entry_id)
    return True


def grid_row_count(entries: list[DashboardEntry]) -> int:
    """Number of grid rows needed to show every tile."""
    if not entries:
        return 0
    return max(entry.tile.row + entry.tile.span_h for entry in entries)


def example_dashboard() -> DashboardConfig:
    """The SCPI starter dashboard seeded on first run (favorited so it
    shows up on the Favorites page immediately)."""
    return DashboardConfig(
        name="Example Dashboard",
        description=(
            "Shipped example: instrument identity and firmware polled every "
            "minute, output state polled continuously as an ON/OFF lamp. "
            "Bind it to a connected terminal tab to start polling."
        ),
        favorite=True,
        columns=4,
        entries=[
            DashboardEntry(
                label="Identity",
                command="*IDN?",
                interval_ms=60_000,
                timeout_ms=1000,
                parse=ParseRule(kind="line", value_type="text"),
                tile=TilePlacement(col=0, row=0, span_w=2, span_h=1, kind="value"),
            ),
            DashboardEntry(
                label="Output",
                command="OUTP?",
                interval_ms=300,
                timeout_ms=250,
                parse=ParseRule(kind="line", value_type="number"),
                rules=[
                    ColorRule(op="eq_num", operand="1", state="ok", label="ON"),
                    ColorRule(op="eq_num", operand="0", state="warn", label="OFF"),
                ],
                tile=TilePlacement(col=2, row=0, span_w=1, span_h=1, kind="led"),
            ),
            DashboardEntry(
                label="Firmware",
                command="SYST:FIRM?",
                interval_ms=60_000,
                timeout_ms=1000,
                parse=ParseRule(kind="line", value_type="text"),
                tile=TilePlacement(col=0, row=1, span_w=2, span_h=1, kind="value"),
            ),
        ],
    )


def default_dashboards() -> list[DashboardConfig]:
    """Dashboard library seeded on first run (and for settings files from
    before the dashboard feature)."""
    return [example_dashboard()]
