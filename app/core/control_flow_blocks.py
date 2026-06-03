"""Control-flow blocks for n8n-style automation pipelines.

These blocks handle conditional branching, looping, merging, data
transformation, and flow delays.  They integrate with the standard
BlockRegistry / BlockBase contract so the FlowExecutor can route
execution paths based on their output signals.
"""
from __future__ import annotations

import asyncio
import logging
import operator
from typing import Any, Dict, List, Optional

from app.core.blocks import BlockBase

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "ge": operator.ge,
    "lt": operator.lt,
    "le": operator.le,
    "contains": lambda a, b: b in a if isinstance(a, (str, list, dict)) else False,
    "not_contains": lambda a, b: b not in a if isinstance(a, (str, list, dict)) else True,
    "is_empty": lambda a, _: not a,
    "is_not_empty": lambda a, _: bool(a),
    "starts_with": lambda a, b: str(a).startswith(str(b)),
    "ends_with": lambda a, b: str(a).endswith(str(b)),
    "regex": lambda a, b: bool(__import__("re").search(str(b), str(a))),
}


def _resolve_path(data: Any, path: str) -> Any:
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


def _evaluate_condition(condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """Evaluate a single condition dict: {field, operator, value}."""
    field = str(condition.get("field") or "")
    op_name = str(condition.get("operator") or "eq")
    expected = condition.get("value")

    actual = _resolve_path(context, field) if "." in field else context.get(field)

    op_fn = _OPS.get(op_name, operator.eq)
    try:
        return bool(op_fn(actual, expected))
    except Exception:
        return False


# ------------------------------------------------------------------
# IF Block — conditional branching
# ------------------------------------------------------------------

class IfBlock(BlockBase):
    """Evaluate conditions and signal which branch to follow.

    Output ``_route`` is either ``"true"`` or ``"false"``.
    The FlowExecutor uses ``_route`` to decide which downstream edge
    to activate when the edge carries a ``branch`` label.
    """

    DESCRIPTION = "Conditional branch: evaluates conditions and routes to true/false path."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {"type": "string"},
                        "value": {},
                    },
                },
                "description": "List of conditions – all must pass (AND logic).",
            },
            "combine": {
                "type": "string",
                "enum": ["and", "or"],
                "description": "How to combine conditions. Default: and.",
            },
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "_route": {"type": "string", "enum": ["true", "false"]},
            "result": {"type": "boolean"},
        },
        "required": ["_route", "result"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        conditions: List[Dict[str, Any]] = inputs.get("conditions") or self._params.get("conditions") or []
        combine = str(inputs.get("combine") or self._params.get("combine") or "and").lower()

        if not conditions:
            return {"_route": "true", "result": True}

        results = [_evaluate_condition(c, context) for c in conditions]
        passed = all(results) if combine == "and" else any(results)
        return {"_route": "true" if passed else "false", "result": passed}


# ------------------------------------------------------------------
# Switch Block — multi-branch routing
# ------------------------------------------------------------------

class SwitchBlock(BlockBase):
    """Route to one of N named outputs based on value matching.

    Output ``_route`` is the matched case name or ``"default"``.
    """

    DESCRIPTION = "Multi-way switch: routes to a named branch based on value matching."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "value": {"description": "The value to match against cases."},
            "cases": {
                "type": "object",
                "additionalProperties": {},
                "description": "Map of case_name → expected value.",
            },
        },
        "required": ["value", "cases"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "_route": {"type": "string"},
            "matched_case": {"type": "string"},
            "input_value": {},
        },
        "required": ["_route"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        value = inputs.get("value")
        cases: Dict[str, Any] = inputs.get("cases") or self._params.get("cases") or {}

        for case_name, expected in cases.items():
            if value == expected:
                return {"_route": case_name, "matched_case": case_name, "input_value": value}

        return {"_route": "default", "matched_case": "default", "input_value": value}


# ------------------------------------------------------------------
# Loop Block — iterate over an array
# ------------------------------------------------------------------

class LoopBlock(BlockBase):
    """Iterate over an array, emitting each item sequentially.

    Returns aggregated items processed during iteration.
    """

    DESCRIPTION = "Loop over an array and emit each item for downstream processing."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "description": "Array to iterate over."},
            "batch_size": {"type": "integer", "description": "Process N items at a time (default: 1)."},
        },
        "required": ["items"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {"type": "array"},
            "total_count": {"type": "integer"},
            "current_item": {},
            "current_index": {"type": "integer"},
            "_loop_items": {"type": "array"},
        },
        "required": ["items", "total_count"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        items = inputs.get("items") or []
        batch_size = max(1, int(inputs.get("batch_size") or self._params.get("batch_size") or 1))

        if not isinstance(items, list):
            items = [items]

        batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

        return {
            "items": items,
            "total_count": len(items),
            "current_item": items[0] if items else None,
            "current_index": 0,
            "_loop_items": batches if batch_size > 1 else items,
        }


# ------------------------------------------------------------------
# Merge Block — combine branches
# ------------------------------------------------------------------

class MergeBlock(BlockBase):
    """Combine data from multiple upstream branches into a single output."""

    DESCRIPTION = "Merge data from multiple branches into one output."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["append", "merge", "choose_first"],
                "description": "How to combine inputs. Default: merge.",
            },
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "merged": {},
        },
        "required": ["merged"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        mode = str(inputs.pop("mode", None) or self._params.get("mode") or "merge")
        data = {k: v for k, v in inputs.items() if not k.startswith("_")}

        if mode == "append":
            merged: List[Any] = []
            for v in data.values():
                if isinstance(v, list):
                    merged.extend(v)
                else:
                    merged.append(v)
            return {"merged": merged}

        if mode == "choose_first":
            first = next(iter(data.values()), None)
            return {"merged": first}

        # Default: merge all dicts, keep non-dicts under their key
        result: Dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                result.update(v)
            else:
                result[k] = v
        return {"merged": result}


# ------------------------------------------------------------------
# Set Block — set / transform values
# ------------------------------------------------------------------

class SetBlock(BlockBase):
    """Set explicit key-value pairs into the context."""

    DESCRIPTION = "Set or transform values in the execution context."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "values": {
                "type": "object",
                "description": "Key-value pairs to set in context.",
            },
        },
        "required": ["values"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "additionalProperties": True,
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        values = inputs.get("values") or self._params.get("values") or {}
        if not isinstance(values, dict):
            return {}
        return dict(values)


# ------------------------------------------------------------------
# Filter Block — filter array items
# ------------------------------------------------------------------

class FilterBlock(BlockBase):
    """Filter an array of items based on conditions."""

    DESCRIPTION = "Filter array items by conditions, returning only matching items."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "description": "Array to filter."},
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {"type": "string"},
                        "value": {},
                    },
                },
            },
            "combine": {"type": "string", "enum": ["and", "or"]},
        },
        "required": ["items"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {"type": "array"},
            "count": {"type": "integer"},
            "filtered_out": {"type": "integer"},
        },
        "required": ["items", "count"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        items = inputs.get("items") or []
        conditions = inputs.get("conditions") or self._params.get("conditions") or []
        combine = str(inputs.get("combine") or self._params.get("combine") or "and").lower()

        if not conditions or not isinstance(items, list):
            return {"items": items, "count": len(items) if isinstance(items, list) else 0, "filtered_out": 0}

        kept: List[Any] = []
        for item in items:
            item_ctx = item if isinstance(item, dict) else {"value": item}
            results = [_evaluate_condition(c, item_ctx) for c in conditions]
            passed = all(results) if combine == "and" else any(results)
            if passed:
                kept.append(item)

        return {"items": kept, "count": len(kept), "filtered_out": len(items) - len(kept)}


# ------------------------------------------------------------------
# Wait Block — delay execution
# ------------------------------------------------------------------

class WaitBlock(BlockBase):
    """Pause execution for a specified duration."""

    DESCRIPTION = "Wait/delay execution for a specified number of seconds."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "description": "Seconds to wait (max 300)."},
        },
        "required": ["seconds"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "waited_seconds": {"type": "number"},
        },
        "required": ["waited_seconds"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        seconds = float(inputs.get("seconds") or self._params.get("seconds") or 0)
        seconds = max(0, min(seconds, 300))  # Cap at 5 minutes
        if seconds > 0:
            await asyncio.sleep(seconds)
        return {"waited_seconds": seconds}


# ------------------------------------------------------------------
# NoOp / Passthrough Block
# ------------------------------------------------------------------

class NoOpBlock(BlockBase):
    """Passthrough node — forwards all inputs unchanged."""

    DESCRIPTION = "Passthrough: forwards all inputs unchanged."
    INPUT_SCHEMA = {"type": "object", "additionalProperties": True}
    OUTPUT_SCHEMA = {"type": "object", "additionalProperties": True}

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        return dict(inputs)
