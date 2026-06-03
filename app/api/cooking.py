"""Cooking plan generation endpoint for NeoEats."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cooking", tags=["cooking"])

_MIN_STEP_DURATION_SEC = 60
_MAX_STEP_DURATION_SEC = 900
_DEFAULT_STEP_DURATION_SEC = 180


class CookingPlanRequest(BaseModel):
    recipe_name: str = Field(..., min_length=1, max_length=300)
    ingredients: List[Dict[str, Any]] = Field(default_factory=list)
    servings: int = Field(default=2, ge=1, le=20)


class CookingStepResponse(BaseModel):
    step_id: str
    title: str
    instruction: str
    duration_sec: int = 0
    emoji: str = ""
    ingredients_used: List[Dict[str, Any]] = Field(default_factory=list)
    timers: List[Dict[str, Any]] = Field(default_factory=list)
    tips: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class CookingPlanResponse(BaseModel):
    schema_version: str = "cooking_plan_v1"
    servings: int
    steps: List[CookingStepResponse]
    chef_note: str = ""


_PLAN_PROMPT = """\
You are a professional chef creating a DETAILED step-by-step cooking plan.

Recipe: {recipe_name}
Servings: {servings}

Available ingredients:
{ingredients_text}

Generate a cooking plan with 4-7 detailed steps. For EACH step provide:
- title: short name, for example "Prep Vegetables" or "Sear the Protein"
- emoji: optional single emoji representing this step
- instruction: detailed 2-3 sentence instruction
- duration_sec: estimated duration in seconds, 60-900
- tips: 1-2 practical cooking tips for this step
- ingredients_used: list of ingredient names used in this step

Also provide a brief chef_note, one encouraging sentence.

Respond ONLY with valid JSON matching this exact structure:
{{
  "servings": {servings},
  "chef_note": "...",
  "steps": [
    {{
      "title": "...",
      "emoji": "...",
      "instruction": "...",
      "duration_sec": 300,
      "tips": ["..."],
      "warnings": ["..."],
      "ingredients_used": ["ingredient name"]
    }}
  ]
}}
"""


def _format_ingredients(ingredients: List[Dict[str, Any]]) -> str:
    if not ingredients:
        return "No specific ingredients listed."

    lines: List[str] = []
    for ing in ingredients[:30]:
        name = _coerce_text(ing.get("name"), "unknown", max_chars=120)
        qty = _coerce_text(ing.get("quantity"), "", max_chars=24)
        unit = _coerce_text(ing.get("unit"), "", max_chars=24)
        status = _coerce_text(ing.get("status"), "", max_chars=80)
        suffix = f" ({status})" if status else ""
        if qty and unit:
            lines.append(f"- {name}: {qty} {unit}{suffix}")
        else:
            lines.append(f"- {name}{suffix}")
    return "\n".join(lines)


def _json_object_or_none(raw_json: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_plan_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from an LLM response, including fenced JSON."""
    text = str(raw_text or "").strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    parsed = _json_object_or_none(text)
    if parsed is not None:
        return parsed

    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return _json_object_or_none(json_match.group(0))
    return None


def _coerce_text(value: Any, default: str, *, max_chars: int = 500) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return default
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return default
    return text[:max_chars]


def _coerce_duration_sec(value: Any) -> int:
    try:
        duration = int(float(value))
    except (TypeError, ValueError):
        return _DEFAULT_STEP_DURATION_SEC
    return max(_MIN_STEP_DURATION_SEC, min(_MAX_STEP_DURATION_SEC, duration))


def _coerce_servings(value: Any, requested_servings: int) -> int:
    try:
        servings = int(float(value))
    except (TypeError, ValueError):
        return requested_servings
    if 1 <= servings <= 20:
        return servings
    return requested_servings


def _coerce_text_list(value: Any, *, max_items: int, max_chars: int = 220) -> List[str]:
    if isinstance(value, str):
        candidates: List[Any] = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        return []

    result: List[str] = []
    for item in candidates:
        if item is None or isinstance(item, (dict, list, tuple, set)):
            continue
        text = re.sub(r"\s+", " ", str(item)).strip()
        if text:
            result.append(text[:max_chars])
        if len(result) >= max_items:
            break
    return result


def _normalize_ingredients_used(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []

    ing_refs: List[Dict[str, Any]] = []
    for item in value[:20]:
        if isinstance(item, str):
            name = item.strip()
            if name:
                ing_refs.append({"name": name[:120], "quantity": 0, "unit": ""})
        elif isinstance(item, dict):
            ing_refs.append(
                {
                    "name": _coerce_text(item.get("name"), "ingredient", max_chars=120),
                    "quantity": item.get("quantity", 0),
                    "unit": _coerce_text(item.get("unit"), "", max_chars=24),
                }
            )
    return ing_refs


def _coerce_step_object(step: Any, idx: int) -> Optional[Dict[str, Any]]:
    if isinstance(step, dict):
        return step
    if isinstance(step, str) and step.strip():
        return {"title": f"Step {idx + 1}", "instruction": step.strip()}
    return None


def _build_fallback_plan(recipe_name: str, ingredients: List[Dict[str, Any]], servings: int) -> Dict[str, Any]:
    """Deterministic fallback when AI generation fails."""
    ing_names = [
        _coerce_text(ing.get("name"), "", max_chars=120)
        for ing in ingredients[:5]
        if isinstance(ing, dict) and _coerce_text(ing.get("name"), "", max_chars=120)
    ]
    ingredient_summary = ", ".join(ing_names) or "your ingredients"
    return {
        "servings": servings,
        "chef_note": f"Let's make a delicious {recipe_name}.",
        "steps": [
            {
                "title": "Prep Ingredients",
                "instruction": (
                    f"Wash, peel, and chop {ingredient_summary}. Set everything in separate bowls so cooking stays calm."
                ),
                "duration_sec": 300,
                "tips": [
                    "Prep everything before you turn on the heat.",
                    "Use a stable cutting board and a sharp knife.",
                ],
                "ingredients_used": ing_names[:3],
            },
            {
                "title": "Heat And Season",
                "instruction": (
                    "Heat your pan or pot over medium-high heat. Add oil, let it shimmer, then season the main "
                    "vegetables or protein."
                ),
                "duration_sec": 180,
                "tips": ["Let the pan heat before adding food for better browning."],
                "ingredients_used": ing_names[:2],
            },
            {
                "title": "Cook Main Components",
                "instruction": "Cook the main elements until tender and fragrant. Stir or turn as needed for even cooking.",
                "duration_sec": 480,
                "tips": ["Avoid overcrowding the pan; cook in batches if needed."],
                "ingredients_used": ing_names[:4],
            },
            {
                "title": "Combine And Finish",
                "instruction": "Combine the cooked components. Taste, adjust seasoning, and let the flavors settle briefly.",
                "duration_sec": 180,
                "tips": ["Always taste before serving."],
                "ingredients_used": ing_names[2:5],
            },
            {
                "title": "Plate And Serve",
                "instruction": f"Plate your {recipe_name} neatly and serve while warm.",
                "duration_sec": 120,
                "tips": ["Wipe the plate rim before serving for a cleaner presentation."],
                "ingredients_used": [],
            },
        ],
    }


def _normalize_plan_steps(plan_data: Dict[str, Any]) -> List[CookingStepResponse]:
    """Normalize LLM cooking steps into the stable public response contract."""
    steps: List[CookingStepResponse] = []
    raw_steps_value = plan_data.get("steps", [])
    raw_steps = raw_steps_value if isinstance(raw_steps_value, list) else []

    for idx, raw_step in enumerate(raw_steps[:8]):
        step = _coerce_step_object(raw_step, idx)
        if step is None:
            continue

        title = _coerce_text(step.get("title"), f"Step {idx + 1}", max_chars=90)
        duration = _coerce_duration_sec(step.get("duration_sec", _DEFAULT_STEP_DURATION_SEC))
        steps.append(
            CookingStepResponse(
                step_id=f"s{len(steps) + 1}",
                title=title,
                instruction=_coerce_text(
                    step.get("instruction"),
                    "Continue cooking with your prepared ingredients.",
                    max_chars=1200,
                ),
                duration_sec=duration,
                emoji=_coerce_text(step.get("emoji"), "", max_chars=12),
                ingredients_used=_normalize_ingredients_used(step.get("ingredients_used", [])),
                timers=[{"label": f"{title} timer", "duration_sec": duration}],
                tips=_coerce_text_list(step.get("tips", []), max_items=3),
                warnings=_coerce_text_list(step.get("warnings", []), max_items=4),
            )
        )

    while len(steps) < 3:
        idx = len(steps)
        title = f"Step {idx + 1}"
        steps.append(
            CookingStepResponse(
                step_id=f"s{idx + 1}",
                title=title,
                instruction="Continue cooking with your prepared ingredients.",
                duration_sec=_DEFAULT_STEP_DURATION_SEC,
                timers=[{"label": f"{title} timer", "duration_sec": _DEFAULT_STEP_DURATION_SEC}],
            )
        )

    return steps


@router.post("/generate-plan", response_model=CookingPlanResponse)
async def generate_cooking_plan(request: Request, body: CookingPlanRequest) -> CookingPlanResponse:
    """Generate a detailed AI cooking plan for a recipe on demand."""
    llm_engine = getattr(request.app.state, "llm_engine", None)
    prompt = _PLAN_PROMPT.format(
        recipe_name=body.recipe_name,
        servings=body.servings,
        ingredients_text=_format_ingredients(body.ingredients),
    )

    plan_data: Optional[Dict[str, Any]] = None
    if llm_engine and getattr(llm_engine, "enabled", False):
        try:
            raw = llm_engine._generate_content(
                contents=prompt,
                model_name="gemini-2.0-flash",
                generation_config={"temperature": 0.7, "maxOutputTokens": 2048},
            )
            plan_data = _parse_plan_json(raw)
            if plan_data:
                logger.info("AI cooking plan generated for '%s'", body.recipe_name)
        except Exception:
            logger.exception("AI cooking plan generation failed for '%s'", body.recipe_name)

    if not plan_data:
        plan_data = _build_fallback_plan(body.recipe_name, body.ingredients, body.servings)
        logger.info("Using fallback cooking plan for '%s'", body.recipe_name)

    return CookingPlanResponse(
        servings=_coerce_servings(plan_data.get("servings"), body.servings),
        steps=_normalize_plan_steps(plan_data),
        chef_note=_coerce_text(
            plan_data.get("chef_note"),
            f"Enjoy your {body.recipe_name}!",
            max_chars=300,
        ),
    )
