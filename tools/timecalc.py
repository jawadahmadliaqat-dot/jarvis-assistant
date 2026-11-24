"""Time, date and a safe calculator."""

from __future__ import annotations

import ast
import datetime
import math
import operator
from typing import Any
from zoneinfo import ZoneInfo

from tools.registry import Tool, ToolRegistry

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_SAFE_FUNCS = {
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "exp": math.exp,
    "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
    "pi": math.pi, "e": math.e,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _SAFE_FUNCS.get(node.func.id)
        if fn is None or not callable(fn):
            raise ValueError(f"function '{node.func.id}' is not allowed")
        return float(fn(*[_eval(a) for a in node.args]))
    if isinstance(node, ast.Name) and node.id in _SAFE_FUNCS:
        value = _SAFE_FUNCS[node.id]
        if isinstance(value, (int, float)):
            return float(value)
    raise ValueError("unsupported expression")


def calculate(expression: str) -> str:
    """Evaluate a maths expression safely (no eval, no imports)."""
    expr = expression.strip()
    if not expr:
        return "Nothing to calculate."
    try:
        tree = ast.parse(expr, mode="eval")
        result = _eval(tree)
        if result == int(result):
            return f"{expr} = {int(result)}"
        return f"{expr} = {result:.6g}"
    except Exception as exc:  # noqa: BLE001
        return f"Could not calculate '{expr}': {exc}"


def _tz(context: dict[str, Any]):
    tz_name = (context.get("config").timezone if context.get("config") else "Asia/Karachi")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return datetime.timezone.utc


def get_time(context: dict[str, Any]) -> str:
    now = datetime.datetime.now(_tz(context))
    return f"It is {now.strftime('%I:%M %p')} on {now.strftime('%A, %B %d, %Y')}."


def get_date(context: dict[str, Any]) -> str:
    now = datetime.datetime.now(_tz(context))
    return f"Today is {now.strftime('%A, %B %d, %Y')}."


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    registry.register(
        Tool(
            name="get_time",
            description="Current time and date in the user's timezone.",
            parameters={"type": "object", "properties": {}},
            func=lambda: get_time(context),
        )
    )
    registry.register(
        Tool(
            name="get_date",
            description="Today's date.",
            parameters={"type": "object", "properties": {}},
            func=lambda: get_date(context),
        )
    )
    registry.register(
        Tool(
            name="calculate",
            description="Evaluate a maths expression, e.g. '12 * 8 + sqrt(16)'.",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "maths expression"},
                },
                "required": ["expression"],
            },
            func=calculate,
        )
    )
