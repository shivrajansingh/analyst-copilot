"""Arithmetic the model does not have to do in its head.

Half the practice questions are numerical reasoning: a margin, a year-on-year
change, a ratio of two line items. A language model asked to divide 21,410 by
88,187 will often be close and occasionally be wrong, and "occasionally wrong"
is exactly the failure the rubric charges -1 for.

So the model's job is reduced to the part it is good at — finding the two
figures and knowing which operation applies — and the arithmetic is done here,
exactly, by parsing the expression rather than evaluating it. `eval` is not
used: the grammar below is the whole language, and it contains no names,
attributes, calls or subscripts, so there is nothing to escape from.

The expression is also kept on the answer. A derived figure appears nowhere in
the filing, so the only way to prove it is to show the inputs, show the
operation, and let the verifier re-run it.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Dict, Optional

from analyst_copilot.agent.tools.base import Tool, ToolResult, schema

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# Only these names may be called, and each is a plain numeric function.
_FUNCTIONS: Dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
}

# Filings write figures the way an annual report prints them, and a model
# copying a figure out of a table copies the punctuation with it. Rather than
# demand clean input, the obvious dressing is removed first: currency symbols,
# digit grouping, a trailing percent sign, and the parentheses accountants use
# for a negative number.
_CURRENCY = re.compile(r"[$€£¥]")
_GROUPING = re.compile(r"(?<=\d),(?=\d)")
_ACCOUNTING_NEGATIVE = re.compile(r"\((\s*[\d.,\s+\-*/]+\s*)\)\s*(?=$|[+\-*/)])")

MAX_EXPRESSION_LENGTH = 400
# Bound on exponentiation, so `9**9**9` cannot hang the worker computing a
# number no filing contains.
MAX_POWER = 64


class CalculationError(ValueError):
    """The expression could not be evaluated as arithmetic."""


def normalize_expression(expression: str) -> str:
    """Strip the punctuation a figure carries when copied out of a filing."""
    text = expression.strip()
    text = _CURRENCY.sub("", text)
    text = _GROUPING.sub("", text)
    text = text.replace("−", "-").replace("–", "-").replace("×", "*").replace("÷", "/")
    text = text.replace("^", "**")
    # A trailing percent is a unit, not an operator: "12.5%" is the number.
    text = re.sub(r"(?<=[\d.])\s*%", "", text)
    return text.strip()


def evaluate(expression: str) -> float:
    """Evaluate an arithmetic expression, or raise `CalculationError`."""
    if not expression or not expression.strip():
        raise CalculationError("The expression is empty.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise CalculationError(
            f"The expression is longer than {MAX_EXPRESSION_LENGTH} characters."
        )

    text = normalize_expression(expression)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"{text!r} is not arithmetic: {exc.msg}.") from exc

    value = _eval(tree.body)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalculationError("The expression did not evaluate to a number.")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CalculationError("The expression produced an infinite or undefined value.")
    return float(value)


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalculationError(f"{node.value!r} is not a number.")
        return node.value

    if isinstance(node, ast.BinOp):
        handler = _BINARY.get(type(node.op))
        if handler is None:
            raise CalculationError(f"{type(node.op).__name__} is not a supported operator.")
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POWER:
            raise CalculationError(f"Exponents above {MAX_POWER} are not allowed.")
        try:
            return handler(left, right)
        except ZeroDivisionError as exc:
            raise CalculationError("Division by zero.") from exc

    if isinstance(node, ast.UnaryOp):
        handler = _UNARY.get(type(node.op))
        if handler is None:
            raise CalculationError(f"{type(node.op).__name__} is not a supported operator.")
        return handler(_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            allowed = ", ".join(sorted(_FUNCTIONS))
            raise CalculationError(f"Only these functions may be called: {allowed}.")
        if node.keywords:
            raise CalculationError("Functions take positional arguments only.")
        return _FUNCTIONS[node.func.id](*[_eval(arg) for arg in node.args])

    raise CalculationError(
        f"{type(node).__name__} is not allowed in an arithmetic expression."
    )


def format_result(value: float) -> str:
    """Render a result without inventing precision or losing it."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    rounded = round(value, 6)
    text = f"{rounded:.6f}".rstrip("0").rstrip(".")
    return text or "0"


class CalculateTool(Tool):
    name = "calculate"
    description = """
Evaluate an arithmetic expression exactly. Use this for EVERY calculation
instead of computing in your head — a margin, a growth rate, a ratio, a sum of
segments, a change between two years.

Supports + - * / // % ** and parentheses, plus abs, round, min, max, sqrt.
Figures may be written as they appear in the filing: 1,577 and $1,577 and
(1,577) are all accepted, and a trailing % is read as the number.

Example: to express 21,410 of 88,187 as a percentage, pass
expression="21410 / 88187 * 100".
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return schema(
            {
                "expression": {
                    "type": "string",
                    "description": "The arithmetic to evaluate, e.g. '(4223 - 3892) / 3892 * 100'.",
                }
            },
            required=["expression"],
        )

    def run(self, expression: Optional[str] = None, **_extra: Any) -> ToolResult:
        if expression is None:
            return ToolResult.failure("calculate needs an 'expression'.")
        try:
            value = evaluate(str(expression))
        except CalculationError as exc:
            return ToolResult.failure(str(exc))

        rendered = format_result(value)
        return ToolResult(
            content=f"{normalize_expression(str(expression))} = {rendered}",
            meta={"expression": str(expression), "result": value},
        )
