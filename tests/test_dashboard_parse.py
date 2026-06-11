"""Tests for dashboard response parsing and color-rule evaluation."""

from __future__ import annotations

import unittest

from ComPort_Zone.dashboard_models import ColorRule, ParseRule
from ComPort_Zone.dashboard_parse import (
    CompiledParseRule,
    MAX_RX_WINDOW_CHARS,
    ParseOutcome,
    append_to_window,
    evaluate_rules,
    format_tile_value,
    parse_response,
)


def line_rule(value_type: str = "text") -> CompiledParseRule:
    return CompiledParseRule.compile(ParseRule(kind="line", value_type=value_type))


def regex_rule(pattern: str, group: int | str = 1, value_type: str = "text") -> CompiledParseRule:
    return CompiledParseRule.compile(
        ParseRule(kind="regex", pattern=pattern, group=group, value_type=value_type)
    )


class CompileTests(unittest.TestCase):
    def test_compile_rejects_invalid_regex(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            CompiledParseRule.compile(ParseRule(kind="regex", pattern="(open"))
        self.assertIn("Invalid regex", str(ctx.exception))

    def test_compile_rejects_missing_group(self) -> None:
        with self.assertRaises(ValueError):
            CompiledParseRule.compile(ParseRule(kind="regex", pattern=r"\d+", group=3))

    def test_compile_line_rule_has_no_pattern(self) -> None:
        compiled = line_rule()
        self.assertIsNone(compiled.pattern)


class LineParseTests(unittest.TestCase):
    def test_partial_line_keeps_waiting(self) -> None:
        self.assertIsNone(parse_response(line_rule(), "13."))

    def test_line_completes_across_chunks(self) -> None:
        rule = line_rule(value_type="number")
        window = "13."
        self.assertIsNone(parse_response(rule, window))
        window = append_to_window(window, "2\r\n")
        outcome = parse_response(rule, window)
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.value_number, 13.2)

    def test_terminator_variants(self) -> None:
        for terminator in ("\r\n", "\n", "\r"):
            outcome = parse_response(line_rule(), f"OK{terminator}")
            assert outcome is not None
            self.assertEqual(outcome.value_text, "OK", msg=repr(terminator))

    def test_leading_blank_lines_skipped(self) -> None:
        outcome = parse_response(line_rule(), "\r\n  \r\nREADY\r\n")
        assert outcome is not None
        self.assertEqual(outcome.value_text, "READY")

    def test_blank_lines_only_keeps_waiting(self) -> None:
        self.assertIsNone(parse_response(line_rule(), "\r\n\r\n   \r\n"))

    def test_value_is_stripped(self) -> None:
        outcome = parse_response(line_rule(), "  13.2  \r\n")
        assert outcome is not None
        self.assertEqual(outcome.value_text, "13.2")


class RegexParseTests(unittest.TestCase):
    def test_unmatched_keeps_waiting(self) -> None:
        self.assertIsNone(parse_response(regex_rule(r"V=([\d.]+)"), "T=21.0\r\n"))

    def test_numbered_group(self) -> None:
        outcome = parse_response(regex_rule(r"V=([\d.]+)", 1, "number"), "junk V=13.2 junk")
        assert outcome is not None
        self.assertEqual(outcome.value_number, 13.2)

    def test_named_group(self) -> None:
        outcome = parse_response(regex_rule(r"V=(?P<volts>[\d.]+)", "volts"), "V=3.30")
        assert outcome is not None
        self.assertEqual(outcome.value_text, "3.30")

    def test_group_zero_is_whole_match(self) -> None:
        outcome = parse_response(regex_rule(r"ERR-\d+", 0), "stuff ERR-42 stuff")
        assert outcome is not None
        self.assertEqual(outcome.value_text, "ERR-42")

    def test_optional_unmatched_group_yields_empty(self) -> None:
        outcome = parse_response(regex_rule(r"OK(?: code=(\d+))?", 1), "OK\r\n")
        assert outcome is not None
        self.assertEqual(outcome.value_text, "")


class NumberConversionTests(unittest.TestCase):
    def test_number_conversion_failure_is_matched_with_error(self) -> None:
        outcome = parse_response(line_rule(value_type="number"), "ERR\r\n")
        assert outcome is not None
        self.assertTrue(outcome.matched)
        self.assertIsNone(outcome.value_number)
        self.assertIn("Not a number", outcome.error)
        self.assertEqual(outcome.value_text, "ERR")

    def test_number_accepts_scientific_notation(self) -> None:
        outcome = parse_response(line_rule(value_type="number"), "1.5e-3\r\n")
        assert outcome is not None
        self.assertEqual(outcome.value_number, 0.0015)


class WindowCapTests(unittest.TestCase):
    def test_append_caps_to_tail(self) -> None:
        window = append_to_window("", "x" * (MAX_RX_WINDOW_CHARS + 500))
        self.assertEqual(len(window), MAX_RX_WINDOW_CHARS)

    def test_match_found_in_tail_after_flood(self) -> None:
        window = ""
        for _ in range(8):
            window = append_to_window(window, "noise " * 200)
        window = append_to_window(window, "V=13.2\r\n")
        outcome = parse_response(regex_rule(r"V=([\d.]+)", 1, "number"), window)
        assert outcome is not None
        self.assertEqual(outcome.value_number, 13.2)
        self.assertLessEqual(len(window), MAX_RX_WINDOW_CHARS)


class RuleEvaluationTests(unittest.TestCase):
    def test_ordered_first_match_wins(self) -> None:
        rules = [
            ColorRule(op="gt", operand="10", state="warn"),
            ColorRule(op="gt", operand="5", state="fail"),
        ]
        verdict = evaluate_rules(rules, ParseOutcome(True, "12", 12.0))
        self.assertEqual(verdict.state, "warn")

    def test_between_bounds_are_inclusive(self) -> None:
        rules = [ColorRule(op="between", operand="1.0", operand2="2.0", state="ok")]
        for value in (1.0, 1.5, 2.0):
            verdict = evaluate_rules(rules, ParseOutcome(True, str(value), value))
            self.assertEqual(verdict.state, "ok", msg=str(value))
        verdict = evaluate_rules(rules, ParseOutcome(True, "2.1", 2.1))
        self.assertEqual(verdict.state, "neutral")

    def test_numeric_ops_skipped_for_non_numeric_value(self) -> None:
        rules = [
            ColorRule(op="lt", operand="5", state="fail"),
            ColorRule(op="contains", operand="ERR", state="warn"),
        ]
        verdict = evaluate_rules(rules, ParseOutcome(True, "ERR-42", None))
        self.assertEqual(verdict.state, "warn")

    def test_text_operators(self) -> None:
        outcome = ParseOutcome(True, "FAULT: OVERTEMP", None)
        self.assertEqual(
            evaluate_rules([ColorRule(op="eq_text", operand="FAULT: OVERTEMP", state="fail")], outcome).state,
            "fail",
        )
        self.assertEqual(
            evaluate_rules([ColorRule(op="contains", operand="OVERTEMP", state="warn")], outcome).state,
            "warn",
        )
        self.assertEqual(
            evaluate_rules([ColorRule(op="matches", operand=r"FAULT.*TEMP", state="fail")], outcome).state,
            "fail",
        )

    def test_label_override_carried(self) -> None:
        rules = [ColorRule(op="eq_text", operand="1", state="fail", label="TRIPPED")]
        verdict = evaluate_rules(rules, ParseOutcome(True, "1", None))
        self.assertEqual(verdict.label, "TRIPPED")

    def test_empty_rules_neutral(self) -> None:
        self.assertEqual(evaluate_rules([], ParseOutcome(True, "x", None)).state, "neutral")

    def test_parse_error_outcome_is_error_state(self) -> None:
        outcome = ParseOutcome(True, "ERR", None, error="Not a number: 'ERR'")
        self.assertEqual(evaluate_rules([ColorRule(op="eq_text", operand="ERR")], outcome).state, "error")

    def test_unmatched_outcome_is_neutral(self) -> None:
        self.assertEqual(evaluate_rules([], ParseOutcome(False)).state, "neutral")

    def test_equal_and_not_equal_numbers(self) -> None:
        rules = [ColorRule(op="eq_num", operand="0", state="ok"), ColorRule(op="ne_num", operand="0", state="fail")]
        self.assertEqual(evaluate_rules(rules, ParseOutcome(True, "0", 0.0)).state, "ok")
        self.assertEqual(evaluate_rules(rules, ParseOutcome(True, "3", 3.0)).state, "fail")

    def test_invalid_rule_regex_skipped_at_runtime(self) -> None:
        rules = [ColorRule(op="matches", operand="(bad", state="fail")]
        self.assertEqual(evaluate_rules(rules, ParseOutcome(True, "anything", None)).state, "neutral")


class FormatTests(unittest.TestCase):
    def test_number_six_significant_digits(self) -> None:
        outcome = ParseOutcome(True, "13.20000001", 13.20000001)
        self.assertEqual(format_tile_value(outcome, "V"), "13.2 V")

    def test_large_number(self) -> None:
        outcome = ParseOutcome(True, "1234567.8", 1234567.8)
        self.assertEqual(format_tile_value(outcome, ""), "1.23457e+06")

    def test_text_with_unit(self) -> None:
        self.assertEqual(format_tile_value(ParseOutcome(True, "ON", None), "state"), "ON state")

    def test_unmatched_renders_dash(self) -> None:
        self.assertEqual(format_tile_value(ParseOutcome(False), "V"), "—")

    def test_empty_text_renders_dash_without_unit(self) -> None:
        self.assertEqual(format_tile_value(ParseOutcome(True, "", None), "V"), "—")


if __name__ == "__main__":
    unittest.main()
