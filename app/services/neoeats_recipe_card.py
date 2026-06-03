from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.core.neoeats_blocks import NeoEatsRecipeCompileStrictBlock
from app.models.neoeats_recipe_card import RecipeCardV1


DEFAULT_STAPLES_ALLOWLIST: List[str] = ["salt", "pepper", "water", "olive oil", "vegetable oil", "butter"]
SPICE_LIKE_TOKENS: set[str] = {
    "salt",
    "pepper",
    "chili",
    "chilli",
    "paprika",
    "cumin",
    "oregano",
    "basil",
    "parsley",
    "thyme",
    "rosemary",
    "coriander",
    "turmeric",
    "cinnamon",
}
CORE_INGREDIENT_TOKENS: set[str] = {
    "chicken",
    "turkey",
    "beef",
    "fish",
    "salmon",
    "egg",
    "rice",
    "pasta",
    "potato",
    "tomato",
    "milk",
    "cream",
    "yogurt",
    "cheese",
    "onion",
    "garlic",
}
VEGETABLE_TOKENS: set[str] = {
    "tomato",
    "onion",
    "garlic",
    "spinach",
    "broccoli",
    "pepper",
    "carrot",
    "cucumber",
    "lettuce",
    "zucchini",
}
HEAVY_FAT_TOKENS: set[str] = {"butter", "cheese", "cream"}
MEANINGLESS_UNITS: set[str] = {"", "unit", "units", "portion", "serving", "to taste"}
MOJIBAKE_MARKERS: tuple[str, ...] = ("вЂ", "â€™", "â€œ", "â€", "Â ")
MISSING_PRICE_TABLE_NOK: Dict[str, float] = {
    "egg": 3.5,
    "milk": 2.8,
    "butter": 3.2,
    "flour": 1.4,
    "rice": 1.2,
    "pasta": 1.5,
    "chicken": 4.0,
    "tomato": 2.3,
    "onion": 1.3,
    "garlic": 0.9,
    "spinach": 2.4,
    "cheese": 3.8,
    "oil": 2.0,
    "olive oil": 2.8,
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _looks_core_ingredient(name: str) -> bool:
    lowered = _clean_text(name)
    return any(token in lowered for token in CORE_INGREDIENT_TOKENS)


def _is_spice_like(name: str) -> bool:
    lowered = _clean_text(name)
    return any(token in lowered for token in SPICE_LIKE_TOKENS)


def _ingredient_bucket(name: str) -> str:
    lowered = _clean_text(name)
    if any(token in lowered for token in ("milk", "oil", "vinegar", "soy sauce", "broth", "water", "sauce")):
        return "liquid"
    if any(token in lowered for token in ("butter", "cheese")):
        return "fat_solid"
    if "garlic" in lowered:
        return "garlic"
    if any(token in lowered for token in ("tomato", "onion")):
        return "produce_pcs"
    if any(token in lowered for token in ("rice", "pasta")):
        return "starch"
    if _is_spice_like(lowered):
        return "spice"
    return "generic"


def _normalize_unit_text(value: Any) -> str:
    unit = _clean_text(value)
    if unit in {"pc", "piece", "pieces"}:
        return "pcs"
    if unit in {"clove", "cloves"}:
        return "cloves"
    if unit in {"grams", "gram"}:
        return "g"
    if unit in {"milliliter", "milliliters", "millilitre", "millilitres"}:
        return "ml"
    if unit in {"liter", "liters", "litre", "litres"}:
        return "l"
    if unit in {"tablespoon", "tablespoons"}:
        return "tbsp"
    if unit in {"teaspoon", "teaspoons"}:
        return "tsp"
    return unit


def _is_meaningless_unit(value: Any) -> bool:
    return _normalize_unit_text(value) in MEANINGLESS_UNITS


def _is_unit_allowed_for_bucket(bucket: str, unit: str) -> bool:
    normalized = _normalize_unit_text(unit)
    if bucket == "liquid":
        return normalized in {"ml", "l", "tbsp", "tsp", "cup"}
    if bucket == "fat_solid":
        return normalized in {"g", "kg", "ml", "tbsp", "tsp"}
    if bucket == "produce_pcs":
        return normalized in {"pcs", "g", "kg"}
    if bucket == "garlic":
        return normalized in {"cloves", "pcs", "g"}
    if bucket == "starch":
        return normalized in {"g", "kg"}
    if bucket == "spice":
        return normalized in {"tsp", "tbsp", "g", "ml"}
    return normalized not in MEANINGLESS_UNITS


def _preferred_unit_for_bucket(bucket: str) -> str:
    if bucket == "liquid":
        return "ml"
    if bucket == "fat_solid":
        return "g"
    if bucket == "produce_pcs":
        return "pcs"
    if bucket == "garlic":
        return "cloves"
    if bucket == "starch":
        return "g"
    if bucket == "spice":
        return "tsp"
    return "g"


def _parse_iso_date(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.fromisoformat(f"{raw}T00:00:00+00:00")
        except Exception:
            return None


def _days_to_expiry(value: Any) -> Optional[int]:
    dt = _parse_iso_date(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta_seconds = (dt - now).total_seconds()
    days = int((delta_seconds + 86399) // 86400)
    return days


def _parse_quantity(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        if parsed > 0:
            return round(parsed, 2)
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    return round(default, 2)


def _parse_quantity_with_flag(value: Any, default: float) -> tuple[float, bool]:
    try:
        parsed = float(value)
        if parsed > 0:
            return round(parsed, 2), False
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    return round(default, 2), True


def _parse_servings_hint(value: Any, default: int = 2) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    return max(1, min(12, parsed))


def _default_quantity_unit(name: str, servings: int = 2) -> tuple[float, str]:
    servings = max(1, min(8, int(servings or 2)))
    lowered = _clean_text(name)
    if any(token in lowered for token in ("chicken", "turkey", "beef", "fish", "salmon")):
        return round(190.0 * servings, 2), "g"
    if "egg" in lowered:
        return float(max(1, servings * 2)), "pcs"
    if any(token in lowered for token in ("rice", "pasta")):
        return round(80.0 * servings, 2), "g"
    if "potato" in lowered:
        return round(180.0 * servings, 2), "g"
    if "milk" in lowered or "cream" in lowered or "yogurt" in lowered:
        return round(140.0 * servings, 2), "ml"
    if "tomato" in lowered:
        return round(1.5 * servings, 2), "pcs"
    if "onion" in lowered:
        return round(max(1.0, servings / 2.0), 2), "pcs"
    if "garlic" in lowered:
        return float(max(1, servings)), "cloves"
    if "cheese" in lowered:
        return round(45.0 * servings, 2), "g"
    if any(token in lowered for token in ("oil", "milk", "water", "broth", "sauce")):
        return 120.0, "ml"
    if any(token in lowered for token in ("salt", "pepper", "spice", "herb")):
        return 1.0, "tsp"
    return 120.0, "g"


def _staples_allowlist() -> List[str]:
    raw = os.getenv("SEED_NEOEATS_STAPLES_ALLOWLIST")
    if not raw:
        return list(DEFAULT_STAPLES_ALLOWLIST)
    parsed = [_clean_text(item) for item in raw.split(",")]
    filtered = [item for item in parsed if item]
    return filtered or list(DEFAULT_STAPLES_ALLOWLIST)


def _staples_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for staple in _staples_allowlist():
        qty, unit = _default_quantity_unit(staple, servings=2)
        rows.append({"name": staple, "quantity": qty, "unit": unit})
    return rows


def _redacted_snippet(value: str, max_len: int = 160) -> str:
    snippet = value[:max_len]
    snippet = re.sub(r"[A-Za-z0-9_\-]{24,}", "<redacted>", snippet)
    return repr(snippet)


def _encoding_debug_enabled() -> bool:
    return os.getenv("SEED_ENV", "").strip().lower() == "development" and os.getenv(
        "SEED_NEOEATS_ENCODING_DEBUG", "0"
    ).strip() == "1"


def _repair_mojibake_text(value: Any, *, field_name: str) -> tuple[str, bool]:
    text = str(value or "")
    if not text:
        return "", False
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text, False
    repaired = text
    for source_encoding in ("latin-1", "cp1251"):
        try:
            candidate = text.encode(source_encoding).decode("utf-8")
        except Exception:
            continue
        if candidate and "\ufffd" not in candidate:
            repaired = candidate
            break
    if repaired == text:
        return text, False
    if _encoding_debug_enabled():
        logging.info(
            "neoeats_encoding_repair field=%s before=%s after=%s",
            field_name,
            _redacted_snippet(text),
            _redacted_snippet(repaired),
        )
    return repaired, True


@lru_cache(maxsize=1)
def _nutrition_indexes() -> tuple[Dict[str, Dict[str, float]], Dict[str, str]]:
    table_path = Path(__file__).resolve().parents[1] / "catalog" / "domains" / "neoeats" / "nutrition_table_v0.json"
    try:
        payload = json.loads(table_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {}, {}
    index: Dict[str, Dict[str, float]] = {}
    aliases: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"))
        if not name:
            continue
        profile = {
            "kcal_per_100g": float(row.get("kcal_per_100g") or 0.0),
            "protein_g": float(row.get("protein_g") or 0.0),
            "fat_g": float(row.get("fat_g") or 0.0),
            "carbs_g": float(row.get("carbs_g") or 0.0),
        }
        index[name] = profile
        aliases[name] = name
        for alias in row.get("aliases") or []:
            alias_key = _clean_text(alias)
            if alias_key and alias_key not in aliases:
                aliases[alias_key] = name
    return index, aliases


def _nutrition_profile_for_name(name: str, index: Dict[str, Dict[str, float]], aliases: Dict[str, str]) -> Dict[str, float]:
    key = _clean_text(name)
    if not key:
        return {"kcal_per_100g": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0}
    canonical = aliases.get(key, key)
    profile = index.get(canonical)
    if profile:
        return profile
    for alias_key, canonical_name in aliases.items():
        if alias_key and alias_key in key:
            candidate = index.get(canonical_name)
            if candidate:
                return candidate
    return {"kcal_per_100g": 160.0, "protein_g": 8.0, "fat_g": 6.0, "carbs_g": 12.0}


def _estimate_grams(name: str, quantity: float, unit: str) -> float:
    qty = max(0.0, float(quantity))
    unit_norm = _normalize_unit_text(unit)
    if unit_norm == "g":
        return qty
    if unit_norm in {"kg"}:
        return qty * 1000.0
    if unit_norm == "ml":
        return qty
    if unit_norm in {"l"}:
        return qty * 1000.0
    if unit_norm in {"tsp"}:
        return qty * 5.0
    if unit_norm in {"tbsp"}:
        return qty * 15.0
    if unit_norm in {"cup", "cups"}:
        return qty * 240.0
    if unit_norm in {"cloves", "clove"}:
        return qty * 5.0
    if unit_norm in {"pcs"}:
        lowered = _clean_text(name)
        if "egg" in lowered:
            return qty * 50.0
        if "onion" in lowered:
            return qty * 110.0
        if "tomato" in lowered:
            return qty * 120.0
        if "garlic" in lowered:
            return qty * 5.0
        if "potato" in lowered:
            return qty * 170.0
        return qty * 100.0
    return qty


def _build_protein_badge(
    *,
    ingredients: List[Dict[str, Any]],
    protein_g_per_serving: float,
) -> Optional[Dict[str, Any]]:
    if protein_g_per_serving >= 30:
        label = "High Protein"
    elif protein_g_per_serving >= 20:
        label = "Protein Focus"
    else:
        return None

    index, aliases = _nutrition_indexes()
    source_rows: List[tuple[float, Dict[str, Any]]] = []
    for row in ingredients:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        qty = float(row.get("quantity") or 0.0)
        unit = str(row.get("unit") or "")
        grams = _estimate_grams(name, qty, unit)
        if grams <= 0:
            continue
        profile = _nutrition_profile_for_name(name, index, aliases)
        protein_per_100g = float(profile.get("protein_g") or 0.0)
        if protein_per_100g <= 0:
            continue
        protein_contrib = (protein_per_100g * grams) / 100.0
        if protein_contrib <= 0:
            continue
        source_rows.append(
            (
                protein_contrib,
                {
                    "name": _clean_text(name),
                    "approx_protein_per_100g": round(protein_per_100g, 1),
                    "used_qty_g": round(grams, 1),
                },
            )
        )
    source_rows.sort(key=lambda item: item[0], reverse=True)
    main_sources = [row for _, row in source_rows[:3]]
    score_0_100 = int(max(0, min(100, round((protein_g_per_serving / 40.0) * 100))))
    return {
        "label": label,
        "protein_g_per_serving": round(protein_g_per_serving, 1),
        "main_sources": main_sources,
        "score_0_100": score_0_100,
    }


def _estimate_missing_cost_nok(name: str, quantity: float, unit: str) -> Optional[float]:
    normalized = _clean_text(name)
    if not normalized:
        return None
    price_per_unit = MISSING_PRICE_TABLE_NOK.get(normalized)
    if price_per_unit is None:
        for key, value in MISSING_PRICE_TABLE_NOK.items():
            if key in normalized:
                price_per_unit = value
                break
    if price_per_unit is None:
        return None

    qty = max(0.0, float(quantity))
    unit_norm = _clean_text(unit)
    if unit_norm in {"kg", "kilogram", "kilograms"}:
        factor = qty
    elif unit_norm in {"g", "gram", "grams"}:
        factor = qty / 1000.0
    elif unit_norm in {"ml", "milliliter", "milliliters"}:
        factor = qty / 1000.0
    elif unit_norm in {"l", "liter", "liters"}:
        factor = qty
    elif unit_norm in {"pcs", "piece", "pieces"}:
        factor = qty
    elif unit_norm in {"tsp", "tbsp"}:
        factor = max(1.0, qty / 3.0)
    else:
        factor = max(1.0, qty / 500.0)
    return round(max(0.0, price_per_unit * max(0.5, factor)), 2)


def _extract_budget_limit_nok(constraints: Dict[str, Any]) -> Optional[float]:
    if not isinstance(constraints, dict):
        return None
    for key in ("budget_limit_nok", "budget_nok", "max_budget_nok", "budget_limit", "budget"):
        value = constraints.get(key)
        if value in (None, ""):
            continue
        try:
            parsed = float(value)
            if parsed > 0:
                return round(parsed, 2)
        except Exception:
            match = re.search(r"(\d+(?:\.\d+)?)", str(value))
            if match:
                parsed = float(match.group(1))
                if parsed > 0:
                    return round(parsed, 2)
    return None


def _build_health_budget_scores(
    *,
    ingredients: List[Dict[str, Any]],
    nutrition: Dict[str, Any],
    missing_cost_nok: Optional[float],
    constraints: Dict[str, Any],
) -> tuple[int, int]:
    servings = _parse_servings_hint(constraints.get("servings"), default=2)
    protein_per_serving = float(nutrition.get("protein_g_per_serving") or 0.0)
    fat_total = float(nutrition.get("fat_g") or 0.0)
    fat_per_serving = fat_total / float(max(1, servings))

    veg_hits = 0
    heavy_fat_hits = 0
    for row in ingredients:
        name = _clean_text(row.get("name"))
        if not name:
            continue
        if any(token in name for token in VEGETABLE_TOKENS):
            veg_hits += 1
        if any(token in name for token in HEAVY_FAT_TOKENS):
            heavy_fat_hits += 1

    health_score = 40.0
    health_score += min(34.0, protein_per_serving * 1.2)
    health_score += min(20.0, veg_hits * 5.0)
    if fat_per_serving > 18.0:
        health_score -= min(28.0, (fat_per_serving - 18.0) * 1.3)
    health_score -= min(18.0, heavy_fat_hits * 6.0)

    health_focus = any(
        token in _clean_text(constraints.get("goal") or "")
        for token in ("healthy", "health", "light", "high protein", "protein")
    ) or bool(constraints.get("prefer_healthy"))
    if health_focus:
        health_score += 6.0

    budget_limit = _extract_budget_limit_nok(constraints)
    if budget_limit is None:
        budget_score = 75.0
    elif missing_cost_nok is None:
        budget_score = 35.0
    elif missing_cost_nok <= budget_limit:
        utilization = 0.0 if budget_limit <= 0 else missing_cost_nok / budget_limit
        budget_score = max(70.0, 100.0 - utilization * 25.0)
    else:
        overrun = missing_cost_nok - budget_limit
        budget_score = max(0.0, 35.0 - overrun * 1.2)

    return int(max(0, min(100, round(health_score)))), int(max(0, min(100, round(budget_score))))


def _step_duration_seconds(step_text: str) -> int:
    text = _clean_text(step_text)
    minutes_match = re.search(r"(\d{1,2})\s*(min|mins|minute|minutes)", text)
    if minutes_match:
        return max(30, int(minutes_match.group(1)) * 60)
    if any(token in text for token in ("simmer", "bake", "roast", "boil")):
        return 8 * 60
    if any(token in text for token in ("prep", "chop", "slice", "mix")):
        return 4 * 60
    if any(token in text for token in ("serve", "plate", "garnish")):
        return 2 * 60
    return 5 * 60


def _step_title(step_text: str, index: int) -> str:
    text = str(step_text or "").strip()
    if not text:
        return f"Step {index + 1}"
    normalized = re.sub(r"^\d+[\).\s-]*", "", text).strip()
    title = normalized[:48].strip()
    if not title:
        return f"Step {index + 1}"
    if len(title) < len(normalized):
        title = title.rsplit(" ", 1)[0] or title
    return title[0].upper() + title[1:]


def _step_ingredient_refs(step_text: str, ingredients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    text = _clean_text(step_text)
    refs: List[Dict[str, Any]] = []
    for row in ingredients:
        name = _clean_text(row.get("name"))
        if not name:
            continue
        tokens = [name] + [part for part in name.split(" ") if len(part) > 3]
        if any(token and token in text for token in tokens):
            refs.append(
                {
                    "name": str(row.get("name")),
                    "quantity": float(row.get("quantity") or 0.0),
                    "unit": str(row.get("unit") or ""),
                }
            )
    return refs[:5]


def _split_steps(raw_steps: List[Any], *, fallback_ingredients: List[Dict[str, Any]]) -> List[str]:
    normalized = [str(step).strip() for step in raw_steps if str(step).strip()]
    if len(normalized) >= 3:
        return normalized[:8]
    if len(normalized) == 1:
        parts = [segment.strip() for segment in re.split(r"[.;]\s+", normalized[0]) if segment.strip()]
        if len(parts) >= 3:
            return parts[:8]

    ingredient_names = [str(row.get("name")) for row in fallback_ingredients if str(row.get("name") or "").strip()]
    lead = ingredient_names[0] if ingredient_names else "ingredients"
    follow = ingredient_names[1] if len(ingredient_names) > 1 else lead
    return [
        f"Prep {lead} and {follow}: wash, trim, and measure all ingredients.",
        "Heat pan to medium and cook proteins or base ingredients first.",
        "Add remaining ingredients in measured quantities and cook until tender.",
        "Taste, adjust seasoning, and serve warm.",
    ]


def _generate_step_tips(step_text: str, refs: List[Dict[str, Any]], step_index: int) -> List[str]:
    """Generate contextual cooking tips based on step content and ingredients."""
    tips: List[str] = []
    lowered = step_text.lower()

    # Temperature / heat tips
    if any(w in lowered for w in ["high heat", "sear", "stir-fry", "wok"]):
        tips.append("Ensure the pan is smoking hot before adding oil for a proper sear.")
    elif any(w in lowered for w in ["medium heat", "saute", "sauté"]):
        tips.append("Medium heat prevents burning while allowing even cooking.")
    elif any(w in lowered for w in ["low heat", "simmer", "slow cook"]):
        tips.append("Low and slow develops deeper flavors. Keep the lid slightly ajar.")

    # Technique tips
    if any(w in lowered for w in ["chop", "dice", "mince", "slice", "cut"]):
        tips.append("Keep your fingers curled (claw grip) for safe knife work.")
    if any(w in lowered for w in ["boil", "blanch"]):
        tips.append("Salt your water generously — it should taste like the sea.")
    if any(w in lowered for w in ["bake", "roast", "oven"]):
        tips.append("Preheat oven fully before placing food inside for even cooking.")
    if any(w in lowered for w in ["marinate", "marinade"]):
        tips.append("Pat proteins dry before marinating for better absorption.")
    if "rest" in lowered and any(w in lowered for w in ["meat", "steak", "chicken"]):
        tips.append("Resting meat allows juices to redistribute — don't skip this step.")

    # Ingredient-specific tips
    ref_names = [str(r.get("name", "")).lower() for r in refs]
    if any("garlic" in n for n in ref_names):
        tips.append("Add garlic last in the pan — it burns quickly at high heat.")
    if any("onion" in n for n in ref_names):
        tips.append("Cook onions until translucent (3-4 min) for the best flavor base.")
    if any(n in ("egg", "eggs") for n in ref_names):
        tips.append("Remove eggs from heat just before they look done — carryover heat finishes them.")
    if any("pasta" in n or "spaghetti" in n for n in ref_names):
        tips.append("Save a cup of pasta water before draining — it's liquid gold for sauces.")
    if any("rice" in n for n in ref_names):
        tips.append("Don't lift the lid while rice steams — let it absorb fully.")

    # Seasoning tips
    if any(w in lowered for w in ["season", "salt", "pepper", "spice"]):
        tips.append("Season in layers throughout cooking, not just at the end.")
    if "taste" in lowered or "adjust" in lowered:
        tips.append("Trust your palate — taste and adjust before plating.")

    # General position tips
    if step_index == 0 and not tips:
        tips.append("Read through all steps before starting. Mise en place saves time.")

    return tips[:2]


def _build_cooking_plan_v1(
    *,
    compiled_recipe: Dict[str, Any],
    ingredients: List[Dict[str, Any]],
    servings: int,
    warnings: List[str],
) -> Dict[str, Any]:
    raw_steps = compiled_recipe.get("steps") if isinstance(compiled_recipe.get("steps"), list) else []
    step_texts = _split_steps(raw_steps, fallback_ingredients=ingredients)
    steps: List[Dict[str, Any]] = []
    for index, step_text in enumerate(step_texts):
        duration_sec = _step_duration_seconds(step_text)
        refs = _step_ingredient_refs(step_text, ingredients)
        timer_rows = [{"label": f"Step {index + 1} timer", "duration_sec": duration_sec}] if duration_sec >= 120 else []
        tips = _generate_step_tips(step_text, refs, index)
        steps.append(
            {
                "step_id": f"s{index + 1}",
                "title": _step_title(step_text, index),
                "instruction": str(step_text).strip(),
                "duration_sec": duration_sec,
                "ingredients_used": refs,
                "timers": timer_rows,
                "tips": tips,
                "warnings": warnings[:1] if warnings and index == 0 else [],
            }
        )
    if len(steps) < 3:
        while len(steps) < 3:
            idx = len(steps)
            steps.append(
                {
                    "step_id": f"s{idx + 1}",
                    "title": f"Step {idx + 1}",
                    "instruction": "Continue cooking with measured ingredients.",
                    "duration_sec": 180,
                    "ingredients_used": [],
                    "timers": [{"label": f"Step {idx + 1} timer", "duration_sec": 180}],
                    "tips": [],
                    "warnings": [],
                }
            )
    return {
        "schema_version": "cooking_plan_v1",
        "servings": servings,
        "steps": steps[:8],
    }


def _build_match_breakdown(
    *,
    inventory_count: int,
    staple_count: int,
    missing_count: int,
    expiry_items_count: int,
    constraints: Dict[str, Any],
    nutrition_confidence: str,
    health_score: int,
    budget_score: int,
    budget_limit_nok: Optional[float],
    missing_cost_nok: Optional[float],
) -> tuple[int, Dict[str, Any]]:
    penalties: List[Dict[str, Any]] = []
    inventory_denominator = max(1, inventory_count + missing_count)
    inventory_coverage_pct = int(round((inventory_count / float(inventory_denominator)) * 100))
    expiry_priority_pct = 100 if expiry_items_count > 0 else 75

    prefs_pct = 88
    if constraints:
        prefs_pct = 94
    constraints_pct = 90
    if constraints.get("diet") or constraints.get("allergens") or constraints.get("calories_target"):
        constraints_pct = 95

    if missing_count > 0:
        penalties.append(
            {
                "code": "missing_items",
                "message": f"{missing_count} ingredient(s) missing from pantry.",
                "points": min(35, 8 + missing_count * 5),
            }
        )
    if nutrition_confidence == "low":
        penalties.append(
            {
                "code": "nutrition_low_confidence",
                "message": "Nutrition uses fallback heuristics for unknown ingredients.",
                "points": 8,
            }
        )
    if budget_limit_nok is not None and missing_cost_nok is not None and missing_cost_nok > budget_limit_nok:
        overrun = round(missing_cost_nok - budget_limit_nok, 2)
        penalties.append(
            {
                "code": "budget_exceeded",
                "message": f"Estimated missing cost exceeds budget by {overrun:g} NOK.",
                "points": min(40, int(10 + overrun * 0.5)),
            }
        )
    weighted = (
        inventory_coverage_pct * 0.35
        + expiry_priority_pct * 0.1
        + prefs_pct * 0.1
        + constraints_pct * 0.1
        + health_score * 0.2
        + budget_score * 0.15
    )
    penalty_points = sum(int(item["points"]) for item in penalties)
    overall_score = int(max(0, min(100, round(weighted - penalty_points))))
    match_pct = overall_score
    breakdown = {
        "inventory_coverage_pct": inventory_coverage_pct,
        "expiry_priority_pct": expiry_priority_pct,
        "prefs_pct": prefs_pct,
        "constraints_pct": constraints_pct,
        "health_score_0_100": health_score,
        "budget_fit_0_100": budget_score,
        "overall_score_0_100": overall_score,
        "penalties": penalties,
    }
    return match_pct, breakdown


def validate_recipe_card_v1(
    payload: Dict[str, Any],
    *,
    inventory_names: Optional[set[str]] = None,
    staples_allowlist: Optional[set[str]] = None,
) -> List[str]:
    errors: List[str] = []
    inventory_names = inventory_names or set()
    staples_allowlist = staples_allowlist or set(_staples_allowlist())
    try:
        card = RecipeCardV1.model_validate(payload)
    except ValidationError as exc:
        return [f"schema:{err.get('loc')}:{err.get('msg')}" for err in exc.errors()]

    missing_names = {_clean_text(item.name) for item in card.missing_items}
    for ingredient in card.ingredients:
        normalized_name = _clean_text(ingredient.name)
        bucket = _ingredient_bucket(normalized_name)
        if (
            _looks_core_ingredient(normalized_name)
            and ingredient.source != "missing"
            and (
                ingredient.quantity <= 0
                or _is_meaningless_unit(ingredient.unit)
                or not str(ingredient.unit).strip()
            )
        ):
            errors.append(f"core_quantity_missing:{ingredient.name}")
        if ingredient.source == "inventory" and normalized_name not in inventory_names:
            errors.append(f"inventory_source_not_found:{ingredient.name}")
        if ingredient.source == "staple" and normalized_name not in staples_allowlist:
            errors.append(f"staple_source_not_allowed:{ingredient.name}")
        if ingredient.source == "missing" and normalized_name not in missing_names:
            errors.append(f"missing_source_not_listed:{ingredient.name}")
        if bucket != "spice" and ingredient.quantity <= 0:
            errors.append(f"ingredient_quantity_missing:{ingredient.name}")
        if bucket != "spice" and "to taste" in _clean_text(ingredient.unit):
            errors.append(f"ingredient_to_taste_forbidden:{ingredient.name}")
        if not _is_unit_allowed_for_bucket(bucket, ingredient.unit):
            errors.append(f"ingredient_unit_invalid:{ingredient.name}:{ingredient.unit}")

    if not card.missing_items and (card.actions.missing_cost_nok or 0) != 0:
        errors.append("missing_cost_must_be_zero_when_no_missing_items")
    if card.missing_items and card.actions.missing_cost_nok == 0:
        errors.append("missing_cost_cannot_be_zero_when_missing_items_exist")
    if card.cooking_plan is not None:
        if len(card.cooking_plan.steps) < 3:
            errors.append("cooking_plan_min_steps")
        for step in card.cooking_plan.steps:
            if not step.step_id.strip() or not step.instruction.strip():
                errors.append("cooking_plan_step_invalid")
    return errors


def build_safe_error_recipe_card(recipe_id: str, title: str, message: str) -> Dict[str, Any]:
    payload = {
        "schema_version": "recipe_card_v1",
        "recipe_id": recipe_id,
        "title": title or "Recipe unavailable",
        "match_pct": 0,
        "match_breakdown": {
            "inventory_coverage_pct": 0,
            "expiry_priority_pct": 0,
            "prefs_pct": 0,
            "constraints_pct": 0,
            "health_score_0_100": 0,
            "budget_fit_0_100": 0,
            "overall_score_0_100": 0,
            "penalties": [
                {"code": "card_compile_error", "message": message, "points": 0},
            ],
        },
        "ingredients": [],
        "missing_items": [],
        "nutrition": {
            "kcal_total": 0,
            "protein_g_total": 0.0,
            "protein_g_per_serving": 0.0,
            "protein_g": 0.0,
            "fat_g": 0.0,
            "carbs_g": 0.0,
            "per_serving": {
                "kcal": 0,
                "protein_g": 0.0,
                "protein_g_total": 0.0,
                "protein_g_per_serving": 0.0,
                "fat_g": 0.0,
                "carbs_g": 0.0,
            },
            "estimate_confidence": "low",
        },
        "protein_badge": None,
        "cooking_plan": {
            "schema_version": "cooking_plan_v1",
            "servings": 2,
            "steps": [
                {
                    "step_id": "s1",
                    "title": "Retry",
                    "instruction": "Retry recipe generation when systems recover.",
                    "duration_sec": 60,
                    "ingredients_used": [],
                    "timers": [{"label": "Retry timer", "duration_sec": 60}],
                    "tips": [],
                    "warnings": [message],
                },
                {
                    "step_id": "s2",
                    "title": "Prepare",
                    "instruction": "Prepare available pantry ingredients with measured quantities.",
                    "duration_sec": 120,
                    "ingredients_used": [],
                    "timers": [{"label": "Prep timer", "duration_sec": 120}],
                    "tips": [],
                    "warnings": [],
                },
                {
                    "step_id": "s3",
                    "title": "Cook",
                    "instruction": "Cook and serve once a valid recipe card is available.",
                    "duration_sec": 180,
                    "ingredients_used": [],
                    "timers": [{"label": "Cook timer", "duration_sec": 180}],
                    "tips": [],
                    "warnings": [],
                },
            ],
        },
        "expiry_priority": {"used_first": [], "soonest_days": None},
        "actions": {"primary_cta": "start_cooking", "missing_cost_nok": 0.0, "missing_count": 0},
        "missing_items_count": 0,
        "missing_cost_nok": 0,
        "explain": "Recipe card is temporarily unavailable. Please retry.",
        "encoding_repaired": False,
        "flags": ["card_error"],
        "warnings": [message],
    }
    return RecipeCardV1.model_validate(payload).model_dump()


async def compile_recipe_card_v1(
    *,
    recipe: Dict[str, Any],
    normalized_inventory: List[Dict[str, Any]],
    constraints: Optional[Dict[str, Any]] = None,
    recipe_id: Optional[str] = None,
    explain: Optional[str] = None,
) -> Dict[str, Any]:
    compiler = NeoEatsRecipeCompileStrictBlock(engine=SimpleNamespace(), params={})
    compiled = await compiler.execute(
        {},
        {
            "draft_recipe": recipe,
            "normalized_inventory": normalized_inventory,
            "constraints": constraints or {},
            "pantry_staples": _staples_rows(),
        },
    )

    compiled_recipe = compiled.get("recipe") if isinstance(compiled.get("recipe"), dict) else {}
    compiled_nutrition = compiled.get("nutrition") if isinstance(compiled.get("nutrition"), dict) else {}
    raw_missing = compiled.get("missing_items") if isinstance(compiled.get("missing_items"), list) else []
    recipe_ingredients = compiled_recipe.get("ingredients") if isinstance(compiled_recipe.get("ingredients"), list) else []
    servings_hint = _parse_servings_hint(
        compiled_recipe.get("servings") or (constraints or {}).get("servings") or recipe.get("servings") or 2
    )

    inventory_lookup: Dict[str, Dict[str, Any]] = {}
    for row in normalized_inventory:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"))
        if not name:
            continue
        inventory_lookup.setdefault(name, row)
    staples_set = set(_staples_allowlist())

    ingredients: List[Dict[str, Any]] = []
    inventory_count = 0
    staple_count = 0
    missing_count = 0

    for row in recipe_ingredients:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"))
        if not name:
            continue
        bucket = _ingredient_bucket(name)
        preferred_unit = _preferred_unit_for_bucket(bucket)
        default_qty, default_unit = _default_quantity_unit(name, servings=servings_hint)
        if not _is_unit_allowed_for_bucket(bucket, default_unit):
            default_unit = preferred_unit
        quantity, used_default_quantity = _parse_quantity_with_flag(row.get("quantity"), default_qty)
        unit = _normalize_unit_text(row.get("unit"))
        used_default_unit = False

        source = "missing"
        expires_at = None
        days_to_expiry = None
        inventory_row = inventory_lookup.get(name)
        inventory_unit = _normalize_unit_text(inventory_row.get("unit")) if isinstance(inventory_row, dict) else ""
        if name in inventory_lookup:
            source = "inventory"
            inventory_count += 1
            raw_exp = inventory_lookup[name].get("expires_at")
            expires_at = raw_exp.isoformat() if hasattr(raw_exp, "isoformat") else (str(raw_exp) if raw_exp is not None else None)
            days_to_expiry = _days_to_expiry(expires_at)
        elif name in staples_set:
            source = "staple"
            staple_count += 1
        else:
            missing_count += 1

        if (
            _is_meaningless_unit(unit)
            or not _is_unit_allowed_for_bucket(bucket, unit)
            or (bucket != "spice" and "to taste" in _clean_text(unit))
        ):
            if inventory_unit and _is_unit_allowed_for_bucket(bucket, inventory_unit):
                unit = inventory_unit
            else:
                unit = default_unit if _is_unit_allowed_for_bucket(bucket, default_unit) else preferred_unit
            used_default_unit = True

        if bucket != "spice" and quantity <= 0:
            quantity = default_qty
            used_default_quantity = True

        ingredients.append(
            {
                "name": name,
                "quantity": quantity,
                "unit": unit,
                "source": source,
                "expires_at": expires_at,
                "days_to_expiry": days_to_expiry,
                "is_estimate": bool(used_default_quantity or used_default_unit),
            }
        )

    missing_items: List[Dict[str, Any]] = []
    for row in raw_missing:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"))
        if not name:
            continue
        bucket = _ingredient_bucket(name)
        preferred_unit = _preferred_unit_for_bucket(bucket)
        default_qty, default_unit = _default_quantity_unit(name, servings=servings_hint)
        if not _is_unit_allowed_for_bucket(bucket, default_unit):
            default_unit = preferred_unit
        quantity = _parse_quantity(row.get("suggested_qty"), default_qty)
        unit = _normalize_unit_text(row.get("unit"))
        if _is_meaningless_unit(unit) or not _is_unit_allowed_for_bucket(bucket, unit):
            unit = default_unit
        est_cost_nok = _estimate_missing_cost_nok(name, quantity, unit)
        missing_items.append(
            {
                "name": name,
                "suggested_quantity": quantity,
                "unit": unit,
                "est_cost_nok": est_cost_nok,
            }
        )

    missing_names = {_clean_text(item["name"]) for item in missing_items}
    for item in list(ingredients):
        if item["source"] == "missing" and item["name"] not in missing_names:
            qty = float(item.get("quantity") or 0.0)
            bucket = _ingredient_bucket(item["name"])
            unit = _normalize_unit_text(item.get("unit")) or _preferred_unit_for_bucket(bucket)
            if not _is_unit_allowed_for_bucket(bucket, unit):
                unit = _preferred_unit_for_bucket(bucket)
            missing_items.append(
                {
                    "name": item["name"],
                    "suggested_quantity": qty,
                    "unit": unit,
                    "est_cost_nok": _estimate_missing_cost_nok(item["name"], qty, unit),
                }
            )
            missing_count += 1

    for missing in missing_items:
        exists = any(
            _clean_text(row.get("name")) == _clean_text(missing.get("name"))
            and str(row.get("source")) == "missing"
            for row in ingredients
        )
        if exists:
            continue
        missing_name = _clean_text(missing.get("name"))
        missing_bucket = _ingredient_bucket(missing_name)
        missing_unit = _normalize_unit_text(missing.get("unit")) or _preferred_unit_for_bucket(missing_bucket)
        if not _is_unit_allowed_for_bucket(missing_bucket, missing_unit):
            missing_unit = _preferred_unit_for_bucket(missing_bucket)
        ingredients.append(
            {
                "name": missing_name,
                "quantity": float(missing.get("suggested_quantity") or 0.0),
                "unit": missing_unit,
                "source": "missing",
                "expires_at": None,
                "days_to_expiry": None,
                "is_estimate": True,
            }
        )

    expiring = [
        {"name": str(item["name"]), "days_to_expiry": int(item["days_to_expiry"])}
        for item in ingredients
        if item.get("source") == "inventory" and isinstance(item.get("days_to_expiry"), int)
    ]
    expiring_sorted = sorted(expiring, key=lambda row: row["days_to_expiry"])
    used_first = expiring_sorted[:3]
    soonest_days = used_first[0]["days_to_expiry"] if used_first else None

    nutrition_confidence = str(compiled_nutrition.get("confidence") or "low").lower()
    if nutrition_confidence not in {"high", "medium", "low"}:
        nutrition_confidence = "low"
    protein_g_total = float(compiled_nutrition.get("protein_g") or 0.0)
    per_serving_payload = (
        compiled_nutrition.get("per_serving") if isinstance(compiled_nutrition.get("per_serving"), dict) else {}
    )
    protein_g_per_serving = float(per_serving_payload.get("protein_g") or 0.0)
    if protein_g_per_serving <= 0 and servings_hint > 0:
        protein_g_per_serving = protein_g_total / float(servings_hint)
    nutrition = {
        "kcal_total": int(compiled_nutrition.get("kcal_total") or 0),
        "protein_g_total": round(max(0.0, protein_g_total), 1),
        "protein_g_per_serving": round(max(0.0, protein_g_per_serving), 1),
        "protein_g": round(max(0.0, protein_g_total), 1),
        "fat_g": float(compiled_nutrition.get("fat_g") or 0.0),
        "carbs_g": float(compiled_nutrition.get("carbs_g") or 0.0),
        "per_serving": {
            **per_serving_payload,
            "protein_g": round(max(0.0, protein_g_per_serving), 1),
            "protein_g_total": round(max(0.0, protein_g_total), 1),
            "protein_g_per_serving": round(max(0.0, protein_g_per_serving), 1),
        }
        if per_serving_payload
        else {
            "kcal": round(float(compiled_nutrition.get("kcal_total") or 0) / float(servings_hint), 1),
            "protein_g": round(max(0.0, protein_g_per_serving), 1),
            "protein_g_total": round(max(0.0, protein_g_total), 1),
            "protein_g_per_serving": round(max(0.0, protein_g_per_serving), 1),
            "fat_g": round(float(compiled_nutrition.get("fat_g") or 0.0) / float(servings_hint), 1),
            "carbs_g": round(float(compiled_nutrition.get("carbs_g") or 0.0) / float(servings_hint), 1),
        },
        "estimate_confidence": nutrition_confidence,
    }
    protein_badge = _build_protein_badge(
        ingredients=ingredients,
        protein_g_per_serving=float(nutrition.get("protein_g_per_serving") or 0.0),
    )

    known_costs = [item.get("est_cost_nok") for item in missing_items if item.get("est_cost_nok") is not None]
    missing_cost_nok: Optional[float]
    if not missing_items:
        missing_cost_nok = 0.0
    elif len(known_costs) == len(missing_items):
        missing_cost_nok = round(float(sum(float(value) for value in known_costs)), 2)
    else:
        missing_cost_nok = None
    missing_cost_nok_int = int(round(missing_cost_nok)) if isinstance(missing_cost_nok, (int, float)) else None
    missing_items_count = len(missing_items)
    budget_limit_nok = _extract_budget_limit_nok(constraints or {})
    health_score, budget_score = _build_health_budget_scores(
        ingredients=ingredients,
        nutrition=nutrition,
        missing_cost_nok=missing_cost_nok,
        constraints=constraints or {},
    )

    match_pct, match_breakdown = _build_match_breakdown(
        inventory_count=inventory_count,
        staple_count=staple_count,
        missing_count=len(missing_items),
        expiry_items_count=len(used_first),
        constraints=constraints or {},
        nutrition_confidence=nutrition_confidence,
        health_score=health_score,
        budget_score=budget_score,
        budget_limit_nok=budget_limit_nok,
        missing_cost_nok=missing_cost_nok,
    )

    actions = {
        "primary_cta": (
            "start_cooking"
            if missing_items_count == 0 and (missing_cost_nok_int or 0) == 0
            else "order_missing"
        ),
        "missing_cost_nok": missing_cost_nok,
        "missing_count": missing_items_count,
    }

    flags: List[str] = []
    warnings: List[str] = []
    ingredient_names = {_clean_text(item.get("name")) for item in ingredients}
    if "tomato" in ingredient_names and ("milk" in ingredient_names or "cream" in ingredient_names):
        flags.append("curdle_risk")
        warnings.append("Tomato + dairy can curdle. Simmer tomato base before adding dairy.")
    if nutrition_confidence == "low":
        flags.append("nutrition_low_confidence")
        warnings.append("Nutrition is an estimate with limited ingredient coverage.")
    if protein_badge is not None:
        flags.append("protein_fact_based")
    if budget_limit_nok is not None and isinstance(missing_cost_nok, (int, float)) and missing_cost_nok > budget_limit_nok:
        flags.append("budget_over_limit")
        warnings.append(f"Missing cost exceeds budget limit ({budget_limit_nok:g} NOK).")
    cooking_plan = _build_cooking_plan_v1(
        compiled_recipe=compiled_recipe,
        ingredients=ingredients,
        servings=servings_hint,
        warnings=warnings,
    )

    title_raw = str(compiled_recipe.get("title") or recipe.get("recipe_name") or recipe.get("name") or "NeoEats Recipe").strip()
    explain_raw = str(
        explain
        or recipe.get("rationale_for_user")
        or recipe.get("description")
        or "Chosen from pantry inventory and constraints."
    )
    title, title_repaired = _repair_mojibake_text(title_raw, field_name="title")
    explain_text, explain_repaired = _repair_mojibake_text(explain_raw, field_name="explain")
    encoding_repaired = bool(title_repaired or explain_repaired)
    recipe_card = {
        "schema_version": "recipe_card_v1",
        "recipe_id": recipe_id or f"recipe_{abs(hash(title)) % 10000000:07d}",
        "title": title,
        "match_pct": match_pct,
        "match_breakdown": match_breakdown,
        "ingredients": ingredients,
        "missing_items": missing_items,
        "nutrition": nutrition,
        "protein_badge": protein_badge,
        "cooking_plan": cooking_plan,
        "expiry_priority": {"used_first": used_first, "soonest_days": soonest_days},
        "actions": actions,
        "missing_items_count": missing_items_count,
        "missing_cost_nok": missing_cost_nok_int,
        "explain": explain_text,
        "encoding_repaired": encoding_repaired,
        "flags": flags,
        "warnings": warnings,
    }

    validation_errors = validate_recipe_card_v1(
        recipe_card,
        inventory_names=set(inventory_lookup.keys()),
        staples_allowlist=staples_set,
    )
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    return RecipeCardV1.model_validate(recipe_card).model_dump()


def build_chat_recommendation_from_recipe_card(
    recipe_card: Dict[str, Any],
    *,
    rationale: Optional[str] = None,
    steps: Optional[List[str]] = None,
) -> Dict[str, Any]:
    ingredients = recipe_card.get("ingredients") if isinstance(recipe_card.get("ingredients"), list) else []
    missing = recipe_card.get("missing_items") if isinstance(recipe_card.get("missing_items"), list) else []
    missing_names = [str(item.get("name")) for item in missing if str(item.get("name") or "").strip()]
    available_names = [
        str(item.get("name"))
        for item in ingredients
        if str(item.get("source")) in {"inventory", "staple"} and str(item.get("name") or "").strip()
    ]
    ingredient_rows: List[Dict[str, Any]] = []
    for row in ingredients:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        quantity = float(row.get("quantity") or 0.0)
        unit = _normalize_unit_text(row.get("unit")) or "pcs"
        source = str(row.get("source") or "missing")
        amount = f"{quantity:g} {unit}".strip()
        is_estimate = bool(row.get("is_estimate"))
        if is_estimate and amount:
            amount = f"est. {amount}"
        ingredient_rows.append(
            {
                "name": name,
                "quantity": quantity,
                "unit": unit,
                "amount": amount or "1 pcs",
                "status": "missing" if source == "missing" else "owned",
                "source": source,
                "expires_at": row.get("expires_at").isoformat() if hasattr(row.get("expires_at"), "isoformat") else row.get("expires_at"),
                "days_to_expiry": row.get("days_to_expiry"),
                "is_estimate": is_estimate,
                "price_est": None,
            }
        )

    actions = recipe_card.get("actions") if isinstance(recipe_card.get("actions"), dict) else {}
    primary = str(actions.get("primary_cta") or "")
    action_rows = []
    if primary == "start_cooking":
        action_rows.append({"label": "Start Cooking Mode", "action_id": "start_cooking_mode"})
    else:
        cost = actions.get("missing_cost_nok")
        if isinstance(cost, (int, float)):
            label = f"Order Missing ({float(cost):g} NOK)"
        else:
            label = "Order Missing"
        action_rows.append({"label": label, "action_id": "add_to_cart_missing"})
        action_rows.append({"label": "Start Anyway", "action_id": "start_cooking_mode"})

    raw_description = str(rationale or recipe_card.get("explain") or "")
    cleaned_description, _ = _repair_mojibake_text(raw_description, field_name="chat_description")
    protein_badge = recipe_card.get("protein_badge") if isinstance(recipe_card.get("protein_badge"), dict) else None
    badge_label = str(protein_badge.get("label") or "").strip() if protein_badge else ""
    if not badge_label:
        badge_label = str(recipe_card.get("badge") or "").strip()
    cooking_plan = recipe_card.get("cooking_plan") if isinstance(recipe_card.get("cooking_plan"), dict) else {}
    structured_steps = [
        str(step.get("instruction")).strip()
        for step in (cooking_plan.get("steps") if isinstance(cooking_plan.get("steps"), list) else [])
        if isinstance(step, dict) and str(step.get("instruction") or "").strip()
    ]
    fallback_steps = [str(step).strip() for step in (steps or []) if str(step).strip()]
    resolved_steps = structured_steps or fallback_steps

    return {
        "recipe_id": recipe_card.get("recipe_id"),
        "name": recipe_card.get("title"),
        "recipe_name": recipe_card.get("title"),
        "description": cleaned_description,
        "rationale_for_user": cleaned_description,
        "match_score": recipe_card.get("match_pct"),
        "score": recipe_card.get("match_pct"),
        "confidence": max(0.0, min(1.0, float(recipe_card.get("match_pct") or 0) / 100.0)),
        "badge": badge_label or None,
        "protein_badge": protein_badge,
        "available_items": available_names,
        "missing_items": missing_names,
        "ingredients": ingredient_rows,
        "price_to_complete": actions.get("missing_cost_nok"),
        "price": actions.get("missing_cost_nok"),
        "currency": "NOK",
        "actions": action_rows,
        "steps": resolved_steps,
        "recipe_card_v1": recipe_card,
    }
