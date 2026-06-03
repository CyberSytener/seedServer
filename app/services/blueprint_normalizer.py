from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.blocks import BlockRegistry, build_default_registry

_ALLOWED_REF_ROOTS = {
    "payload",
    "request",
    "user_id",
    "persona",
    "scan_id",
}

_BLOCK_ALIASES = {
    "neoeats.input.normalize": "neoeats.input.normalize",
    "normalize_input": "neoeats.input.normalize",
    "normalize_inventory": "neoeats.input.normalize",
    "normalize_pantry": "neoeats.input.normalize",
    "neoeats.recipe.generate": "neoeats.recipe.generate",
    "generate_recipe": "neoeats.recipe.generate",
    "recipe_generate": "neoeats.recipe.generate",
    "neoeats.recipe.validate": "neoeats.recipe.validate",
    "validate_recipe": "neoeats.recipe.validate",
    "recipe_validate": "neoeats.recipe.validate",
}

_BLOCK_DEFAULT_STEP_IDS = {
    "neoeats.input.normalize": "normalize_input",
    "neoeats.recipe.generate": "generate_recipe",
    "neoeats.recipe.validate": "validate_recipe",
}


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _canonical_block_name(raw: Any) -> str:
    block = str(raw or "").strip()
    if not block:
        return ""
    return _BLOCK_ALIASES.get(block.lower(), block)


def _looks_like_reference(text: str) -> bool:
    value = text.strip()
    if not value or " " in value:
        return False
    if value in _ALLOWED_REF_ROOTS:
        return True
    if any(value.startswith(f"{root}.") for root in _ALLOWED_REF_ROOTS):
        return True
    return "." in value


def _normalize_input_value(value: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(value, dict):
        mapped = dict(value)
        if "from" not in mapped:
            source = mapped.pop("source", None)
            if _is_non_empty_str(source):
                mapped["from"] = str(source).strip()
                return mapped, "source_to_from"
            path = mapped.pop("path", None)
            if _is_non_empty_str(path):
                mapped["from"] = str(path).strip()
                return mapped, "path_to_from"
        return mapped, None

    if _is_non_empty_str(value) and _looks_like_reference(str(value)):
        return {"from": str(value).strip()}, "string_ref_to_from"
    return value, None


def _default_step_id(block_name: str, index: int) -> str:
    if block_name in _BLOCK_DEFAULT_STEP_IDS:
        return _BLOCK_DEFAULT_STEP_IDS[block_name]
    return f"step_{index + 1}"


def normalize_blueprint(
    blueprint: Any,
    *,
    registry: Optional[BlockRegistry] = None,
    allowed_blocks: Optional[Iterable[str]] = None,
    default_name: str = "draft_blueprint",
) -> Tuple[Dict[str, Any], List[str]]:
    fixes: List[str] = []
    if isinstance(blueprint, dict):
        normalized: Dict[str, Any] = deepcopy(blueprint)
    elif isinstance(blueprint, list):
        normalized = {"steps": deepcopy(blueprint)}
        fixes.append("root_wrapped_list_into_object")
    else:
        normalized = {}
        fixes.append("root_coerced_to_object")

    if allowed_blocks is None:
        active_registry = registry or build_default_registry()
        allowed_blocks_set = set(active_registry.list_blocks())
    else:
        allowed_blocks_set = {str(item) for item in allowed_blocks if _is_non_empty_str(item)}

    if not _is_non_empty_str(normalized.get("name")):
        normalized["name"] = default_name
        fixes.append("set_default_name")

    if not _is_non_empty_str(normalized.get("version")):
        normalized["version"] = "v1"
        fixes.append("set_default_version")

    raw_steps = normalized.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = []
        normalized["steps"] = raw_steps
        fixes.append("set_default_steps")

    normalized_steps: List[Dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps):
        if isinstance(raw_step, dict):
            step = deepcopy(raw_step)
        else:
            step = {}
            fixes.append(f"step[{index}]:coerced_to_object")

        step_id = str(step.get("id") or step.get("name") or "").strip()
        block_name = _canonical_block_name(step.get("block") or step.get("block_type"))

        if not block_name and step_id:
            inferred = _canonical_block_name(step_id)
            if inferred in allowed_blocks_set:
                block_name = inferred
                fixes.append(f"step[{index}]:inferred_block_from_step_id")

        if block_name and block_name not in allowed_blocks_set:
            step_label = step_id or f"step_{index + 1}"
            fixes.append(f"step[{step_label}]:unknown_block_preserved")

        if not step_id:
            step_id = _default_step_id(block_name, index)
            fixes.append(f"step[{index}]:set_default_id")

        if not block_name:
            hinted = _canonical_block_name(step_id)
            if hinted in allowed_blocks_set:
                block_name = hinted
                fixes.append(f"step[{step_id}]:canonicalized_block")

        if step.get("id") != step_id:
            fixes.append(f"step[{step_id}]:normalized_id")
        step["id"] = step_id
        step["block"] = block_name
        step.pop("name", None)
        step.pop("block_type", None)

        inputs = step.get("inputs")
        if not isinstance(inputs, dict):
            inputs = {}
            fixes.append(f"step[{step_id}]:set_default_inputs")

        normalized_inputs: Dict[str, Any] = {}
        for key, value in inputs.items():
            normalized_value, input_fix = _normalize_input_value(value)
            normalized_inputs[str(key)] = normalized_value
            if input_fix:
                fixes.append(f"step[{step_id}].inputs.{key}:{input_fix}")

        step["inputs"] = normalized_inputs
        normalized_steps.append(step)

    normalized["steps"] = normalized_steps
    return normalized, fixes
