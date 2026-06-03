"""Lightweight expression engine for referencing data between nodes.

Supports ``{{ expression }}`` syntax inside input string values.
Expressions can reference node outputs, context fields, and apply
simple operations.

Examples
--------
- ``{{ $node["scanner_1"].data.jobs }}``
  → resolves to the ``jobs`` key of scanner_1's output
- ``{{ $context.user_id }}``
  → resolves to the context-level user_id
- ``{{ $node["scorer"].data.scored_count > 0 }}``
  → boolean evaluation
- ``{{ $json.field }}``
  → shorthand for the immediately-previous node's output
"""
from __future__ import annotations

import ast
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Pattern for {{ ... }} template expressions
_EXPR_PATTERN = re.compile(r"\{\{(.+?)\}\}", re.DOTALL)

# Pattern for $node["name"].data.path references
_NODE_REF_PATTERN = re.compile(
    r"""\$node\[["']([^"']+)["']\]\.data(?:\.(\S+))?"""
)

# Pattern for $context.path references
_CTX_REF_PATTERN = re.compile(r"\$context\.(\S+)")

# Pattern for $json.path references (previous node shorthand)
_JSON_REF_PATTERN = re.compile(r"\$json\.(\S+)")


def _safe_resolve_path(data: Any, path: str) -> Any:
    """Navigate a dot-separated path into nested dicts/lists."""
    current = data
    for key in path.split("."):
        if not key:
            continue
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def _resolve_references(
    raw: str,
    node_outputs: Dict[str, Any],
    context: Dict[str, Any],
    previous_node_id: Optional[str] = None,
) -> str:
    """Replace ``$node``, ``$context``, and ``$json`` references with values."""

    def _replace_node_ref(m: re.Match) -> str:
        node_id = m.group(1)
        path = m.group(2) or ""
        output = node_outputs.get(node_id)
        if output is None:
            return "None"
        if path:
            val = _safe_resolve_path(output, path)
        else:
            val = output
        return repr(val)

    def _replace_ctx_ref(m: re.Match) -> str:
        path = m.group(1)
        val = _safe_resolve_path(context, path)
        return repr(val)

    def _replace_json_ref(m: re.Match) -> str:
        path = m.group(1)
        if previous_node_id and previous_node_id in node_outputs:
            val = _safe_resolve_path(node_outputs[previous_node_id], path)
        else:
            val = None
        return repr(val)

    result = _NODE_REF_PATTERN.sub(_replace_node_ref, raw)
    result = _CTX_REF_PATTERN.sub(_replace_ctx_ref, result)
    result = _JSON_REF_PATTERN.sub(_replace_json_ref, result)
    return result


def _safe_eval(expr_str: str) -> Any:
    """Evaluate a simple Python expression safely using AST.

    Only allows literals, comparisons, boolean operators, unary ops,
    attribute access, subscript, and basic builtins (len, str, int,
    float, bool, list, dict, min, max, abs, round, sorted, sum).
    """
    _SAFE_BUILTINS = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "sorted": sorted,
        "sum": sum,
        "True": True,
        "False": False,
        "None": None,
    }

    try:
        tree = ast.parse(expr_str.strip(), mode="eval")
    except SyntaxError:
        return expr_str

    # Walk the AST and reject unsafe nodes
    _ALLOWED = (
        ast.Expression,
        ast.Constant,
        ast.Num,
        ast.Str,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Set,
        ast.Name,
        ast.Load,
        ast.UnaryOp,
        ast.UAdd,
        ast.USub,
        ast.Not,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Is,
        ast.IsNot,
        ast.In,
        ast.NotIn,
        ast.IfExp,
        ast.Subscript,
        ast.Index,
        ast.Slice,
        ast.Attribute,
        ast.Call,
        ast.Starred,
        ast.FormattedValue,
        ast.JoinedStr,
    )
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            logger.warning("Expression engine rejected AST node: %s", type(node).__name__)
            return expr_str

    # Restrict callable names
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in _SAFE_BUILTINS:
                logger.warning("Expression engine rejected call: %s", node.func.id)
                return expr_str

    try:
        return eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, _SAFE_BUILTINS)  # noqa: S307
    except Exception as exc:
        logger.debug("Expression eval failed: %s — %s", expr_str, exc)
        return expr_str


def evaluate_expression(
    template: str,
    node_outputs: Dict[str, Any],
    context: Dict[str, Any],
    previous_node_id: Optional[str] = None,
) -> Any:
    """Resolve ``{{ expr }}`` templates in a string.

    If the entire string is a single expression, returns the native
    Python value (not forced to string).  If there are multiple
    expressions intermixed with literal text, the result is a string.
    """
    matches = list(_EXPR_PATTERN.finditer(template))
    if not matches:
        return template

    # Single expression occupying the whole string → return native type
    if len(matches) == 1 and matches[0].start() == 0 and matches[0].end() == len(template):
        inner = matches[0].group(1).strip()
        resolved = _resolve_references(inner, node_outputs, context, previous_node_id)
        return _safe_eval(resolved)

    # Multiple / partial expressions → string interpolation
    result = template
    for m in reversed(matches):
        inner = m.group(1).strip()
        resolved = _resolve_references(inner, node_outputs, context, previous_node_id)
        replacement = _safe_eval(resolved)
        result = result[: m.start()] + str(replacement) + result[m.end() :]
    return result


def resolve_inputs_with_expressions(
    inputs: Dict[str, Any],
    node_outputs: Dict[str, Any],
    context: Dict[str, Any],
    previous_node_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk an inputs dict and resolve any ``{{ }}`` expressions in string values."""
    resolved: Dict[str, Any] = {}
    for key, value in inputs.items():
        resolved[key] = _resolve_value(value, node_outputs, context, previous_node_id)
    return resolved


def _resolve_value(
    value: Any,
    node_outputs: Dict[str, Any],
    context: Dict[str, Any],
    previous_node_id: Optional[str],
) -> Any:
    if isinstance(value, str) and "{{" in value:
        return evaluate_expression(value, node_outputs, context, previous_node_id)
    if isinstance(value, dict):
        return {k: _resolve_value(v, node_outputs, context, previous_node_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v, node_outputs, context, previous_node_id) for v in value]
    return value
