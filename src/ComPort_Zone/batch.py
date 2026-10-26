from __future__ import annotations

import re
from decimal import Decimal, DecimalException, InvalidOperation
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import perf_counter

from .serial_core import SerialEvent

WAIT_PATTERN = re.compile(r"^WAIT\s+(\d+)$", re.IGNORECASE)
LOOP_PATTERN = re.compile(r"^LOOP\s+(\d+|FOREVER|INFINITE)$", re.IGNORECASE)
ENDLOOP_PATTERN = re.compile(r"^ENDLOOP$", re.IGNORECASE)
CONDITION_OPERATOR_PATTERN = re.compile(
    r"NOT\s+CONTAINS|CONTAINS|==|!=|<=|>=|<|>",
    re.IGNORECASE,
)
ELSE_PATTERN = re.compile(r"^ELSE$", re.IGNORECASE)
ENDIF_PATTERN = re.compile(r"^ENDIF$", re.IGNORECASE)
CAPTURE_PATTERN = re.compile(
    r"^CAPTURE\s+([A-Za-z_][A-Za-z0-9_]*)\s+REGEX\s+(.+)$",
    re.IGNORECASE,
)
BREAK_PATTERN = re.compile(r"^BREAK$", re.IGNORECASE)
PAUSE_PATTERN = re.compile(r"^PAUSE(?:\s+(.*))?$", re.IGNORECASE)
SET_PATTERN = re.compile(
    r"^SET\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)$",
    re.IGNORECASE,
)
VARIABLE_ACTION_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*):(INCREMENT|DECREMENT)(?:\s+(.+))?$",
    re.IGNORECASE,
)
LOG_PATTERN = re.compile(r"^LOG\s+(.+)$", re.IGNORECASE)
RUNTIME_VARIABLE_PATTERN = re.compile(r"(?<!\$)\$([A-Za-z_][A-Za-z0-9_]*)")
SEND_PATTERN = re.compile(r"^SEND\s+(.+)$", re.IGNORECASE)
HEX_PATTERN = re.compile(r"^HEX\s+([0-9A-Fa-f\s]+)$", re.IGNORECASE)
EXPECT_PATTERN = re.compile(r"^EXPECT\s+(.+)$", re.IGNORECASE)
# ``@@name value`` — a persistent execution setting (see KNOWN_SETTINGS). Distinct
# from the one-time ``WAIT`` step and from ``{{param}}`` templating.
SETTING_PATTERN = re.compile(r"^@@([A-Za-z][\w-]*)\s*(.*)$")
PARAMETER_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:=([^{}]*?))?\s*\}\}")
HIGH_RES_WAIT_THRESHOLD_SECONDS = 0.020
COARSE_WAIT_CHUNK_SECONDS = 0.050
DEFAULT_EXPECT_TIMEOUT_MS = 1000

# TX origin tag for batch sends (SerialEvent.source) — distinguishes
# command-file traffic from manual terminal input in the transcript/log.
BATCH_TX_SOURCE = "batch"
# Source tag carried by control-panel poll traffic; EXPECT skips it so a
# resumed panel's polls can't satisfy/pollute a running command file. Kept as a
# literal (not imported from control_panel_engine) to avoid a circular import.
CONTROL_PANEL_RX_SOURCE = "control_panel"


class BatchParseError(ValueError):
    def __init__(self, message: str, line_number: int) -> None:
        super().__init__(f"Line {line_number}: {message}")
        self.line_number = line_number


# ----- @@settings: persistent execution directives -------------------------
# A settings line (``@@name value``) mutates the run's RunSettings from that point
# forward (persist-until-overridden). The registry below is the single source of
# truth so parsing, execution, highlighting, completion, and validation all agree,
# and adding a setting is one entry + one RunSettings field.

SEND_MODES = ("text", "hex")


@dataclass(slots=True)
class RunSettings:
    """Mutable per-run state driven by ``@@`` directives. Seeded from each engine's
    defaults, then updated in document order as ``setting`` steps execute."""

    wait_before_ms: int = 0
    expect_timeout_ms: int = DEFAULT_EXPECT_TIMEOUT_MS
    stop_on_error: bool = True
    send_mode: str = "text"

    def apply(self, name: str, value: object) -> None:
        KNOWN_SETTINGS[name].apply(self, value)


@dataclass(frozen=True, slots=True)
class SettingSpec:
    name: str
    value_hint: str  # e.g. "<ms>" — shown in completion, docs, and parse errors
    parse: Callable[[str], object]  # raw text -> typed value; raises ValueError if bad
    apply: Callable[[RunSettings, object], None]
    help: str


def _parse_non_negative_ms(text: str) -> int:
    if not text:
        raise ValueError("a whole number of milliseconds is required.")
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a whole number of milliseconds.") from None
    if value < 0:
        raise ValueError("milliseconds cannot be negative.")
    return value


def _parse_positive_ms(text: str) -> int:
    value = _parse_non_negative_ms(text)
    if value < 1:
        raise ValueError("milliseconds must be at least 1.")
    return value


def _parse_choice(text: str, choices: tuple[str, ...]) -> str:
    value = text.strip().lower()
    if value not in choices:
        raise ValueError(f"expected one of {', '.join(choices)}.")
    return value


KNOWN_SETTINGS: dict[str, SettingSpec] = {
    "wait": SettingSpec(
        "wait", "<ms>", _parse_non_negative_ms,
        lambda settings, value: setattr(settings, "wait_before_ms", value),
        "Delay (ms) before each following command.",
    ),
    "expect-timeout": SettingSpec(
        "expect-timeout", "<ms>", _parse_positive_ms,
        lambda settings, value: setattr(settings, "expect_timeout_ms", value),
        "Timeout (ms) for following EXPECT steps.",
    ),
    "on-error": SettingSpec(
        "on-error", "<stop|continue>",
        lambda text: _parse_choice(text, ("stop", "continue")),
        lambda settings, value: setattr(settings, "stop_on_error", value == "stop"),
        "Whether a failed step aborts the run (stop) or logs and continues.",
    ),
    "send-mode": SettingSpec(
        "send-mode", "<text|hex>",
        lambda text: _parse_choice(text, SEND_MODES),
        lambda settings, value: setattr(settings, "send_mode", value),
        "Interpret following bare/SEND lines as text or raw hex bytes.",
    ),
}

# Names in registration order — the editor imports this for completion/highlighting.
SETTING_NAMES = tuple(KNOWN_SETTINGS)


@dataclass(slots=True)
class BatchStep:
    kind: str
    # For a "setting" step the payload is a ``(name, parsed_value)`` tuple.
    # A ``None`` loop payload means an intentionally unbounded loop.
    payload: str | bytes | int | tuple[object, ...] | None
    line_number: int


@dataclass(slots=True)
class BatchTemplateStep:
    line: str
    line_number: int


@dataclass(slots=True)
class BatchParameterOccurrence:
    name: str
    default: str | None
    line_number: int
    line_text: str


@dataclass(slots=True)
class BatchParameterInputLine:
    line_number: int
    line_text: str
    parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BatchRunSnapshot:
    is_running: bool
    is_paused: bool = False
    is_stopping: bool = False
    pause_reason: str = ""
    can_resume: bool = False


BatchLineResolver = Callable[[str, int], str | None]
BatchParameterPrompt = Callable[[str, int, str], str | None]
EventQueueFactory = Callable[[], Queue[SerialEvent]]
EventQueueDisposer = Callable[[Queue[SerialEvent]], None]
BatchPauseNotifier = Callable[[str, int], None]


def parse_hex_payload(text: str) -> bytes:
    normalized = text.replace(",", " ").replace("-", " ")
    parts = [part.removeprefix("0x").removeprefix("0X") for part in normalized.split()]
    compact = "".join(parts)
    if not compact:
        raise ValueError("Provide at least one byte.")
    if len(compact) % 2 != 0:
        raise ValueError("HEX byte count must be even.")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("HEX payload contains invalid characters.") from exc


def strip_c_style_comment(line: str) -> str:
    return line.split("//", 1)[0].strip()


def _batch_command_lines(text: str) -> list[BatchTemplateStep]:
    steps: list[BatchTemplateStep] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = strip_c_style_comment(raw_line)
        if not stripped or stripped.startswith("#"):
            continue
        steps.append(BatchTemplateStep(stripped, line_number))
    return steps


def _parse_condition_step(line: str, line_number: int) -> BatchStep:
    expression = line[2:].strip()
    quote: str | None = None
    for index, character in enumerate(expression):
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            continue
        if index == 0 or not expression[index - 1].isspace():
            continue
        operator_match = CONDITION_OPERATOR_PATTERN.match(expression, index)
        if operator_match is None:
            continue
        operator_end = operator_match.end()
        if operator_end >= len(expression) or not expression[operator_end].isspace():
            continue
        left = expression[:index].strip()
        right = expression[operator_end:].strip()
        if left and right:
            operator = " ".join(operator_match.group(0).upper().split())
            return BatchStep("if", (left, operator, right), line_number)
    raise BatchParseError(
        "IF requires two values and an operator: ==, !=, <, <=, >, >=, CONTAINS, or NOT CONTAINS.",
        line_number,
    )


def parse_batch_line(line: str, line_number: int) -> BatchStep:
    stripped = line.strip()
    if not stripped:
        raise BatchParseError("Line became empty after parameter substitution.", line_number)
    setting_match = SETTING_PATTERN.match(stripped)
    if setting_match:
        name = setting_match.group(1).lower()
        raw_value = setting_match.group(2).strip()
        spec = KNOWN_SETTINGS.get(name)
        if spec is None:
            raise BatchParseError(f"Unknown setting @@{name}.", line_number)
        try:
            value = spec.parse(raw_value)
        except ValueError as exc:
            raise BatchParseError(f"@@{name} {spec.value_hint}: {exc}", line_number) from exc
        return BatchStep("setting", (name, value), line_number)
    wait_match = WAIT_PATTERN.match(stripped)
    if wait_match:
        return BatchStep("wait", int(wait_match.group(1)), line_number)
    loop_match = LOOP_PATTERN.match(stripped)
    if loop_match:
        count_text = loop_match.group(1)
        if count_text.upper() in ("FOREVER", "INFINITE"):
            return BatchStep("loop", None, line_number)
        count = int(count_text)
        if count < 1:
            raise BatchParseError("LOOP count must be at least 1, or FOREVER.", line_number)
        return BatchStep("loop", count, line_number)
    if ENDLOOP_PATTERN.match(stripped):
        return BatchStep("endloop", "", line_number)
    if re.match(r"^LOOP\b", stripped, re.IGNORECASE):
        raise BatchParseError("LOOP requires a positive whole-number count or FOREVER.", line_number)
    if re.match(r"^ENDLOOP\b", stripped, re.IGNORECASE):
        raise BatchParseError("ENDLOOP does not accept an argument.", line_number)
    if re.match(r"^IF\b", stripped, re.IGNORECASE):
        return _parse_condition_step(stripped, line_number)
    if ELSE_PATTERN.match(stripped):
        return BatchStep("else", "", line_number)
    if ENDIF_PATTERN.match(stripped):
        return BatchStep("endif", "", line_number)
    if re.match(r"^ELSE\b", stripped, re.IGNORECASE):
        raise BatchParseError("ELSE does not accept an argument.", line_number)
    if re.match(r"^ENDIF\b", stripped, re.IGNORECASE):
        raise BatchParseError("ENDIF does not accept an argument.", line_number)
    capture_match = CAPTURE_PATTERN.match(stripped)
    if capture_match:
        name, pattern = capture_match.groups()
        try:
            re.compile(pattern)
        except re.error as exc:
            raise BatchParseError(f"Invalid CAPTURE regular expression: {exc}", line_number) from exc
        return BatchStep("capture", (name, pattern), line_number)
    if re.match(r"^CAPTURE\b", stripped, re.IGNORECASE):
        raise BatchParseError("CAPTURE syntax is: CAPTURE NAME REGEX <pattern>.", line_number)
    if BREAK_PATTERN.match(stripped):
        return BatchStep("break", "", line_number)
    if re.match(r"^BREAK\b", stripped, re.IGNORECASE):
        raise BatchParseError("BREAK does not accept an argument.", line_number)
    pause_match = PAUSE_PATTERN.match(stripped)
    if pause_match:
        return BatchStep("pause", (pause_match.group(1) or "").strip(), line_number)
    set_match = SET_PATTERN.match(stripped)
    if set_match:
        name, value = set_match.groups()
        return BatchStep("set", (name, value), line_number)
    if re.match(r"^SET\b", stripped, re.IGNORECASE):
        raise BatchParseError("SET syntax is: SET NAME <value>.", line_number)
    variable_action_match = VARIABLE_ACTION_PATTERN.match(stripped)
    if variable_action_match:
        name, action, amount = variable_action_match.groups()
        amount = amount.strip() if amount is not None else "1"
        if "$" not in amount and "{{" not in amount:
            try:
                parsed_amount = Decimal(amount)
            except InvalidOperation:
                parsed_amount = None
            if parsed_amount is None or not parsed_amount.is_finite() or parsed_amount < 0:
                raise BatchParseError(
                    f"{action.upper()} amount must be a non-negative finite number or runtime variable.",
                    line_number,
                )
        return BatchStep("variable_action", (name, action.lower(), amount), line_number)
    log_match = LOG_PATTERN.match(stripped)
    if log_match:
        return BatchStep("log", log_match.group(1), line_number)
    if re.match(r"^LOG\b", stripped, re.IGNORECASE):
        raise BatchParseError("LOG requires a message.", line_number)
    expect_match = EXPECT_PATTERN.match(stripped)
    if expect_match:
        expected = expect_match.group(1).strip()
        if not expected:
            raise BatchParseError("EXPECT requires text to match.", line_number)
        return BatchStep("expect", expected, line_number)
    send_match = SEND_PATTERN.match(stripped)
    if send_match:
        return BatchStep("send", send_match.group(1), line_number)
    hex_match = HEX_PATTERN.match(stripped)
    if hex_match:
        try:
            payload = parse_hex_payload(hex_match.group(1))
        except ValueError as exc:
            raise BatchParseError(str(exc), line_number) from exc
        return BatchStep("hex", payload, line_number)
    return BatchStep("send", stripped, line_number)


def parse_batch_script(text: str) -> list[BatchStep]:
    steps = [parse_batch_line(step.line, step.line_number) for step in _batch_command_lines(text)]
    validate_control_blocks(steps)
    build_loop_jumps(steps)
    build_break_jumps(steps)
    build_condition_jumps(steps)
    return steps


def parse_batch_template(text: str) -> list[BatchTemplateStep]:
    return _batch_command_lines(text)


def _template_step_kind(step: BatchTemplateStep) -> str:
    token = step.line.split(maxsplit=1)[0].upper()
    if token == "LOOP":
        return "loop"
    if token == "ENDLOOP":
        return "endloop"
    if token == "IF":
        return "if"
    if token == "ELSE":
        return "else"
    if token == "ENDIF":
        return "endif"
    if token == "BREAK":
        return "break"
    return ""


def build_loop_jumps(
    steps: list[BatchStep] | list[BatchTemplateStep],
) -> dict[int, int]:
    """Validate LOOP nesting and map each LOOP/ENDLOOP index to its partner."""
    jumps: dict[int, int] = {}
    stack: list[tuple[int, int]] = []
    for index, step in enumerate(steps):
        kind = step.kind if isinstance(step, BatchStep) else _template_step_kind(step)
        if kind == "loop":
            stack.append((index, step.line_number))
        elif kind == "endloop":
            if not stack:
                raise BatchParseError("ENDLOOP has no matching LOOP.", step.line_number)
            start_index, _ = stack.pop()
            jumps[start_index] = index
            jumps[index] = start_index
    if stack:
        _, line_number = stack[-1]
        raise BatchParseError("LOOP has no matching ENDLOOP.", line_number)
    return jumps


def build_break_jumps(
    steps: list[BatchStep] | list[BatchTemplateStep],
) -> dict[int, tuple[int, int]]:
    """Map each BREAK index to its innermost LOOP and ENDLOOP indexes."""
    loop_jumps = build_loop_jumps(steps)
    jumps: dict[int, tuple[int, int]] = {}
    loop_stack: list[int] = []
    for index, step in enumerate(steps):
        kind = step.kind if isinstance(step, BatchStep) else _template_step_kind(step)
        if kind == "loop":
            loop_stack.append(index)
        elif kind == "endloop":
            loop_stack.pop()
        elif kind == "break":
            if not loop_stack:
                raise BatchParseError("BREAK must be inside a LOOP block.", step.line_number)
            loop_index = loop_stack[-1]
            jumps[index] = (loop_index, loop_jumps[loop_index])
    return jumps


def validate_control_blocks(steps: list[BatchStep] | list[BatchTemplateStep]) -> None:
    """Require LOOP and IF blocks to be correctly and non-crossingly nested."""
    stack: list[tuple[str, int, bool]] = []
    for step in steps:
        kind = step.kind if isinstance(step, BatchStep) else _template_step_kind(step)
        if kind in ("loop", "if"):
            stack.append((kind, step.line_number, False))
            continue
        if kind == "break":
            if not any(open_kind == "loop" for open_kind, _, _ in stack):
                raise BatchParseError("BREAK must be inside a LOOP block.", step.line_number)
            continue
        if kind == "else":
            if not stack or stack[-1][0] != "if":
                raise BatchParseError("ELSE must be inside the currently open IF block.", step.line_number)
            _, line_number, seen_else = stack[-1]
            if seen_else:
                raise BatchParseError("IF block cannot contain more than one ELSE.", step.line_number)
            stack[-1] = ("if", line_number, True)
            continue
        if kind not in ("endloop", "endif"):
            continue
        expected = "loop" if kind == "endloop" else "if"
        marker = "ENDLOOP" if kind == "endloop" else "ENDIF"
        opener = "LOOP" if expected == "loop" else "IF"
        if not stack:
            raise BatchParseError(f"{marker} has no matching {opener}.", step.line_number)
        if stack[-1][0] != expected:
            open_name = "LOOP" if stack[-1][0] == "loop" else "IF"
            raise BatchParseError(
                f"{marker} cannot close the currently open {open_name} block.",
                step.line_number,
            )
        stack.pop()
    if stack:
        kind, line_number, _ = stack[-1]
        opener = "LOOP" if kind == "loop" else "IF"
        closer = "ENDLOOP" if kind == "loop" else "ENDIF"
        raise BatchParseError(f"{opener} has no matching {closer}.", line_number)


def build_condition_jumps(
    steps: list[BatchStep] | list[BatchTemplateStep],
) -> tuple[dict[int, tuple[int | None, int]], dict[int, int]]:
    """Validate IF nesting and return IF targets plus ELSE-to-ENDIF jumps."""
    if_jumps: dict[int, tuple[int | None, int]] = {}
    else_jumps: dict[int, int] = {}
    stack: list[tuple[int, int, int | None]] = []
    for index, step in enumerate(steps):
        kind = step.kind if isinstance(step, BatchStep) else _template_step_kind(step)
        if kind == "if":
            stack.append((index, step.line_number, None))
        elif kind == "else":
            if not stack:
                raise BatchParseError("ELSE has no matching IF.", step.line_number)
            if_index, line_number, else_index = stack[-1]
            if else_index is not None:
                raise BatchParseError("IF block cannot contain more than one ELSE.", step.line_number)
            stack[-1] = (if_index, line_number, index)
        elif kind == "endif":
            if not stack:
                raise BatchParseError("ENDIF has no matching IF.", step.line_number)
            if_index, _, else_index = stack.pop()
            if_jumps[if_index] = (else_index, index)
            if else_index is not None:
                else_jumps[else_index] = index
    if stack:
        _, line_number, _ = stack[-1]
        raise BatchParseError("IF has no matching ENDIF.", line_number)
    return if_jumps, else_jumps


def _unquote_condition_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def evaluate_condition(left: str, operator: str, right: str) -> bool:
    """Evaluate a resolved IF expression without executing arbitrary code."""
    left_value = _unquote_condition_value(left)
    right_value = _unquote_condition_value(right)
    operator = " ".join(operator.upper().split())
    if operator == "CONTAINS":
        return right_value in left_value
    if operator == "NOT CONTAINS":
        return right_value not in left_value
    if operator in ("==", "!="):
        try:
            equal = Decimal(left_value) == Decimal(right_value)
        except InvalidOperation:
            equal = left_value == right_value
        return equal if operator == "==" else not equal
    try:
        left_number = Decimal(left_value)
        right_number = Decimal(right_value)
    except InvalidOperation as exc:
        raise ValueError(f"{operator} requires numeric values, got '{left_value}' and '{right_value}'.") from exc
    return {
        "<": left_number < right_number,
        "<=": left_number <= right_number,
        ">": left_number > right_number,
        ">=": left_number >= right_number,
    }[operator]


def substitute_runtime_variables(
    text: str,
    variables: dict[str, str],
    line_number: int,
) -> str:
    """Resolve ``$NAME`` values captured earlier in the current run.

    ``$$`` escapes a literal dollar sign.
    """
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            missing.append(name)
            return match.group(0)
        return variables[name]

    resolved = RUNTIME_VARIABLE_PATTERN.sub(replace, text).replace("$$", "$")
    if missing:
        names = ", ".join(dict.fromkeys(missing))
        raise BatchParseError(f"Runtime variable(s) not captured yet: {names}.", line_number)
    return resolved


def resolve_runtime_step(step: BatchStep, variables: dict[str, str]) -> BatchStep:
    """Return a step with runtime variables resolved in text-bearing fields."""
    if step.kind in ("send", "expect", "pause"):
        return BatchStep(
            step.kind,
            substitute_runtime_variables(str(step.payload), variables, step.line_number),
            step.line_number,
        )
    if step.kind == "if":
        left, operator, right = step.payload
        return BatchStep(
            "if",
            (
                substitute_runtime_variables(str(left), variables, step.line_number),
                operator,
                substitute_runtime_variables(str(right), variables, step.line_number),
            ),
            step.line_number,
        )
    if step.kind == "capture":
        name, pattern = step.payload
        resolved_pattern = substitute_runtime_variables(
            str(pattern), variables, step.line_number
        )
        try:
            re.compile(resolved_pattern)
        except re.error as exc:
            raise BatchParseError(
                f"Invalid CAPTURE regular expression after variable substitution: {exc}",
                step.line_number,
            ) from exc
        return BatchStep(
            "capture",
            (name, resolved_pattern),
            step.line_number,
        )
    if step.kind == "set":
        name, value = step.payload
        return BatchStep(
            "set",
            (name, substitute_runtime_variables(str(value), variables, step.line_number)),
            step.line_number,
        )
    if step.kind == "variable_action":
        name, action, amount = step.payload
        return BatchStep(
            "variable_action",
            (
                name,
                action,
                substitute_runtime_variables(str(amount), variables, step.line_number),
            ),
            step.line_number,
        )
    if step.kind == "log":
        return BatchStep(
            "log",
            substitute_runtime_variables(str(step.payload), variables, step.line_number),
            step.line_number,
        )
    return step


def apply_variable_action(step: BatchStep, variables: dict[str, str]) -> None:
    """Apply a parsed increment/decrement step to the per-run variable map."""
    name, action, amount_text = step.payload
    variable_name = str(name)
    if variable_name not in variables:
        raise BatchParseError(
            f"Runtime variable '{variable_name}' is not set for {str(action).upper()}.",
            step.line_number,
        )
    try:
        current = Decimal(variables[variable_name])
        amount = Decimal(str(amount_text))
        if not current.is_finite() or not amount.is_finite() or amount < 0:
            raise InvalidOperation
        result = current + amount if action == "increment" else current - amount
    except DecimalException:
        raise BatchParseError(
            f"Variable '{variable_name}' and the action amount must be finite numbers; "
            "the amount cannot be negative.",
            step.line_number,
        ) from None
    result_text = format(result, "f")
    if "." in result_text:
        result_text = result_text.rstrip("0").rstrip(".")
    variables[variable_name] = "0" if result_text in ("-0", "") else result_text


def find_batch_parameters(text: str) -> list[BatchParameterOccurrence]:
    occurrences: list[BatchParameterOccurrence] = []
    for step in _batch_command_lines(text):
        for match in PARAMETER_PATTERN.finditer(step.line):
            default = match.group(2)
            occurrences.append(
                BatchParameterOccurrence(
                    name=match.group(1),
                    default=default.strip() if default is not None else None,
                    line_number=step.line_number,
                    line_text=step.line,
                )
            )
    return occurrences


def batch_parameter_input_lines(text: str) -> list[BatchParameterInputLine]:
    values: dict[str, str] = {}
    prompt_names: set[str] = set()
    lines: list[BatchParameterInputLine] = []
    for step in _batch_command_lines(text):
        line_parameters: list[str] = []
        seen_on_line: set[str] = set()
        for match in PARAMETER_PATTERN.finditer(step.line):
            name = match.group(1)
            default = match.group(2)
            default_value = default.strip() if default is not None else None
            if name in values:
                continue
            if default_value:
                values[name] = default_value
                continue
            if name not in prompt_names and name not in seen_on_line:
                line_parameters.append(name)
                prompt_names.add(name)
                seen_on_line.add(name)
        if line_parameters:
            lines.append(BatchParameterInputLine(step.line_number, step.line, tuple(line_parameters)))
    return lines


def substitute_batch_parameters(
    line: str,
    values: dict[str, str],
    prompt: BatchParameterPrompt,
    line_number: int,
    ignored_defaults: set[str] | None = None,
) -> str | None:
    cancelled = False
    ignored_defaults = ignored_defaults or set()

    def replace(match: re.Match[str]) -> str:
        nonlocal cancelled
        name = match.group(1)
        default = match.group(2)
        default_value = default.strip() if default is not None else None
        if name in values:
            return values[name]
        if default_value and name not in ignored_defaults:
            values[name] = default_value
            return default_value
        value = prompt(name, line_number, line)
        if value is None:
            cancelled = True
            return ""
        values[name] = value
        return value

    substituted = PARAMETER_PATTERN.sub(replace, line)
    if cancelled:
        return None
    return substituted


def load_batch_file(path: str | Path) -> list[BatchStep]:
    return parse_batch_script(Path(path).read_text(encoding="utf-8"))


class BatchRunner:
    def __init__(
        self,
        *,
        emit_event: Callable[[SerialEvent], None],
        send_text,
        send_bytes,
        connected_supplier,
        event_queue_factory: EventQueueFactory | None = None,
        event_queue_disposer: EventQueueDisposer | None = None,
        pause_notifier: BatchPauseNotifier | None = None,
        expect_timeout_ms: int = DEFAULT_EXPECT_TIMEOUT_MS,
        stop_on_error: bool = True,
    ) -> None:
        self._emit_event = emit_event
        self._send_text = send_text
        self._send_bytes = send_bytes
        self._connected_supplier = connected_supplier
        self._event_queue_factory = event_queue_factory
        self._event_queue_disposer = event_queue_disposer
        self._pause_notifier = pause_notifier
        self._expect_timeout_ms = max(expect_timeout_ms, 1)
        # Defaults a script's @@settings start from (and can override per run).
        self._stop_on_error = stop_on_error
        self._rx_event_queue: Queue[SerialEvent] | None = None
        self._rx_buffer = ""
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._resume_event = Event()
        self._state_lock = Lock()
        self._user_paused = False
        self._directive_paused = False
        self._connection_paused = False
        self._stopping = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, steps: list[BatchStep]) -> None:
        validate_control_blocks(steps)
        build_loop_jumps(steps)
        build_condition_jumps(steps)
        self.stop(emit_message=False)
        self._stop_event = Event()
        self._resume_event = Event()
        with self._state_lock:
            self._user_paused = False
            self._directive_paused = False
            self._connection_paused = not self._connected_supplier()
            self._stopping = False
            self._refresh_resume_state_locked()
        self._thread = Thread(
            target=self._run_with_event_subscription,
            args=(self._run_steps, steps),
            daemon=True,
            name="batch-runner",
        )
        self._thread.start()

    def start_template(self, steps: list[BatchTemplateStep], resolve_line: BatchLineResolver) -> None:
        validate_control_blocks(steps)
        build_loop_jumps(steps)
        build_condition_jumps(steps)
        self.stop(emit_message=False)
        self._stop_event = Event()
        self._resume_event = Event()
        with self._state_lock:
            self._user_paused = False
            self._directive_paused = False
            self._connection_paused = not self._connected_supplier()
            self._stopping = False
            self._refresh_resume_state_locked()
        self._thread = Thread(
            target=self._run_with_event_subscription,
            args=(self._run_template_steps, steps, resolve_line),
            daemon=True,
            name="batch-runner",
        )
        self._thread.start()

    def stop(self, emit_message: bool = True) -> None:
        thread = self._thread
        if thread and thread.is_alive():
            with self._state_lock:
                self._stopping = True
                self._stop_event.set()
                self._resume_event.set()
            thread.join(timeout=1.5)
            if emit_message:
                self._emit("status", "Batch run stopped.")
            if thread.is_alive():
                return
        self._thread = None
        with self._state_lock:
            self._stopping = False
            self._user_paused = False
            self._directive_paused = False
            self._connection_paused = False
            self._refresh_resume_state_locked()

    def pause(self, reason: str = "user", emit_message: bool = True) -> bool:
        if not self.is_running:
            return False
        reason = "connection" if reason == "connection" else "user"
        with self._state_lock:
            was_paused = self._user_paused or self._directive_paused or self._connection_paused
            if reason == "connection":
                self._connection_paused = True
            else:
                self._user_paused = True
            self._refresh_resume_state_locked()
        if emit_message and not was_paused:
            self._emit("status", "Batch run paused.")
        return True

    def resume(self, emit_message: bool = True) -> bool:
        if not self.is_running:
            return False
        if not self._connected_supplier():
            with self._state_lock:
                self._connection_paused = True
                self._refresh_resume_state_locked()
            if emit_message:
                self._emit("status", "Connect before resuming batch run.")
            return False
        with self._state_lock:
            was_paused = self._user_paused or self._directive_paused or self._connection_paused
            self._user_paused = False
            self._directive_paused = False
            self._connection_paused = False
            self._refresh_resume_state_locked()
        if emit_message and was_paused:
            self._emit("status", "Batch run resumed.")
        return True

    def snapshot(self) -> BatchRunSnapshot:
        running = self.is_running
        with self._state_lock:
            paused = running and (
                self._user_paused or self._directive_paused or self._connection_paused
            )
            reason = self._pause_reason_locked() if paused else ""
            can_resume = paused and self._connected_supplier() and not self._stopping
            return BatchRunSnapshot(
                is_running=running,
                is_paused=paused,
                is_stopping=running and self._stopping,
                pause_reason=reason,
                can_resume=can_resume,
            )

    def notify_connection_state(self, connected: bool) -> None:
        if not self.is_running:
            return
        if connected:
            with self._state_lock:
                was_connection_paused = self._connection_paused
                self._refresh_resume_state_locked()
            if was_connection_paused:
                self._emit("status", "Connection restored. Batch run waiting for Resume.")
            return
        with self._state_lock:
            was_paused = self._user_paused or self._directive_paused or self._connection_paused
            self._connection_paused = True
            self._refresh_resume_state_locked()
        if not was_paused:
            self._emit("status", "Connection lost. Batch run paused.")

    def _refresh_resume_state_locked(self) -> None:
        if self._stop_event.is_set():
            self._resume_event.set()
            return
        if self._user_paused or self._directive_paused or self._connection_paused:
            self._resume_event.clear()
            return
        self._resume_event.set()

    def _pause_reason_locked(self) -> str:
        if self._directive_paused and self._connection_paused:
            return "script+connection"
        if self._user_paused and self._connection_paused:
            return "user+connection"
        if self._connection_paused:
            return "connection"
        if self._directive_paused:
            return "script"
        if self._user_paused:
            return "user"
        return ""

    def _run_with_event_subscription(self, target, *args) -> None:
        self._rx_buffer = ""
        if self._event_queue_factory is not None:
            self._rx_event_queue = self._event_queue_factory()
        try:
            target(*args)
        finally:
            queue = self._rx_event_queue
            self._rx_event_queue = None
            self._rx_buffer = ""
            if queue is not None and self._event_queue_disposer is not None:
                self._event_queue_disposer(queue)
            with self._state_lock:
                self._stopping = False
                self._user_paused = False
                self._directive_paused = False
                self._connection_paused = False
                self._refresh_resume_state_locked()

    def _new_run_settings(self) -> RunSettings:
        return RunSettings(
            expect_timeout_ms=self._expect_timeout_ms,
            stop_on_error=self._stop_on_error,
        )

    def _step_failed_should_abort(self, settings: RunSettings) -> bool:
        # A real stop/disconnect always aborts; a step *error* aborts only when the
        # current @@on-error setting says so.
        return self._stop_event.is_set() or settings.stop_on_error

    def _run_steps(self, steps: list[BatchStep]) -> None:
        self._emit("status", f"Batch run started with {len(steps)} step(s).")
        if not steps:
            self._emit("status", "Batch file had no runnable commands.")
            return
        settings = self._new_run_settings()
        completed = True
        loop_jumps = build_loop_jumps(steps)
        break_jumps = build_break_jumps(steps)
        condition_jumps, else_jumps = build_condition_jumps(steps)
        loop_remaining: dict[int, int | None] = {}
        runtime_variables: dict[str, str] = {}
        index = 0
        while index < len(steps):
            if not self._wait_for_connection():
                completed = False
                break
            step = steps[index]
            try:
                step = resolve_runtime_step(step, runtime_variables)
            except BatchParseError as exc:
                self._emit("error", str(exc))
                if step.kind == "if" or self._step_failed_should_abort(settings):
                    completed = False
                    break
                index += 1
                continue
            if step.kind == "loop":
                loop_remaining[index] = step.payload if isinstance(step.payload, int) else None
                index += 1
                continue
            if step.kind == "endloop":
                loop_index = loop_jumps[index]
                remaining = loop_remaining[loop_index]
                if remaining is None:
                    index = loop_index + 1
                    continue
                if remaining > 1:
                    loop_remaining[loop_index] = remaining - 1
                    index = loop_index + 1
                    continue
                del loop_remaining[loop_index]
                index += 1
                continue
            if step.kind == "break":
                loop_index, endloop_index = break_jumps[index]
                loop_remaining.pop(loop_index, None)
                index = endloop_index + 1
                continue
            if step.kind == "if":
                left, operator, right = step.payload
                try:
                    condition_met = evaluate_condition(str(left), str(operator), str(right))
                except ValueError as exc:
                    self._emit("error", f"Condition on line {step.line_number} failed: {exc}")
                    completed = False
                    break
                if condition_met:
                    index += 1
                else:
                    else_index, endif_index = condition_jumps[index]
                    index = (else_index + 1) if else_index is not None else (endif_index + 1)
                continue
            if step.kind == "else":
                index = else_jumps[index] + 1
                continue
            if step.kind == "endif":
                index += 1
                continue
            if not self._run_step(step, settings, runtime_variables) and self._step_failed_should_abort(settings):
                completed = False
                break
            index += 1
        if completed:
            self._emit("status", "Batch run completed.")

    def _run_template_steps(self, steps: list[BatchTemplateStep], resolve_line: BatchLineResolver) -> None:
        self._emit("status", f"Batch run started with {len(steps)} step(s).")
        if not steps:
            self._emit("status", "Batch file had no runnable commands.")
            return
        settings = self._new_run_settings()
        completed = True
        loop_jumps = build_loop_jumps(steps)
        break_jumps = build_break_jumps(steps)
        condition_jumps, else_jumps = build_condition_jumps(steps)
        loop_remaining: dict[int, int | None] = {}
        runtime_variables: dict[str, str] = {}
        index = 0
        while index < len(steps):
            if not self._wait_for_connection():
                completed = False
                break
            template_step = steps[index]
            try:
                resolved_line = resolve_line(template_step.line, template_step.line_number)
                if resolved_line is None:
                    self._emit("status", "Batch run cancelled.")
                    completed = False
                    break
                step = parse_batch_line(resolved_line, template_step.line_number)
            except BatchParseError as exc:
                self._emit("error", str(exc))
                completed = False
                break
            except Exception as exc:
                self._emit("error", f"Batch parameter on line {template_step.line_number} failed: {exc}")
                completed = False
                break
            try:
                step = resolve_runtime_step(step, runtime_variables)
            except BatchParseError as exc:
                self._emit("error", str(exc))
                if step.kind == "if" or self._step_failed_should_abort(settings):
                    completed = False
                    break
                index += 1
                continue
            if self._stop_event.is_set():
                completed = False
                break
            if step.kind == "loop":
                loop_remaining[index] = step.payload if isinstance(step.payload, int) else None
                index += 1
                continue
            if step.kind == "endloop":
                loop_index = loop_jumps[index]
                remaining = loop_remaining[loop_index]
                if remaining is None:
                    index = loop_index + 1
                    continue
                if remaining > 1:
                    loop_remaining[loop_index] = remaining - 1
                    index = loop_index + 1
                    continue
                del loop_remaining[loop_index]
                index += 1
                continue
            if step.kind == "break":
                loop_index, endloop_index = break_jumps[index]
                loop_remaining.pop(loop_index, None)
                index = endloop_index + 1
                continue
            if step.kind == "if":
                left, operator, right = step.payload
                try:
                    condition_met = evaluate_condition(str(left), str(operator), str(right))
                except ValueError as exc:
                    self._emit("error", f"Condition on line {step.line_number} failed: {exc}")
                    completed = False
                    break
                if condition_met:
                    index += 1
                else:
                    else_index, endif_index = condition_jumps[index]
                    index = (else_index + 1) if else_index is not None else (endif_index + 1)
                continue
            if step.kind == "else":
                index = else_jumps[index] + 1
                continue
            if step.kind == "endif":
                index += 1
                continue
            if not self._run_step(step, settings, runtime_variables) and self._step_failed_should_abort(settings):
                completed = False
                break
            index += 1
        if completed:
            self._emit("status", "Batch run completed.")

    def _run_step(
        self,
        step: BatchStep,
        settings: RunSettings,
        runtime_variables: dict[str, str],
    ) -> bool:
        if step.kind == "set":
            name, value = step.payload
            stored_value = _unquote_condition_value(str(value))
            runtime_variables[str(name)] = stored_value
            return True
        if step.kind == "pause":
            with self._state_lock:
                self._directive_paused = True
                self._refresh_resume_state_locked()
            message = str(step.payload).strip()
            detail = f": {message}" if message else ""
            self._emit(
                "status",
                f"Script paused on line {step.line_number}{detail}. "
                "Press Return, Space, or Continue in the checkpoint dialog.",
            )
            if self._pause_notifier is not None:
                self._pause_notifier(message, step.line_number)
            return self._wait_for_connection()
        if step.kind == "variable_action":
            try:
                apply_variable_action(step, runtime_variables)
            except BatchParseError as exc:
                self._emit("error", str(exc))
                return False
            return True
        if step.kind == "log":
            self._emit("script", str(step.payload))
            return True
        if step.kind == "setting":
            name, value = step.payload
            settings.apply(name, value)
            return True
        if step.kind == "wait":
            return self._sleep_interruptible(step.payload / 1000)
        if step.kind == "expect":
            if not self._wait_for_connection():
                return False
            return self._expect_text(str(step.payload), step.line_number, settings.expect_timeout_ms)
        if step.kind == "capture":
            if not self._wait_for_connection():
                return False
            name, pattern = step.payload
            return self._capture_regex(
                str(name),
                str(pattern),
                step.line_number,
                settings.expect_timeout_ms,
                runtime_variables,
            )
        if not self._wait_for_connection():
            return False
        # Persistent inter-command delay (@@wait) applies before each send/hex.
        if not self._sleep_interruptible(settings.wait_before_ms / 1000):
            return False
        try:
            if step.kind == "send":
                self._reset_expectation_buffer()
                self._send_command(step.payload, settings)
            elif step.kind == "hex":
                self._reset_expectation_buffer()
                self._send_bytes(step.payload, source=BATCH_TX_SOURCE)
        except Exception as exc:
            self._emit("error", f"Batch step on line {step.line_number} failed: {exc}")
            return False
        return True

    def _send_command(self, payload, settings: RunSettings) -> None:
        # A "send" step honours @@send-mode: hex re-parses the text payload as bytes.
        if settings.send_mode == "hex":
            self._send_bytes(parse_hex_payload(str(payload)), source=BATCH_TX_SOURCE)
        else:
            self._send_text(payload, source=BATCH_TX_SOURCE)

    def _expect_text(self, expected: str, line_number: int, timeout_ms: int) -> bool:
        if self._expected_text_available(expected):
            return True
        queue = self._rx_event_queue
        if queue is None:
            self._emit("error", "EXPECT is not available because RX events are not connected to the batch runner.")
            return False
        remaining_timeout = timeout_ms / 1000
        while not self._stop_event.is_set():
            if not self._wait_for_connection():
                return False
            if remaining_timeout <= 0:
                self._emit(
                    "error",
                    f"EXPECT timed out on line {line_number} after {timeout_ms} ms: {expected}",
                )
                return False
            wait_time = min(remaining_timeout, 0.05)
            started_wait = perf_counter()
            try:
                event = queue.get(timeout=wait_time)
            except Empty:
                remaining_timeout -= perf_counter() - started_wait
                continue
            remaining_timeout -= perf_counter() - started_wait
            # Ignore background control-panel poll replies: if the user resumed
            # a panel during this command-file run, its poll RX must not satisfy
            # or pollute our EXPECT window.
            if event.kind == "rx" and getattr(event, "source", "") != CONTROL_PANEL_RX_SOURCE:
                self._rx_buffer += event.message
                if self._expected_text_available(expected):
                    return True
        return False

    def _capture_regex(
        self,
        name: str,
        pattern: str,
        line_number: int,
        timeout_ms: int,
        runtime_variables: dict[str, str],
    ) -> bool:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            self._emit("error", f"CAPTURE regex on line {line_number} is invalid: {exc}")
            return False

        def capture_available() -> tuple[bool, str]:
            match = compiled.search(self._rx_buffer)
            if match is None:
                return False, ""
            value = match.group(1) if compiled.groups else match.group(0)
            if value is None:
                value = ""
            self._rx_buffer = self._rx_buffer[match.end():]
            return True, value

        matched, value = capture_available()
        if matched:
            runtime_variables[name] = value
            return True
        queue = self._rx_event_queue
        if queue is None:
            self._emit("error", "CAPTURE is not available because RX events are not connected to the batch runner.")
            return False
        remaining_timeout = timeout_ms / 1000
        while not self._stop_event.is_set():
            if not self._wait_for_connection():
                return False
            if remaining_timeout <= 0:
                self._emit(
                    "error",
                    f"CAPTURE timed out on line {line_number} after {timeout_ms} ms: {pattern}",
                )
                return False
            wait_time = min(remaining_timeout, 0.05)
            started_wait = perf_counter()
            try:
                event = queue.get(timeout=wait_time)
            except Empty:
                remaining_timeout -= perf_counter() - started_wait
                continue
            remaining_timeout -= perf_counter() - started_wait
            if event.kind == "rx" and getattr(event, "source", "") != CONTROL_PANEL_RX_SOURCE:
                self._rx_buffer += event.message
                matched, value = capture_available()
                if matched:
                    runtime_variables[name] = value
                    return True
        return False

    def _expected_text_available(self, expected: str) -> bool:
        index = self._rx_buffer.find(expected)
        if index < 0:
            return False
        self._rx_buffer = self._rx_buffer[index + len(expected):]
        return True

    def _reset_expectation_buffer(self) -> None:
        self._rx_buffer = ""
        queue = self._rx_event_queue
        if queue is None:
            return
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return

    def _wait_for_connection(self) -> bool:
        while not self._resume_event.is_set():
            if self._stop_event.wait(0.1):
                return False
        return not self._stop_event.is_set()

    def _sleep_interruptible(self, seconds: float) -> bool:
        if seconds <= 0:
            return not self._stop_event.is_set()
        remaining = seconds
        while remaining > 0:
            if not self._wait_for_connection():
                return False
            if remaining <= 0:
                return True
            if self._stop_event.is_set():
                return False
            if remaining <= HIGH_RES_WAIT_THRESHOLD_SECONDS:
                started_wait = perf_counter()
                slept = self._sleep_high_resolution(remaining)
                remaining -= perf_counter() - started_wait
                if not slept:
                    return False
                continue
            wait_time = min(remaining - HIGH_RES_WAIT_THRESHOLD_SECONDS, COARSE_WAIT_CHUNK_SECONDS)
            started_wait = perf_counter()
            if self._stop_event.wait(max(wait_time, 0)):
                return False
            remaining -= perf_counter() - started_wait
        return True

    def _sleep_high_resolution(self, seconds: float) -> bool:
        deadline = perf_counter() + seconds
        while True:
            if self._stop_event.is_set():
                return False
            if perf_counter() >= deadline:
                return True

    def _emit(self, kind: str, message: str) -> None:
        self._emit_event(SerialEvent(kind=kind, message=message, source=BATCH_TX_SOURCE))
