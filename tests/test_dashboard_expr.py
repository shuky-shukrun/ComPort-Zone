"""Tests for the derived-tile expression engine (safety + semantics)."""

from __future__ import annotations

import unittest

from ComPort_Zone.dashboard_expr import (
    ExpressionError,
    MAX_EXPRESSION_NODES,
    build_label_resolver,
    compile_expression,
    expression_validation_errors,
    normalize_label,
    rewrite_references,
)
from ComPort_Zone.dashboard_models import DashboardEntry, MAX_EXPRESSION_LENGTH

RESOLVER = {
    "volts": ["id-volts"],
    "amps": ["id-amps"],
    "temp": ["id-temp"],
    "dupe": ["id-a", "id-b"],
    "computed": ["id-computed"],
}
SOURCES = {
    "id-volts": "poll",
    "id-amps": "poll",
    "id-temp": "poll",
    "id-computed": "derived",
}
VALUES = {"id-volts": 13.2, "id-amps": 2.5, "id-temp": -40.0}


def evaluate(text: str, values=None) -> float:
    compiled = compile_expression(text, RESOLVER, sources=SOURCES)
    return compiled.evaluate(VALUES if values is None else values)


class ArithmeticTests(unittest.TestCase):
    def test_basic_operations(self) -> None:
        self.assertAlmostEqual(evaluate("{Volts} * {Amps}"), 33.0)
        self.assertAlmostEqual(evaluate("{Volts} + {Amps}"), 15.7)
        self.assertAlmostEqual(evaluate("{Volts} - {Amps}"), 10.7)
        self.assertAlmostEqual(evaluate("{Volts} / {Amps}"), 5.28)
        self.assertAlmostEqual(evaluate("{Amps} % 2"), 0.5)
        self.assertAlmostEqual(evaluate("{Amps} ** 2"), 6.25)
        self.assertAlmostEqual(evaluate("-{Temp}"), 40.0)
        self.assertAlmostEqual(evaluate("({Volts} + 1) * 2"), 28.4)
        self.assertAlmostEqual(evaluate("3"), 3.0)

    def test_functions(self) -> None:
        self.assertAlmostEqual(evaluate("abs({Temp})"), 40.0)
        self.assertAlmostEqual(evaluate("min({Volts}, {Amps})"), 2.5)
        self.assertAlmostEqual(evaluate("max({Volts}, {Amps}, 20)"), 20.0)
        self.assertAlmostEqual(evaluate("round({Volts})"), 13.0)
        self.assertAlmostEqual(evaluate("sqrt({Amps} * 10)"), 5.0)

    def test_case_insensitive_and_whitespace_tolerant_refs(self) -> None:
        self.assertAlmostEqual(evaluate("{ VOLTS } * 2"), 26.4)

    def test_same_ref_twice_counts_one_input(self) -> None:
        compiled = compile_expression("{Volts} * {Volts}", RESOLVER, sources=SOURCES)
        self.assertEqual(compiled.inputs, ("id-volts",))

    def test_inputs_preserve_reference_order(self) -> None:
        compiled = compile_expression("{Amps} + {Volts}", RESOLVER, sources=SOURCES)
        self.assertEqual(compiled.inputs, ("id-amps", "id-volts"))


class RejectionTests(unittest.TestCase):
    def assert_rejected(self, text: str, fragment: str) -> None:
        with self.assertRaises(ExpressionError) as ctx:
            compile_expression(text, RESOLVER, sources=SOURCES)
        self.assertIn(fragment, str(ctx.exception))

    def test_empty(self) -> None:
        self.assert_rejected("   ", "must not be empty")

    def test_too_long(self) -> None:
        self.assert_rejected("1+" * (MAX_EXPRESSION_LENGTH // 2 + 2) + "1", "longer than")

    def test_too_many_nodes(self) -> None:
        text = "+".join(["1"] * (MAX_EXPRESSION_NODES + 4))
        self.assert_rejected(text, "too complex")

    def test_unknown_reference(self) -> None:
        self.assert_rejected("{Pressure} * 2", "Unknown reference {Pressure}")

    def test_ambiguous_reference(self) -> None:
        self.assert_rejected("{Dupe} * 2", "ambiguous")

    def test_derived_reference_rejected(self) -> None:
        self.assert_rejected("{Computed} + 1", "only reference polled entries")

    def test_comparisons_rejected(self) -> None:
        self.assert_rejected("{Volts} > 2", "Unsupported expression element")

    def test_attributes_rejected(self) -> None:
        self.assert_rejected("(1).__class__", "Unsupported expression element")

    def test_subscripts_rejected(self) -> None:
        self.assert_rejected("abs([1])", "Unsupported expression element")

    def test_lambdas_rejected(self) -> None:
        self.assert_rejected("(lambda: 1)()", "functions are allowed")

    def test_unknown_function_rejected(self) -> None:
        self.assert_rejected("__import__('os')", "functions are allowed")

    def test_bare_names_rejected(self) -> None:
        self.assert_rejected("volts * 2", "Unknown name 'volts'")

    def test_keyword_arguments_rejected(self) -> None:
        self.assert_rejected("round({Volts}, ndigits=1)", "Keyword arguments")

    def test_string_literals_rejected(self) -> None:
        self.assert_rejected("'os' + 'x'", "numeric literals")

    def test_boolean_literals_rejected(self) -> None:
        self.assert_rejected("True + 1", "numeric literals")

    def test_unbalanced_braces_rejected(self) -> None:
        self.assert_rejected("{Volts * 2", "Unbalanced")

    def test_syntax_error_rejected(self) -> None:
        self.assert_rejected("{Volts} *", "Invalid expression")

    def test_empty_reference_rejected(self) -> None:
        # "{}" never matches the reference pattern, so it surfaces as
        # unbalanced braces; a whitespace-only reference is the true
        # empty-reference case.
        self.assert_rejected("{} + 1", "Unbalanced")
        self.assert_rejected("{  } + 1", "Empty reference")


class EvaluationErrorTests(unittest.TestCase):
    def test_division_by_zero(self) -> None:
        compiled = compile_expression("{Volts} / ({Amps} - 2.5)", RESOLVER, sources=SOURCES)
        with self.assertRaises(ExpressionError) as ctx:
            compiled.evaluate(VALUES)
        self.assertIn("Division by zero", str(ctx.exception))

    def test_missing_input_value(self) -> None:
        compiled = compile_expression("{Volts} * 2", RESOLVER, sources=SOURCES)
        with self.assertRaises(ExpressionError) as ctx:
            compiled.evaluate({})
        self.assertIn("Waiting for input", str(ctx.exception))

    def test_math_domain_error(self) -> None:
        compiled = compile_expression("sqrt({Temp})", RESOLVER, sources=SOURCES)
        with self.assertRaises(ExpressionError):
            compiled.evaluate(VALUES)

    def test_overflow(self) -> None:
        compiled = compile_expression("{Volts} ** 9999", RESOLVER, sources=SOURCES)
        with self.assertRaises(ExpressionError):
            compiled.evaluate(VALUES)

    def test_wrong_arity_is_expression_error(self) -> None:
        compiled = compile_expression("sqrt({Volts}, {Amps})", RESOLVER, sources=SOURCES)
        with self.assertRaises(ExpressionError):
            compiled.evaluate(VALUES)


class HelperTests(unittest.TestCase):
    def test_validation_errors_wrapper(self) -> None:
        self.assertEqual(
            expression_validation_errors("{Volts} * 2", RESOLVER, SOURCES), []
        )
        errors = expression_validation_errors("{Nope}", RESOLVER, SOURCES)
        self.assertEqual(len(errors), 1)
        self.assertIn("Unknown reference", errors[0])

    def test_build_label_resolver(self) -> None:
        entries = [
            DashboardEntry(id="a", label="Rail A", command="A?"),
            DashboardEntry(id="b", label="rail a", command="B?"),
            DashboardEntry(id="c", command="C?"),  # label falls back to command
        ]
        resolver = build_label_resolver(entries)
        self.assertEqual(resolver["rail a"], ["a", "b"])
        self.assertEqual(resolver["c?"], ["c"])

    def test_normalize_label(self) -> None:
        self.assertEqual(normalize_label("  Rail A  "), "rail a")

    def test_rewrite_references(self) -> None:
        rewritten = rewrite_references("{Volts} + { volts } * {Amps}", "Volts", "Rail A")
        self.assertEqual(rewritten, "{Rail A} + {Rail A} * {Amps}")
        unchanged = rewrite_references("{Amps} * 2", "Volts", "Rail A")
        self.assertEqual(unchanged, "{Amps} * 2")


if __name__ == "__main__":
    unittest.main()
