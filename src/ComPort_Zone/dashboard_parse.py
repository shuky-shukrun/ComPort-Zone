"""Response parsing and color-rule evaluation for dashboard entries.

The poll dispatcher accumulates post-send RX text into a bounded window
and calls :func:`parse_response` after every chunk. ``None`` means "no
decision yet, keep collecting"; a :class:`ParseOutcome` ends the
transaction. Rule evaluation maps a finished outcome to a semantic tile
state (:class:`RuleVerdict`).

Qt-free by design (enforced via ``core/dashboard.py`` re-exports).

Requirements: docs/dashboard-view-requirements.md (FR-24..FR-30).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .dashboard_models import NUMERIC_RULE_OPS, ColorRule, ParseRule

# Rolling correlation buffer cap. Bounds both memory and regex input size
# (stdlib ``re`` has no timeout, so bounding the haystack is the practical
# guard against catastrophic backtracking — NFR-3/NFR-5).
MAX_RX_WINDOW_CHARS = 4096

_LINE_TERMINATORS = re.compile(r"[\r\n]")


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """Result of one finished parse attempt.

    ``matched`` is True when the rule produced a value (even if number
    conversion then failed — ``error`` holds the reason and the tile
    renders the error state instead of waiting for a timeout).
    """

    matched: bool
    value_text: str = ""
    value_number: float | None = None
    error: str = ""


@dataclass(frozen=True, slots=True)
class RuleVerdict:
    """Semantic state a tile should render, plus optional label override."""

    state: str
    label: str = ""


class CompiledParseRule:
    """A validated :class:`ParseRule` with its regex precompiled.

    Compile once per entry (configuration time), evaluate per RX chunk.
    """

    __slots__ = ("rule", "pattern")

    def __init__(self, rule: ParseRule, pattern: re.Pattern[str] | None) -> None:
        self.rule = rule
        self.pattern = pattern

    @classmethod
    def compile(cls, rule: ParseRule) -> "CompiledParseRule":
        """Validate and compile ``rule``; raises ValueError with a friendly
        message when the rule is unusable."""
        errors = rule.validation_errors()
        if errors:
            raise ValueError(" ".join(errors))
        pattern = re.compile(rule.pattern) if rule.kind == "regex" else None
        return cls(rule, pattern)


def append_to_window(window: str, chunk: str, limit: int = MAX_RX_WINDOW_CHARS) -> str:
    """Append RX text to the rolling window, keeping only the tail."""
    combined = window + chunk
    if len(combined) <= limit:
        return combined
    return combined[-limit:]


def parse_response(compiled: CompiledParseRule, window: str) -> ParseOutcome | None:
    """Try to extract a value from the accumulated post-send window.

    Returns ``None`` while undecided (keep collecting until the entry's
    timeout). "line" rules take the first non-blank complete line; "regex"
    rules search the whole window and take the configured capture group.
    """
    rule = compiled.rule
    if rule.kind == "regex":
        assert compiled.pattern is not None
        match = compiled.pattern.search(window)
        if match is None:
            return None
        captured = match.group(rule.group)
        return _finish(rule, captured if captured is not None else "")
    line = _first_complete_line(window)
    if line is None:
        return None
    return _finish(rule, line)


def _first_complete_line(window: str) -> str | None:
    """First non-blank terminated line, or None when no line is complete.

    Blank lines (a common artifact of CRLF echo) are skipped rather than
    reported as an empty value.
    """
    position = 0
    while True:
        match = _LINE_TERMINATORS.search(window, position)
        if match is None:
            return None
        line = window[position : match.start()].strip()
        if line:
            return line
        position = match.end()


def _finish(rule: ParseRule, captured: str) -> ParseOutcome:
    value_text = captured.strip()
    if rule.value_type != "number":
        return ParseOutcome(matched=True, value_text=value_text)
    try:
        number = float(value_text)
    except ValueError:
        return ParseOutcome(
            matched=True,
            value_text=value_text,
            value_number=None,
            error=f"Not a number: '{value_text}'",
        )
    return ParseOutcome(matched=True, value_text=value_text, value_number=number)


def evaluate_rules(rules: Sequence[ColorRule], outcome: ParseOutcome) -> RuleVerdict:
    """Map a finished outcome to a tile state, first matching rule wins.

    Outcomes carrying a parse error render "error"; numeric operators are
    skipped when the value is not numeric; no match falls back to
    "neutral" (FR-29/FR-30).
    """
    if not outcome.matched:
        return RuleVerdict("neutral")
    if outcome.error:
        return RuleVerdict("error")
    for rule in rules:
        if _rule_matches(rule, outcome):
            return RuleVerdict(rule.state, rule.label)
    return RuleVerdict("neutral")


def _rule_matches(rule: ColorRule, outcome: ParseOutcome) -> bool:
    if rule.op in NUMERIC_RULE_OPS:
        value = outcome.value_number
        if value is None:
            return False
        try:
            operand = float(rule.operand)
        except ValueError:
            return False
        if rule.op == "lt":
            return value < operand
        if rule.op == "le":
            return value <= operand
        if rule.op == "gt":
            return value > operand
        if rule.op == "ge":
            return value >= operand
        if rule.op == "eq_num":
            return value == operand
        if rule.op == "ne_num":
            return value != operand
        try:
            upper = float(rule.operand2)
        except ValueError:
            return False
        return operand <= value <= upper
    if rule.op == "eq_text":
        return outcome.value_text == rule.operand
    if rule.op == "contains":
        return rule.operand in outcome.value_text
    if rule.op == "matches":
        try:
            return re.search(rule.operand, outcome.value_text) is not None
        except re.error:
            return False
    return False


def format_tile_value(outcome: ParseOutcome, unit: str) -> str:
    """Render an outcome for display: 6 significant digits for numbers,
    raw text otherwise, with the unit suffixed when present."""
    if not outcome.matched:
        return "—"
    if outcome.value_number is not None:
        text = f"{outcome.value_number:.6g}"
    else:
        text = outcome.value_text or "—"
    if unit and text != "—":
        return f"{text} {unit}"
    return text
