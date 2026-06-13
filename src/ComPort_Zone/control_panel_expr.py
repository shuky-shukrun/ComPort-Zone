"""Safe arithmetic expressions for derived control_panel tiles (FR-61).

A derived entry's value is computed from other entries referenced as
``{Label}`` — e.g. ``{Volts} * {Amps}``. Expressions are parsed with
:func:`ast.parse` and evaluated by a whitelisting interpreter: arithmetic
operators, unary minus, numeric literals, entry references, and a small
function set. There is no ``eval``/``exec``/code-object surface at all,
and inputs are size-capped, so a hostile expression can at worst produce
an :class:`ExpressionError` (NFR-11).

References are stored in label form and resolved at compile time against
the control_panel's current entries: the catalog regenerates entry ids on
duplicate/import, so id-form references would silently break — labels
survive both (and keep exported JSON human-readable). Ambiguous or
missing labels are compile errors, never silent. Only *polled numeric*
entries may be referenced (single level: derived-of-derived is rejected,
which also makes reference cycles impossible).

Qt-free by design (enforced via ``core/control_panel.py`` re-exports).
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .control_panel_models import MAX_EXPRESSION_LENGTH

MAX_EXPRESSION_NODES = 64

EXPR_FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
}

_REF_PATTERN = re.compile(r"\{([^{}]+)\}")
_REF_NAME_TEMPLATE = "_ref_{index}"

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)


class ExpressionError(ValueError):
    """A human-readable expression problem (compile or evaluate time)."""


def normalize_label(label: str) -> str:
    return label.strip().casefold()


@dataclass(slots=True)
class CompiledExpression:
    """A validated expression bound to the entry ids it references."""

    expression: str
    inputs: tuple[str, ...]
    _tree: ast.expr
    _ref_ids: dict[str, str]

    def evaluate(self, values: Mapping[str, float]) -> float:
        """Compute the expression over ``values`` (entry id -> number).

        Raises :class:`ExpressionError` for missing inputs, division by
        zero, overflow, or domain errors — never anything else.
        """
        try:
            result = _eval_node(self._tree, self._ref_ids, values)
        except ExpressionError:
            raise
        except ZeroDivisionError as exc:
            raise ExpressionError("Division by zero.") from exc
        except OverflowError as exc:
            raise ExpressionError("Result is too large.") from exc
        except (ValueError, TypeError) as exc:
            raise ExpressionError(str(exc)) from exc
        if not isinstance(result, (int, float)) or isinstance(result, bool):
            raise ExpressionError("Expression did not produce a number.")
        value = float(result)
        if math.isnan(value) or math.isinf(value):
            raise ExpressionError("Result is not a finite number.")
        return value


def compile_expression(
    text: str,
    resolver: Mapping[str, list[str]],
    *,
    sources: Mapping[str, str] | None = None,
) -> CompiledExpression:
    """Validate ``text`` and resolve its ``{Label}`` references.

    ``resolver`` maps a normalized label to the entry ids carrying it;
    ``sources`` (entry id -> "poll" | "derived") enforces the single-level
    rule when provided. Raises :class:`ExpressionError` with a message fit
    for the entry dialog.
    """
    if not text.strip():
        raise ExpressionError("Expression must not be empty.")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(
            f"Expression is longer than {MAX_EXPRESSION_LENGTH} characters."
        )

    ref_ids: dict[str, str] = {}
    label_for_name: dict[str, str] = {}

    def replace_reference(match: re.Match[str]) -> str:
        label = match.group(1)
        normalized = normalize_label(label)
        if not normalized:
            raise ExpressionError("Empty reference {} is not allowed.")
        candidates = resolver.get(normalized, [])
        if not candidates:
            raise ExpressionError(f"Unknown reference {{{label}}}.")
        if len(candidates) > 1:
            raise ExpressionError(
                f"Reference {{{label}}} is ambiguous ({len(candidates)} entries share that label)."
            )
        entry_id = candidates[0]
        if sources is not None and sources.get(entry_id) == "derived":
            raise ExpressionError(
                f"{{{label}}} is a derived entry — expressions may only reference polled entries."
            )
        for name, existing_id in ref_ids.items():
            if existing_id == entry_id:
                return name
        name = _REF_NAME_TEMPLATE.format(index=len(ref_ids))
        ref_ids[name] = entry_id
        label_for_name[name] = label
        return name

    python_text = _REF_PATTERN.sub(replace_reference, text)
    if "{" in python_text or "}" in python_text:
        raise ExpressionError("Unbalanced { } in expression.")

    try:
        tree = ast.parse(python_text, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Invalid expression: {exc.msg}.") from exc

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_EXPRESSION_NODES:
        raise ExpressionError("Expression is too complex.")
    _validate_node(tree.body, set(ref_ids), label_for_name)

    # Dedupe inputs preserving first-reference order.
    inputs = tuple(dict.fromkeys(ref_ids.values()))
    return CompiledExpression(
        expression=text, inputs=inputs, _tree=tree.body, _ref_ids=ref_ids
    )


def expression_validation_errors(
    text: str,
    resolver: Mapping[str, list[str]],
    sources: Mapping[str, str] | None = None,
) -> list[str]:
    """Dialog-friendly wrapper: compile and return problems as a list."""
    try:
        compile_expression(text, resolver, sources=sources)
    except ExpressionError as exc:
        return [str(exc)]
    return []


def _validate_node(node: ast.expr, ref_names: set[str], labels: dict[str, str]) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("Only numeric literals are allowed.")
        return
    if isinstance(node, ast.Name):
        if node.id not in ref_names:
            raise ExpressionError(f"Unknown name '{node.id}' — reference entries as {{Label}}.")
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ExpressionError("Only + - * / % ** operators are allowed.")
        _validate_node(node.left, ref_names, labels)
        _validate_node(node.right, ref_names, labels)
        return
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise ExpressionError("Only unary + and - are allowed.")
        _validate_node(node.operand, ref_names, labels)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in EXPR_FUNCTIONS:
            raise ExpressionError(
                "Only these functions are allowed: " + ", ".join(sorted(EXPR_FUNCTIONS))
            )
        if node.keywords:
            raise ExpressionError("Keyword arguments are not allowed.")
        for argument in node.args:
            _validate_node(argument, ref_names, labels)
        return
    raise ExpressionError("Unsupported expression element.")


def _eval_node(
    node: ast.expr, ref_ids: dict[str, str], values: Mapping[str, float]
) -> float:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        entry_id = ref_ids[node.id]
        if entry_id not in values:
            raise ExpressionError("Waiting for input values.")
        return float(values[entry_id])
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, ref_ids, values)
        right = _eval_node(node.right, ref_ids, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        return left ** right
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, ref_ids, values)
        return operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name)
        function = EXPR_FUNCTIONS[node.func.id]
        arguments = [_eval_node(argument, ref_ids, values) for argument in node.args]
        return function(*arguments)
    raise ExpressionError("Unsupported expression element.")


def build_label_resolver(entries) -> dict[str, list[str]]:
    """Normalized display label -> entry ids, for compile_expression.

    Includes only entries that can legally be referenced targets-wise
    (numeric polled entries); the sources map still guards explicitly.
    """
    resolver: dict[str, list[str]] = {}
    for entry in entries:
        label = normalize_label(entry.display_label())
        if not label:
            continue
        resolver.setdefault(label, []).append(entry.id)
    return resolver


def rewrite_references(expression: str, old_label: str, new_label: str) -> str:
    """Rename ``{old_label}`` references to ``{new_label}`` (case-insensitive,
    whitespace-tolerant) — used when a referenced entry is renamed."""
    normalized_old = normalize_label(old_label)

    def replace(match: re.Match[str]) -> str:
        if normalize_label(match.group(1)) == normalized_old:
            return "{" + new_label + "}"
        return match.group(0)

    return _REF_PATTERN.sub(replace, expression)
