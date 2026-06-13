"""Qt-free domain models for the ControlPanel View feature.

A control_panel (``ControlPanelConfig``) is a named collection of polled entries
(``ControlPanelEntry``). Each entry describes one command that is sent
periodically over a bound terminal session, how its response is parsed
(``ParseRule``), how the parsed value maps to a semantic tile state
(``ColorRule``), and where its tile sits on the control_panel grid
(``TilePlacement``).

This module must stay importable without Qt and without the transport
stack: ``models.py`` imports it (settings own the control_panel library), and
the transport modules import ``models.py`` — so importing ``batch`` or
``serial_core`` from here would create a cycle. The few helpers shared
with those modules (hex validation, UTC timestamps) are intentionally
re-implemented locally.

Requirements: docs/control_panel-view-requirements.md (FR-18, FR-19, FR-29,
FR-30, FR-33, FR-35, FR-37).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

TILE_KINDS = ("value", "led", "control", "setpoint", "enum", "bits")
# Semantic states a tile can render. "ok"/"warn"/"fail" come from color
# rules, "neutral" is the no-rule-matched default, "stale" means no recent
# successful poll, "error" covers send/parse failures.
TILE_STATES = ("ok", "warn", "fail", "neutral", "stale", "error")
# How an entry gets its value onto the wire/screen (v2):
POLL_MODES = ("interval", "on_connect")
ENTRY_SOURCES = ("poll", "derived")
CONTROL_MODES = ("button", "toggle")
MAX_EXPRESSION_LENGTH = 256
# Setpoint hard limits — chosen so the slider's int range never overflows
# (max steps = (max - min) / step) and the editor dialog stays usable. v3.
SETPOINT_MIN_DECIMALS = 0
SETPOINT_MAX_DECIMALS = 6
SETPOINT_MIN_STEP = 1e-6
SETPOINT_VALUE_PLACEHOLDER = "{value}"
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
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
CONTROL_PANEL_SEND_MODES = ("Text", "Hex Bytes")
# "" = use the bound session's configured line ending.
LINE_ENDING_OVERRIDE_OPTIONS = ("", "None", "CR", "LF", "CRLF")

MIN_POLL_INTERVAL_MS = 100
MAX_POLL_INTERVAL_MS = 3_600_000
MIN_POLL_TIMEOUT_MS = 50
MAX_POLL_TIMEOUT_MS = 30_000
DEFAULT_POLL_INTERVAL_MS = 1000
DEFAULT_POLL_TIMEOUT_MS = 500

GRID_COLUMNS_MIN = 1
GRID_COLUMNS_MAX = 12
DEFAULT_GRID_COLUMNS = 4
GRID_ROWS_MIN = 1
GRID_ROWS_MAX = 24
DEFAULT_GRID_ROWS = 5
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
    ``color`` (v2) optionally overrides the theme state color (``#rrggbb``)
    everywhere this rule's verdict renders (FR-62).
    """

    op: str = "eq_text"
    operand: str = ""
    operand2: str = ""
    state: str = "ok"
    label: str = ""
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "op": self.op,
            "operand": self.operand,
            "operand2": self.operand2,
            "state": self.state,
            "label": self.label,
        }
        # v2 fields serialize sparsely (FR-18): a v1-shaped rule keeps its
        # exact v1 payload, which keeps v1 builds importing it and the
        # schema-floor predicate honest.
        if self.color:
            payload["color"] = self.color
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ColorRule":
        if not data:
            return cls()
        color = str(data.get("color", ""))
        if not _HEX_COLOR.match(color):
            color = ""
        return cls(
            op=_choice(data.get("op"), COLOR_RULE_OPS, "eq_text"),
            operand=str(data.get("operand", "")),
            operand2=str(data.get("operand2", "")),
            state=_choice(data.get("state"), RULE_STATES, "ok"),
            label=str(data.get("label", "")),
            color=color,
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
class ControlSpec:
    """Configuration of a control tile (v2, FR-59).

    ``button`` sends ``on_command`` per click; ``toggle`` alternates between
    ``on_command``/``off_command``, with the visual state following
    ``watch_entry_id``'s verdict ("ok" renders ON) when set.
    """

    mode: str = "button"
    on_command: str = ""
    off_command: str = ""
    confirm: bool = False
    watch_entry_id: str = ""

    def is_default(self) -> bool:
        return self == ControlSpec()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.mode != "button":
            payload["mode"] = self.mode
        if self.on_command:
            payload["on_command"] = self.on_command
        if self.off_command:
            payload["off_command"] = self.off_command
        if self.confirm:
            payload["confirm"] = True
        if self.watch_entry_id:
            payload["watch_entry_id"] = self.watch_entry_id
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ControlSpec":
        if not data:
            return cls()
        return cls(
            mode=_choice(data.get("mode"), CONTROL_MODES, "button"),
            on_command=str(data.get("on_command", "")),
            off_command=str(data.get("off_command", "")),
            confirm=bool(data.get("confirm", False)),
            watch_entry_id=str(data.get("watch_entry_id", "")),
        )

    def validation_errors(self, send_mode: str) -> list[str]:
        errors: list[str] = []
        if not self.on_command.strip():
            noun = "Command" if self.mode == "button" else "ON command"
            errors.append(f"{noun} must not be empty.")
        if self.mode == "toggle" and not self.off_command.strip():
            errors.append("OFF command must not be empty for a toggle.")
        if send_mode == "Hex Bytes":
            for name, command in (("Command", self.on_command), ("OFF command", self.off_command)):
                if command.strip():
                    hex_error = hex_payload_error(command)
                    if hex_error:
                        errors.append(f"{name}: {hex_error}")
        return errors


def format_setpoint_value(value: float, decimals: int) -> str:
    """Render a setpoint value the way the wire command will see it.

    ``f"{x:.{decimals}f}"`` over ``:g`` because operators expect a fixed
    number of decimals from a numeric setpoint (entering 12 with
    decimals=2 sends "12.00"). Trims any trailing decimal-only zero
    when decimals=0 so the integer form stays clean.
    """
    if decimals <= 0:
        return f"{round(value):d}"
    return f"{value:.{decimals}f}"


@dataclass(slots=True)
class SetpointSpec:
    """Configuration of a numeric setpoint tile (v3, FR-63..FR-67).

    The tile shows a slider + spinbox bound to a float value in
    ``[min_value, max_value]`` with ``step`` granularity, and sends a
    single command derived from ``command_template`` (one ``{value}``
    placeholder, formatted with ``decimals`` precision). Optional
    ``watch_entry_id`` mirrors a polled tile's latest value as a
    readback line under the input.
    """

    min_value: float = 0.0
    max_value: float = 100.0
    step: float = 1.0
    decimals: int = 2
    unit: str = ""
    command_template: str = ""
    watch_entry_id: str = ""
    confirm: bool = False

    def is_default(self) -> bool:
        return self == SetpointSpec()

    def clamp(self, value: float) -> float:
        """Snap ``value`` into [min, max] for the dialog's typed-value path."""
        return max(self.min_value, min(self.max_value, float(value)))

    def render_command(self, value: float) -> str:
        """Build the command string sent for ``value`` (no-op when no template)."""
        return self.command_template.replace(
            SETPOINT_VALUE_PLACEHOLDER, format_setpoint_value(value, self.decimals)
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.min_value != 0.0:
            payload["min_value"] = self.min_value
        if self.max_value != 100.0:
            payload["max_value"] = self.max_value
        if self.step != 1.0:
            payload["step"] = self.step
        if self.decimals != 2:
            payload["decimals"] = self.decimals
        if self.unit:
            payload["unit"] = self.unit
        if self.command_template:
            payload["command_template"] = self.command_template
        if self.watch_entry_id:
            payload["watch_entry_id"] = self.watch_entry_id
        if self.confirm:
            payload["confirm"] = True
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SetpointSpec":
        if not data:
            return cls()
        decimals = _clamp_int(
            data.get("decimals", 2),
            SETPOINT_MIN_DECIMALS,
            SETPOINT_MAX_DECIMALS,
            2,
        )
        return cls(
            min_value=float(data.get("min_value", 0.0)),
            max_value=float(data.get("max_value", 100.0)),
            step=float(data.get("step", 1.0)),
            decimals=decimals,
            unit=str(data.get("unit", "")),
            command_template=str(data.get("command_template", "")),
            watch_entry_id=str(data.get("watch_entry_id", "")),
            confirm=bool(data.get("confirm", False)),
        )

    def validation_errors(self, send_mode: str) -> list[str]:
        """Edit-time errors that block dialog OK. Reference validity (the
        watched entry must exist and be a polled tile) lives at the dialog
        level — same pattern as the derived-tile expression check."""
        errors: list[str] = []
        if not self.command_template.strip():
            errors.append("Command template must not be empty.")
        elif self.command_template.count(SETPOINT_VALUE_PLACEHOLDER) != 1:
            errors.append(
                f"Command template must contain {SETPOINT_VALUE_PLACEHOLDER} exactly once."
            )
        if self.min_value >= self.max_value:
            errors.append("Minimum must be less than maximum.")
        if self.step <= SETPOINT_MIN_STEP:
            errors.append("Step must be a positive number.")
        elif self.max_value > self.min_value and self.step > (self.max_value - self.min_value):
            errors.append("Step must be smaller than the value range.")
        if send_mode == "Hex Bytes" and self.command_template.strip():
            # Render with a sample value so a templated hex command can
            # actually be checked end-to-end at edit time.
            sample = self.render_command(self.clamp(self.min_value + self.step))
            hex_error = hex_payload_error(sample)
            if hex_error:
                errors.append(f"Setpoint command: {hex_error}")
        return errors


@dataclass(slots=True)
class EnumOption:
    """One option in an enum/dropdown tile (v3, FR-68..FR-71)."""

    label: str = ""
    command: str = ""
    match_value: str = ""

    def is_default(self) -> bool:
        return self == EnumOption()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.label:
            payload["label"] = self.label
        if self.command:
            payload["command"] = self.command
        if self.match_value:
            payload["match_value"] = self.match_value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EnumOption":
        if not data:
            return cls()
        return cls(
            label=str(data.get("label", "")),
            command=str(data.get("command", "")),
            match_value=str(data.get("match_value", "")),
        )


@dataclass(slots=True)
class EnumSpec:
    """Configuration of an enum/dropdown selector tile (v3)."""

    options: list[EnumOption] = field(default_factory=list)
    watch_entry_id: str = ""
    confirm: bool = False

    def is_default(self) -> bool:
        return not self.options and not self.watch_entry_id and not self.confirm

    def indicated_index(self, value_text: str) -> int:
        """Index of the first option whose match_value matches ``value_text``
        (trimmed, case-insensitive); -1 when nothing matches or no watch."""
        if not value_text:
            return -1
        needle = value_text.strip().casefold()
        for index, option in enumerate(self.options):
            if option.match_value and option.match_value.strip().casefold() == needle:
                return index
        return -1

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.options:
            payload["options"] = [option.to_dict() for option in self.options]
        if self.watch_entry_id:
            payload["watch_entry_id"] = self.watch_entry_id
        if self.confirm:
            payload["confirm"] = True
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EnumSpec":
        if not data:
            return cls()
        return cls(
            options=[
                EnumOption.from_dict(_dict_value(item))
                for item in _list_value(data.get("options"))
            ],
            watch_entry_id=str(data.get("watch_entry_id", "")),
            confirm=bool(data.get("confirm", False)),
        )

    def validation_errors(self, send_mode: str) -> list[str]:
        errors: list[str] = []
        if not self.options:
            errors.append("Enum tile needs at least one option.")
            return errors
        for index, option in enumerate(self.options, start=1):
            if not option.label.strip():
                errors.append(f"Option {index}: label must not be empty.")
            if not option.command.strip():
                errors.append(f"Option {index}: command must not be empty.")
            elif send_mode == "Hex Bytes":
                hex_error = hex_payload_error(option.command)
                if hex_error:
                    errors.append(f"Option {index}: {hex_error}")
        return errors


# Status / fault register tiles. Measurement instruments commonly expose
# fault and status flags as bits in an integer register (SCPI's
# *STB?/STAT:OPER:COND?/STAT:QUES:COND?). Bit definitions describe which
# bits get a labeled indicator on the tile; the active set is computed
# at render time from the latest polled integer value (multiple bits can
# be active simultaneously).
BIT_POSITION_MIN = 0
BIT_POSITION_MAX = 31
BITS_STATES = ("ok", "warn", "fail", "neutral")


@dataclass(slots=True)
class BitDefinition:
    """One labeled indicator on a register/bits tile."""

    bit: int = 0
    label: str = ""
    state: str = "warn"
    description: str = ""

    def is_default(self) -> bool:
        return self == BitDefinition()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        # Always emit the bit position so a value of 0 round-trips
        # explicitly (the default-value gate would otherwise drop it).
        payload["bit"] = self.bit
        if self.label:
            payload["label"] = self.label
        if self.state and self.state != "warn":
            payload["state"] = self.state
        if self.description:
            payload["description"] = self.description
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BitDefinition":
        if not data:
            return cls()
        return cls(
            bit=_clamp_int(
                data.get("bit", 0), BIT_POSITION_MIN, BIT_POSITION_MAX, 0
            ),
            label=str(data.get("label", "")),
            state=_choice(data.get("state"), BITS_STATES, "warn"),
            description=str(data.get("description", "")),
        )


@dataclass(slots=True)
class BitsSpec:
    """Configuration of a bits/register status tile (v3).

    Each :class:`BitDefinition` becomes a small labeled indicator on the
    tile. Any number of bits can be active at once. The tile is read-only
    (not writable) and is fed by the same numeric parse pipeline as a
    value tile: the parsed number is coerced to int and tested for each
    defined bit position.
    """

    bits: list[BitDefinition] = field(default_factory=list)

    def is_default(self) -> bool:
        return not self.bits

    def active_bits(self, value: int) -> list[BitDefinition]:
        """Subset of defined bits that are set in ``value``. Preserves
        the configured order so the tile renders deterministically."""
        return [b for b in self.bits if (int(value) >> b.bit) & 1]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.bits:
            payload["bits"] = [bit.to_dict() for bit in self.bits]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BitsSpec":
        if not data:
            return cls()
        return cls(
            bits=[
                BitDefinition.from_dict(_dict_value(item))
                for item in _list_value(data.get("bits"))
            ],
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.bits:
            errors.append("Bits tile needs at least one bit definition.")
            return errors
        seen: set[int] = set()
        for index, bit in enumerate(self.bits, start=1):
            if not bit.label.strip():
                errors.append(f"Bit {index}: label must not be empty.")
            if not BIT_POSITION_MIN <= bit.bit <= BIT_POSITION_MAX:
                errors.append(
                    f"Bit {index}: position must be in "
                    f"{BIT_POSITION_MIN}..{BIT_POSITION_MAX}."
                )
            if bit.bit in seen:
                errors.append(f"Bit position {bit.bit} is defined more than once.")
            seen.add(bit.bit)
            if bit.state not in BITS_STATES:
                errors.append(f"Bit {index}: invalid state {bit.state!r}.")
        return errors


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
class ControlPanelEntry:
    """One control_panel entry and everything about how it is shown.

    v1 entries are polled commands. v2 adds poll modes (FR-52), per-entry
    target sessions (FR-54), derived/computed entries (FR-61), and control
    tiles (FR-59) — all via additive, sparsely-serialized fields.
    """

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
    # --- v2 fields (sparse in to_dict) ---------------------------------
    poll_mode: str = "interval"
    target_endpoint: str = ""
    source: str = "poll"
    expression: str = ""
    show_sparkline: bool = True
    alerts_enabled: bool = True
    control: ControlSpec = field(default_factory=ControlSpec)
    # --- v3 fields (sparse in to_dict) ---------------------------------
    setpoint: SetpointSpec = field(default_factory=SetpointSpec)
    enum_spec: EnumSpec = field(default_factory=EnumSpec)
    bits_spec: BitsSpec = field(default_factory=BitsSpec)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def display_label(self) -> str:
        return self.label or self.command or self.expression

    def is_control(self) -> bool:
        return self.tile.kind == "control"

    def is_setpoint(self) -> bool:
        return self.tile.kind == "setpoint"

    def is_enum(self) -> bool:
        return self.tile.kind == "enum"

    def is_bits(self) -> bool:
        return self.tile.kind == "bits"

    def is_writable(self) -> bool:
        """Whether this entry sends on user action (button/toggle/setpoint/enum).

        The master arm gate fires here (v3, FR-72): any writing tile is
        refused while the panel is disarmed; non-writing tiles ignore
        arming state.
        """
        return self.is_control() or self.is_setpoint() or self.is_enum()

    def is_derived(self) -> bool:
        return self.source == "derived"

    def is_polled(self) -> bool:
        return not self.is_writable() and not self.is_derived()

    def is_numeric(self) -> bool:
        """Whether this entry produces numeric values (history/sparkline/chart)."""
        if self.is_writable() or self.is_bits():
            return False
        return self.is_derived() or self.parse.value_type == "number"

    def effective_stale_after_ms(self) -> int:
        """Staleness threshold; 0 means automatic (FR-32)."""
        if self.stale_after_ms > 0:
            return self.stale_after_ms
        return max(3 * self.interval_ms, self.interval_ms + self.timeout_ms + 1000)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        # v2 fields: written only when non-default (FR-18 sparse contract).
        if self.poll_mode != "interval":
            payload["poll_mode"] = self.poll_mode
        if self.target_endpoint:
            payload["target_endpoint"] = self.target_endpoint
        if self.source != "poll":
            payload["source"] = self.source
        if self.expression:
            payload["expression"] = self.expression
        if not self.show_sparkline:
            payload["show_sparkline"] = False
        if not self.alerts_enabled:
            payload["alerts_enabled"] = False
        control_payload = self.control.to_dict()
        if control_payload:
            payload["control"] = control_payload
        # v3 fields: written only when non-default (FR-39 v3 sparse contract).
        setpoint_payload = self.setpoint.to_dict()
        if setpoint_payload:
            payload["setpoint"] = setpoint_payload
        enum_payload = self.enum_spec.to_dict()
        if enum_payload:
            payload["enum_spec"] = enum_payload
        bits_payload = self.bits_spec.to_dict()
        if bits_payload:
            payload["bits_spec"] = bits_payload
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ControlPanelEntry":
        if not data:
            return cls()
        line_ending = str(data.get("line_ending_override", ""))
        if line_ending not in LINE_ENDING_OVERRIDE_OPTIONS:
            line_ending = ""
        expression = str(data.get("expression", ""))[:MAX_EXPRESSION_LENGTH]
        return cls(
            id=str(data.get("id") or uuid4().hex),
            label=str(data.get("label", "")).strip(),
            unit=str(data.get("unit", "")).strip(),
            command=str(data.get("command", "")),
            send_mode=_choice(data.get("send_mode"), CONTROL_PANEL_SEND_MODES, "Text"),
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
            poll_mode=_choice(data.get("poll_mode"), POLL_MODES, "interval"),
            target_endpoint=str(data.get("target_endpoint", "")).strip(),
            source=_choice(data.get("source"), ENTRY_SOURCES, "poll"),
            expression=expression,
            show_sparkline=bool(data.get("show_sparkline", True)),
            alerts_enabled=bool(data.get("alerts_enabled", True)),
            control=ControlSpec.from_dict(_dict_value(data.get("control"))),
            setpoint=SetpointSpec.from_dict(_dict_value(data.get("setpoint"))),
            enum_spec=EnumSpec.from_dict(_dict_value(data.get("enum_spec"))),
            bits_spec=BitsSpec.from_dict(_dict_value(data.get("bits_spec"))),
            created_at=str(data.get("created_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
        )

    def validation_errors(self) -> list[str]:
        """Human-readable problems that should block saving this entry.

        Branches by entry kind: writing entries (control/setpoint/enum)
        validate their spec instead of command/schedule/parse; derived
        entries validate the expression's presence and size (reference
        resolution needs sibling context and lives in ``control_panel_expr``).
        Color rules apply to non-writing entries only.
        """
        errors: list[str] = []
        if self.is_control():
            errors.extend(self.control.validation_errors(self.send_mode))
            return errors
        if self.is_setpoint():
            errors.extend(self.setpoint.validation_errors(self.send_mode))
            return errors
        if self.is_enum():
            errors.extend(self.enum_spec.validation_errors(self.send_mode))
            return errors
        if self.is_bits():
            errors.extend(self.bits_spec.validation_errors())
            # Bits tiles also need a polled command — fall through to
            # the polled-entry validation below so the command/schedule
            # checks fire too.
        if self.is_derived():
            if not self.expression.strip():
                errors.append("Expression must not be empty.")
            elif len(self.expression) > MAX_EXPRESSION_LENGTH:
                errors.append(f"Expression is longer than {MAX_EXPRESSION_LENGTH} characters.")
        else:
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
class ControlPanelConfig:
    """A named control_panel: grid settings plus its entries."""

    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "ControlPanel"
    description: str = ""
    columns: int = DEFAULT_GRID_COLUMNS
    rows: int = DEFAULT_GRID_ROWS
    entries: list[ControlPanelEntry] = field(default_factory=list)
    favorite: bool = False
    # v2: CSV value logging persists with the control_panel so unattended
    # capture survives restarts (FR-49). Sparse in to_dict.
    csv_log_enabled: bool = False
    csv_log_path: str = ""
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def entry_by_id(self, entry_id: str) -> ControlPanelEntry | None:
        for entry in self.entries:
            if entry.id == entry_id:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        # Entries serialize in visual order so saved/exported files diff
        # deterministically (FR-35).
        ordered = sorted(self.entries, key=lambda entry: (entry.tile.row, entry.tile.col, entry.id))
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "columns": self.columns,
            "rows": self.rows,
            "entries": [entry.to_dict() for entry in ordered],
            "favorite": self.favorite,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.csv_log_enabled:
            payload["csv_log_enabled"] = True
        if self.csv_log_path:
            payload["csv_log_path"] = self.csv_log_path
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ControlPanelConfig":
        if not data:
            return cls()
        config = cls(
            id=str(data.get("id") or uuid4().hex),
            name=str(data.get("name", "ControlPanel")).strip() or "ControlPanel",
            description=str(data.get("description", "")),
            columns=_clamp_int(
                data.get("columns", DEFAULT_GRID_COLUMNS),
                GRID_COLUMNS_MIN,
                GRID_COLUMNS_MAX,
                DEFAULT_GRID_COLUMNS,
            ),
            rows=_clamp_int(
                data.get("rows", DEFAULT_GRID_ROWS),
                GRID_ROWS_MIN,
                GRID_ROWS_MAX,
                DEFAULT_GRID_ROWS,
            ),
            entries=[
                ControlPanelEntry.from_dict(_dict_value(item))
                for item in _list_value(data.get("entries"))
            ],
            favorite=bool(data.get("favorite", False)),
            csv_log_enabled=bool(data.get("csv_log_enabled", False)),
            csv_log_path=str(data.get("csv_log_path", "")),
            created_at=str(data.get("created_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
        )
        normalize_layout(config.entries, config.columns)
        return config

    def touch(self) -> None:
        self.updated_at = _utc_now_iso()


@dataclass(slots=True)
class ControlPanelTabState:
    """Persisted runtime state of one open control_panel tab (FR-37)."""

    control_panel_id: str = ""
    target_endpoint: str = ""
    target_title: str = ""
    polling_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_panel_id": self.control_panel_id,
            "target_endpoint": self.target_endpoint,
            "target_title": self.target_title,
            "polling_enabled": self.polling_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ControlPanelTabState":
        if not data:
            return cls()
        return cls(
            control_panel_id=str(data.get("control_panel_id", "")),
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


def _normalize(entries: list[ControlPanelEntry], columns: int, priority_id: str | None) -> None:
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


def normalize_layout(entries: list[ControlPanelEntry], columns: int) -> None:
    """Clamp placements to the grid and deterministically resolve overlaps.

    Tiles are processed in (row, col, id) order; a tile whose cells are
    taken is pushed down one row at a time until it fits. Same input
    always produces the same layout (FR-35). Mutates ``entries`` in place.
    """
    _normalize(entries, columns, priority_id=None)


def place_tile(entries: list[ControlPanelEntry], columns: int, entry_id: str, col: int, row: int) -> bool:
    """Move an entry's tile to (col, row), pushing displaced tiles down.

    The moved tile wins the target cells; everything else re-normalizes
    around it. Returns False when ``entry_id`` is unknown.
    """
    target: ControlPanelEntry | None = None
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
    entries: list[ControlPanelEntry], columns: int, entry_id: str, span_w: int, span_h: int
) -> bool:
    """Resize an entry's tile footprint, pushing displaced tiles down.

    Returns False when ``entry_id`` is unknown.
    """
    target: ControlPanelEntry | None = None
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


def grid_row_count(entries: list[ControlPanelEntry]) -> int:
    """Number of grid rows needed to show every tile."""
    if not entries:
        return 0
    return max(entry.tile.row + entry.tile.span_h for entry in entries)


def visible_row_count(config: "ControlPanelConfig") -> int:
    """Rows the grid should reserve room for: at least ``config.rows`` (the
    user-configured minimum) but expands automatically when tiles overflow."""
    return max(int(config.rows), grid_row_count(config.entries))


def entry_uses_v2_features(entry: ControlPanelEntry) -> bool:
    """Whether this entry uses any persisted v2 capability.

    Shared by the settings schema floor and the export-payload version
    stamp (FR-39): a v1-shaped entry must answer False so untouched
    libraries stay readable by v1 builds. Deliberately excludes
    ``show_sparkline``/``alerts_enabled`` — losing them on a downgrade
    round-trip is cosmetic only.
    """
    return (
        entry.poll_mode != "interval"
        or bool(entry.target_endpoint)
        or entry.source == "derived"
        or entry.tile.kind == "control"
        or any(rule.color for rule in entry.rules)
    )


def control_panel_uses_v2_features(config: ControlPanelConfig) -> bool:
    return (
        config.csv_log_enabled
        or bool(config.csv_log_path)
        or any(entry_uses_v2_features(entry) for entry in config.entries)
    )


def entry_uses_v3_features(entry: ControlPanelEntry) -> bool:
    """Whether this entry uses any persisted v3 capability (FR-39 v3).

    A v3 panel pushes the schema floor to v7 only when at least one of
    its entries carries a v3 feature. Setpoint/enum kinds are detected
    via the tile kind so a misconfigured entry (kind set without spec
    payload) still gates correctly; a non-default spec also counts so a
    leftover SetpointSpec without the matching kind never silently
    downgrades.
    """
    return (
        entry.tile.kind == "setpoint"
        or entry.tile.kind == "enum"
        or entry.tile.kind == "bits"
        or not entry.setpoint.is_default()
        or not entry.enum_spec.is_default()
        or not entry.bits_spec.is_default()
    )


def control_panel_uses_v3_features(config: ControlPanelConfig) -> bool:
    return any(entry_uses_v3_features(entry) for entry in config.entries)


def example_control_panel() -> ControlPanelConfig:
    """The SCPI starter control panel seeded on first run (favorited so it
    shows up on the Favorites page immediately)."""
    output_entry_id = "example-output"
    mode_entry_id = "example-mode"
    return ControlPanelConfig(
        name="Example Control Panel",
        description=(
            "Shipped example: instrument identity and firmware fetched once "
            "on every connect, output state polled continuously as an ON/OFF "
            "lamp, plus a setpoint slider for output voltage and an enum for "
            "regulation mode. Bind it to a connected terminal tab and click "
            "Arm in the header to enable controls."
        ),
        favorite=True,
        columns=4,
        entries=[
            ControlPanelEntry(
                label="Identity",
                command="*IDN?",
                poll_mode="on_connect",
                timeout_ms=1000,
                parse=ParseRule(kind="line", value_type="text"),
                tile=TilePlacement(col=0, row=0, span_w=2, span_h=1, kind="value"),
            ),
            ControlPanelEntry(
                id=output_entry_id,
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
            ControlPanelEntry(
                id=mode_entry_id,
                label="Mode",
                command="SOUR:FUNC:MODE?",
                interval_ms=500,
                timeout_ms=250,
                parse=ParseRule(kind="line", value_type="text"),
                tile=TilePlacement(col=3, row=0, span_w=1, span_h=1, kind="value"),
            ),
            ControlPanelEntry(
                label="Firmware",
                command="SYST:FIRM?",
                poll_mode="on_connect",
                timeout_ms=1000,
                parse=ParseRule(kind="line", value_type="text"),
                tile=TilePlacement(col=0, row=1, span_w=2, span_h=1, kind="value"),
            ),
            ControlPanelEntry(
                label="Output voltage",
                tile=TilePlacement(col=0, row=2, span_w=2, span_h=1, kind="setpoint"),
                setpoint=SetpointSpec(
                    min_value=0.0,
                    max_value=30.0,
                    step=0.1,
                    decimals=2,
                    unit="V",
                    command_template="VOLT {value}",
                    watch_entry_id=output_entry_id,
                    confirm=False,
                ),
            ),
            ControlPanelEntry(
                label="Regulation",
                tile=TilePlacement(col=2, row=2, span_w=2, span_h=1, kind="enum"),
                enum_spec=EnumSpec(
                    options=[
                        EnumOption(label="OFF", command="OUTP OFF", match_value="OFF"),
                        EnumOption(label="CV", command="SOUR:FUNC:MODE CV", match_value="CV"),
                        EnumOption(label="CC", command="SOUR:FUNC:MODE CC", match_value="CC"),
                    ],
                    watch_entry_id=mode_entry_id,
                    confirm=False,
                ),
            ),
        ],
    )


def default_control_panels() -> list[ControlPanelConfig]:
    """ControlPanel library seeded on first run (and for settings files from
    before the control_panel feature)."""
    return [example_control_panel()]
