from __future__ import annotations
import logging

import asyncio
import base64
import hashlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.gemini_client import GeminiClient

try:
    from PIL import Image
except Exception:  # noqa: BLE001
    Image = None

from app.core.blocks import BlockBase
from app.infrastructure.monitoring.monitoring.metrics import get_metrics


def _build_gemini_client(*, api_key: str, default_model: str) -> GeminiClient:
    try:
        return GeminiClient(api_key=api_key, default_model=default_model)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Gemini SDK is not available") from exc


def _require_db(engine: Any) -> Any:
    db = getattr(engine, "db", None)
    if db is None:
        raise ValueError("Database connection not available on engine")
    return db


def _invalidate_inventory_cache(engine: Any) -> None:
    adapters = getattr(engine, "adapters", {}) if engine else {}
    provider = adapters.get("inventory_provider")
    invalidate = getattr(provider, "invalidate_cache", None)
    if callable(invalidate):
        invalidate()


_DIET_ALIASES: Dict[str, str] = {
    "vegan": "vegan",
    "plant-based": "vegan",
    "plant_based": "vegan",
    "vegetarian": "vegetarian",
    "keto": "keto",
    "low_carb": "low_carb",
    "low-carb": "low_carb",
    "gluten_free": "gluten_free",
    "gluten-free": "gluten_free",
}

_ALLERGEN_ALIASES: Dict[str, str] = {
    "peanut": "peanut",
    "peanuts": "peanut",
    "nut": "tree_nut",
    "nuts": "tree_nut",
    "tree_nut": "tree_nut",
    "tree nuts": "tree_nut",
    "dairy": "dairy",
    "milk": "dairy",
    "lactose": "dairy",
    "egg": "egg",
    "eggs": "egg",
    "soy": "soy",
    "gluten": "gluten",
    "wheat": "gluten",
    "shellfish": "shellfish",
    "fish": "fish",
    "sesame": "sesame",
}

_DIET_DISALLOWED_TOKENS: Dict[str, set[str]] = {
    "vegan": {"beef", "pork", "chicken", "fish", "shrimp", "egg", "milk", "butter", "cheese", "yogurt", "honey"},
    "vegetarian": {"beef", "pork", "chicken", "fish", "shrimp"},
    "keto": {"sugar", "bread", "rice", "pasta", "potato"},
    "low_carb": {"sugar", "bread", "rice", "pasta", "potato"},
    "gluten_free": {"wheat", "flour", "bread", "pasta", "soy sauce"},
}

_CALORIE_HINTS: Dict[str, float] = {
    "egg": 78.0,
    "chicken": 165.0,
    "beef": 250.0,
    "pork": 242.0,
    "rice": 130.0,
    "pasta": 131.0,
    "potato": 77.0,
    "cheese": 402.0,
    "milk": 42.0,
    "yogurt": 63.0,
    "tofu": 76.0,
    "salmon": 208.0,
    "tuna": 132.0,
    "olive oil": 884.0,
    "oil": 884.0,
    "avocado": 160.0,
    "spinach": 23.0,
    "tomato": 18.0,
    "onion": 40.0,
    "garlic": 149.0,
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _to_unique_ingredients(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    normalized: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("ingredient") or item.get("item")
        else:
            candidate = item
        cleaned = _clean_text(candidate)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _normalize_diet(value: Any) -> Optional[str]:
    normalized = _clean_text(value).replace(" ", "_")
    if not normalized:
        return None
    return _DIET_ALIASES.get(normalized, normalized)


def _normalize_allergens(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_text(item).replace("-", "_")
        if not cleaned:
            continue
        canonical = _ALLERGEN_ALIASES.get(cleaned, cleaned)
        if canonical in seen:
            continue
        seen.add(canonical)
        result.append(canonical)
    return result


def _parse_positive_int(value: Any, *, minimum: int, maximum: int) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        parsed = int(float(value))
    except Exception:
        digits = re.findall(r"\d+", str(value or ""))
        if not digits:
            return None
        parsed = int(digits[0])
    return max(minimum, min(parsed, maximum))


def _first_token_match(haystack: str, tokens: List[str]) -> Optional[str]:
    for token in tokens:
        candidate = _clean_text(token)
        if not candidate:
            continue
        if candidate in haystack:
            return candidate
    return None


def _quantity_unit_for(name: str) -> tuple[float, str]:
    lowered = _clean_text(name)
    if any(token in lowered for token in ("oil", "milk", "broth", "water", "sauce")):
        return 120.0, "ml"
    if any(token in lowered for token in ("salt", "pepper", "spice", "herb")):
        return 1.0, "tsp"
    if any(token in lowered for token in ("egg", "eggs")):
        return 2.0, "pcs"
    return 120.0, "g"


def _estimate_recipe_calories(recipe: Dict[str, Any]) -> Optional[int]:
    ingredients = recipe.get("ingredients")
    if not isinstance(ingredients, list) or not ingredients:
        return None

    total = 0.0
    for item in ingredients:
        if isinstance(item, dict):
            name = _clean_text(item.get("name"))
            quantity_raw = item.get("quantity")
            unit = _clean_text(item.get("unit"))
        else:
            name = _clean_text(item)
            quantity_raw = 1
            unit = ""

        if not name:
            continue

        base_per_100 = 120.0
        matched = _first_token_match(name, list(_CALORIE_HINTS.keys()))
        if matched:
            base_per_100 = _CALORIE_HINTS.get(matched, base_per_100)

        try:
            quantity = float(quantity_raw or 1.0)
        except Exception:
            quantity = 1.0

        if unit in {"g", "gram", "grams", "ml"}:
            factor = max(0.2, min(quantity / 100.0, 5.0))
        elif unit in {"pcs", "piece", "pieces"}:
            factor = max(0.5, min(quantity, 6.0))
        elif unit in {"cup", "cups"}:
            factor = max(0.5, min(quantity, 4.0))
        else:
            factor = 1.0

        total += base_per_100 * factor

    if total <= 0:
        return None
    return int(round(total))


_INVENTORY_ALIAS_DEFAULTS: Dict[str, str] = {
    "tomatoes": "tomato",
    "tomatoe": "tomato",
    "chickpeas": "chickpea",
    "chick peas": "chickpea",
    "garbanzo beans": "chickpea",
    "scallions": "green onion",
    "spring onion": "green onion",
    "bell pepper": "sweet pepper",
    "capsicum": "sweet pepper",
}

_INVENTORY_STUB_BASE: List[Dict[str, Any]] = [
    {"name": "egg", "quantity": 6.0, "unit": "pcs", "expires_at": "2099-01-01"},
    {"name": "tomato", "quantity": 4.0, "unit": "pcs", "expires_at": "2099-02-01"},
    {"name": "spinach", "quantity": 220.0, "unit": "g", "expires_at": "2099-03-01"},
    {"name": "olive oil", "quantity": 380.0, "unit": "ml", "expires_at": "2099-04-01"},
    {"name": "onion", "quantity": 2.0, "unit": "pcs", "expires_at": "2099-05-01"},
    {"name": "expired milk", "quantity": 250.0, "unit": "ml", "expires_at": "2000-01-01"},
]

_NUTRITION_TABLE_CACHE: Optional[Dict[str, Any]] = None

_RECIPE_SUBSTITUTION_MAP: Dict[str, List[str]] = {
    "butter": ["olive oil", "oil"],
    "milk": ["yogurt", "water"],
    "cream": ["yogurt", "milk"],
    "cheese": ["egg", "tofu"],
    "chicken": ["egg", "tofu"],
    "beef": ["mushroom", "tofu"],
    "pasta": ["rice"],
    "rice": ["pasta"],
}

_PCS_WEIGHT_G: Dict[str, float] = {
    "egg": 50.0,
    "onion": 110.0,
    "tomato": 120.0,
    "garlic": 5.0,
    "potato": 170.0,
}

_PANTRY_STAPLES_ALLOWLIST_DEFAULT: List[str] = [
    "salt",
    "pepper",
    "water",
    "olive oil",
    "vegetable oil",
    "butter",
]


def _execution_mode_name(engine: Any, context: Dict[str, Any], inputs: Dict[str, Any]) -> str:
    mode_raw = getattr(engine, "_execution_mode", None)
    mode = str(getattr(mode_raw, "value", mode_raw) or "").upper()
    if mode:
        return mode
    request_payload = context.get("request") if isinstance(context.get("request"), dict) else {}
    hinted = request_payload.get("mode") if isinstance(request_payload, dict) else None
    if not hinted:
        hinted = inputs.get("mode")
    return str(hinted or "").upper()


def _is_stub_or_dry_run(engine: Any, context: Dict[str, Any], inputs: Dict[str, Any]) -> bool:
    return _execution_mode_name(engine, context, inputs) in {"DRY_RUN", "STUB"}


def _parse_iso_date(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
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
    return int((delta_seconds + 86399) // 86400)


def _iso_date_or_none(value: Any) -> Optional[str]:
    dt = _parse_iso_date(value)
    if dt is None:
        return None
    return dt.date().isoformat()


def _is_expired(value: Any) -> bool:
    dt = _parse_iso_date(value)
    if dt is None:
        return False
    return dt.date() < datetime.now(timezone.utc).date()


def _inventory_error(
    message: str,
    *,
    user_id: str,
    reason: str,
) -> ValueError:
    payload = {
        "error": "inventory_not_available",
        "message": message,
        "reason": reason,
        "user_id": user_id,
    }
    return ValueError(json.dumps(payload, ensure_ascii=True))


def _normalize_inventory_item(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        name = _clean_text(raw)
        if not name:
            return None
        return {
            "name": name,
            "quantity": 1.0,
            "unit": "pcs",
            "expires_at": None,
            "confidence": None,
        }

    if not isinstance(raw, dict):
        return None

    name = _clean_text(raw.get("name") or raw.get("ingredient") or raw.get("item"))
    if not name:
        return None
    try:
        quantity = float(raw.get("quantity") if raw.get("quantity") is not None else 0.0)
    except Exception:
        quantity = 0.0
    unit = _clean_text(raw.get("unit")) or "pcs"
    expires_at = _iso_date_or_none(raw.get("expires_at"))
    confidence_raw = raw.get("confidence")
    confidence: Optional[float] = None
    if confidence_raw is not None:
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = None
    return {
        "name": name,
        "quantity": max(0.0, quantity),
        "unit": unit,
        "expires_at": expires_at,
        "confidence": confidence,
    }


def _configured_staples_allowlist() -> List[str]:
    raw = os.getenv("SEED_NEOEATS_STAPLES_ALLOWLIST")
    if not raw:
        return list(_PANTRY_STAPLES_ALLOWLIST_DEFAULT)
    items = [_clean_text(item) for item in raw.split(",")]
    normalized = [item for item in items if item]
    return normalized or list(_PANTRY_STAPLES_ALLOWLIST_DEFAULT)


def _default_staples_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for staple in _configured_staples_allowlist():
        quantity, unit = _quantity_unit_for(staple)
        rows.append({"name": staple, "quantity": quantity, "unit": unit})
    return rows


def _deterministic_stub_inventory(user_id: str) -> List[Dict[str, Any]]:
    seed = hashlib.sha256(user_id.encode("utf-8")).digest()
    rows: List[Dict[str, Any]] = []
    for index, base in enumerate(_INVENTORY_STUB_BASE):
        row = dict(base)
        bump = (seed[index % len(seed)] % 4) * 0.5
        row["quantity"] = float(base["quantity"]) + bump
        confidence = 0.75 + (seed[(index + 7) % len(seed)] / 255.0) * 0.2
        row["confidence"] = round(min(0.99, max(0.5, confidence)), 3)
        rows.append(row)
    return rows


def _extract_inventory_override(context: Dict[str, Any]) -> Optional[List[Any]]:
    candidates: List[Any] = []
    request_payload = context.get("request") if isinstance(context.get("request"), dict) else {}
    payload = context.get("payload") if isinstance(context.get("payload"), dict) else {}
    for scope in (request_payload, payload):
        if not isinstance(scope, dict):
            continue
        candidates.extend(
            [
                scope.get("inventory_override"),
                scope.get("inventory"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return None


def _normalize_alias_map(raw_aliases: Any) -> Dict[str, str]:
    alias_map: Dict[str, str] = {}
    for key, value in _INVENTORY_ALIAS_DEFAULTS.items():
        alias_map[_clean_text(key)] = _clean_text(value)
    if isinstance(raw_aliases, dict):
        for key, value in raw_aliases.items():
            source = _clean_text(key)
            target = _clean_text(value)
            if not source:
                continue
            alias_map[source] = target or source
    return alias_map


def _normalize_unit_quantity(quantity: float, unit: str) -> tuple[float, str]:
    normalized_unit = _clean_text(unit)
    if normalized_unit in {"kg", "kilogram", "kilograms"}:
        return quantity * 1000.0, "g"
    if normalized_unit in {"g", "gram", "grams"}:
        return quantity, "g"
    if normalized_unit in {"l", "liter", "litre", "liters", "litres"}:
        return quantity * 1000.0, "ml"
    if normalized_unit in {"ml", "milliliter", "millilitre", "milliliters", "millilitres"}:
        return quantity, "ml"
    if normalized_unit in {"pc", "piece", "pieces"}:
        return quantity, "pcs"
    if not normalized_unit:
        return quantity, "pcs"
    return quantity, normalized_unit


def _nutrition_table_path() -> Path:
    return Path(__file__).resolve().parents[1] / "catalog" / "domains" / "neoeats" / "nutrition_table_v0.json"


def _load_nutrition_table() -> Dict[str, Any]:
    global _NUTRITION_TABLE_CACHE
    if isinstance(_NUTRITION_TABLE_CACHE, dict):
        return _NUTRITION_TABLE_CACHE
    path = _nutrition_table_path()
    if not path.exists():
        _NUTRITION_TABLE_CACHE = {"catalog_version": "v0", "items": []}
        return _NUTRITION_TABLE_CACHE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not isinstance(payload.get("items"), list):
        payload["items"] = []
    _NUTRITION_TABLE_CACHE = payload
    return payload


def _build_nutrition_index() -> tuple[Dict[str, Dict[str, float]], Dict[str, str]]:
    payload = _load_nutrition_table()
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    table: Dict[str, Dict[str, float]] = {}
    aliases: Dict[str, str] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        name = _clean_text(row.get("name"))
        if not name:
            continue
        try:
            kcal = float(row.get("kcal_per_100g") or 0.0)
            protein = float(row.get("protein_g") or 0.0)
            fat = float(row.get("fat_g") or 0.0)
            carbs = float(row.get("carbs_g") or 0.0)
        except Exception:
            continue
        table[name] = {
            "kcal_per_100g": max(0.0, kcal),
            "protein_g": max(0.0, protein),
            "fat_g": max(0.0, fat),
            "carbs_g": max(0.0, carbs),
        }
        aliases[name] = name
        alias_values = row.get("aliases") if isinstance(row.get("aliases"), list) else []
        for alias in alias_values:
            alias_key = _clean_text(alias)
            if alias_key:
                aliases[alias_key] = name
    return table, aliases


def _resolve_nutrition_name(name: str, alias_index: Dict[str, str]) -> str:
    normalized = _clean_text(name)
    if not normalized:
        return normalized
    if normalized in alias_index:
        return alias_index[normalized]
    if normalized.endswith("es") and normalized[:-2] in alias_index:
        return alias_index[normalized[:-2]]
    if normalized.endswith("s") and normalized[:-1] in alias_index:
        return alias_index[normalized[:-1]]
    return normalized


def _parse_amount_string(amount: str) -> Tuple[float, str]:
    """Parse a legacy amount string like '120g', '1 tbsp', '2 cloves' into (quantity, unit)."""
    amount = (amount or "").strip()
    if not amount or amount.lower() == "to taste":
        return (0.0, "")
    # Try "120g", "250ml", "1.5kg" (no space between number and unit)
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)$", amount)
    if m:
        try:
            qty = float(m.group(1).replace(",", "."))
        except ValueError:
            qty = 0.0
        return (qty, m.group(2).lower())
    # Try "1 tbsp", "2 cloves"
    m = re.match(r"^(\d+(?:[.,]\d+)?)\s+(.+)$", amount)
    if m:
        try:
            qty = float(m.group(1).replace(",", "."))
        except ValueError:
            qty = 0.0
        return (qty, m.group(2).strip().lower())
    # Try plain number
    try:
        return (float(amount.replace(",", ".")), "")
    except ValueError:
        return (0.0, "")


def _parse_recipe_ingredient(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        name = _clean_text(raw)
        if not name:
            return None
        quantity, unit = _quantity_unit_for(name)
        return {"name": name, "quantity": float(quantity), "unit": unit}

    if not isinstance(raw, dict):
        return None
    name = _clean_text(raw.get("name") or raw.get("ingredient") or raw.get("item"))
    if not name:
        return None
    quantity_raw = raw.get("quantity")
    try:
        quantity = float(quantity_raw) if quantity_raw is not None else 0.0
    except Exception:
        quantity = 0.0
    unit = _clean_text(raw.get("unit"))

    # Parse legacy "amount" string (e.g. "120g", "1 tbsp") from flavor architect
    if (quantity <= 0.0 or not unit) and raw.get("amount"):
        amt_qty, amt_unit = _parse_amount_string(str(raw["amount"]))
        if amt_qty > 0.0 and not quantity:
            quantity = amt_qty
        if amt_unit and not unit:
            unit = amt_unit

    if quantity <= 0.0 or not unit:
        fallback_quantity, fallback_unit = _quantity_unit_for(name)
        quantity = quantity if quantity > 0.0 else float(fallback_quantity)
        unit = unit or fallback_unit
    return {
        "name": name,
        "quantity": max(0.0, float(quantity)),
        "unit": unit or "g",
    }


def _merge_recipe_ingredients(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = _clean_text(row.get("name"))
        if not name:
            continue
        try:
            quantity = float(row.get("quantity") or 0.0)
        except Exception:
            quantity = 0.0
        quantity, unit = _normalize_unit_quantity(max(0.0, quantity), str(row.get("unit") or ""))
        key = f"{name}|{unit}"
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "name": name,
                "quantity": quantity,
                "unit": unit,
                "source": str(row.get("source") or "inventory"),
                "expires_at": row.get("expires_at"),
                "days_to_expiry": row.get("days_to_expiry"),
            }
            continue
        existing["quantity"] = float(existing.get("quantity") or 0.0) + quantity
        existing_source = str(existing.get("source") or "inventory")
        row_source = str(row.get("source") or "inventory")
        if existing_source == "staple" and row_source == "inventory":
            existing["source"] = "inventory"
        elif existing_source == "missing" and row_source in {"inventory", "staple"}:
            existing["source"] = row_source

        existing_exp = _parse_iso_date(existing.get("expires_at"))
        row_exp = _parse_iso_date(row.get("expires_at"))
        if existing_exp is None and row_exp is not None:
            existing["expires_at"] = row_exp.date().isoformat()
        elif existing_exp is not None and row_exp is not None and row_exp < existing_exp:
            existing["expires_at"] = row_exp.date().isoformat()
        existing["days_to_expiry"] = _days_to_expiry(existing.get("expires_at"))
    result = sorted(merged.values(), key=lambda item: (str(item.get("name") or ""), str(item.get("unit") or "")))
    for item in result:
        item["quantity"] = round(float(item.get("quantity") or 0.0), 2)
    return result


def _fallback_nutrition_per_100g(name: str) -> Dict[str, float]:
    lowered = _clean_text(name)
    kcal = float(_CALORIE_HINTS.get(lowered, 120.0))
    if any(token in lowered for token in ("oil", "butter")):
        return {"kcal_per_100g": kcal, "protein_g": 0.0, "fat_g": 100.0, "carbs_g": 0.0}
    if any(token in lowered for token in ("egg", "chicken", "beef", "pork", "fish", "tuna", "salmon", "tofu", "cheese")):
        return {"kcal_per_100g": kcal, "protein_g": 18.0, "fat_g": 10.0, "carbs_g": 2.0}
    if any(token in lowered for token in ("rice", "pasta", "flour", "bread", "potato")):
        return {"kcal_per_100g": kcal, "protein_g": 5.0, "fat_g": 1.5, "carbs_g": 28.0}
    return {"kcal_per_100g": kcal, "protein_g": 4.0, "fat_g": 4.0, "carbs_g": 15.0}


def _estimate_grams(name: str, quantity: float, unit: str) -> float:
    q = max(0.0, float(quantity))
    normalized_unit = _clean_text(unit)
    if normalized_unit in {"g", "gram", "grams"}:
        return q
    if normalized_unit in {"kg", "kilogram", "kilograms"}:
        return q * 1000.0
    if normalized_unit in {"ml", "milliliter", "milliliters", "millilitre", "millilitres"}:
        return q
    if normalized_unit in {"l", "liter", "liters", "litre", "litres"}:
        return q * 1000.0
    if normalized_unit in {"tsp", "teaspoon", "teaspoons"}:
        return q * 5.0
    if normalized_unit in {"tbsp", "tablespoon", "tablespoons"}:
        return q * 15.0
    if normalized_unit in {"cup", "cups"}:
        return q * 240.0
    if normalized_unit in {"pcs", "pc", "piece", "pieces"}:
        name_key = _clean_text(name)
        for token, grams in _PCS_WEIGHT_G.items():
            if token in name_key:
                return q * grams
        return q * 60.0
    return q * 100.0


def _nutrition_totals_for_ingredient(
    *,
    name: str,
    quantity: float,
    unit: str,
    nutrition_index: Dict[str, Dict[str, float]],
    alias_index: Dict[str, str],
) -> Dict[str, Any]:
    canonical = _resolve_nutrition_name(name, alias_index)
    profile = nutrition_index.get(canonical)
    used_fallback = False
    if profile is None:
        profile = _fallback_nutrition_per_100g(canonical or name)
        used_fallback = True

    grams = _estimate_grams(canonical or name, quantity, unit)
    scale = max(0.0, grams) / 100.0
    kcal = float(profile.get("kcal_per_100g") or 0.0) * scale
    protein = float(profile.get("protein_g") or 0.0) * scale
    fat = float(profile.get("fat_g") or 0.0) * scale
    carbs = float(profile.get("carbs_g") or 0.0) * scale
    return {
        "name": canonical or name,
        "grams": grams,
        "kcal": kcal,
        "protein_g": protein,
        "fat_g": fat,
        "carbs_g": carbs,
        "used_fallback": used_fallback,
    }


def _resolve_available_name(name: str, available: Dict[str, Dict[str, Any]], alias_map: Dict[str, str]) -> Optional[str]:
    candidate = _clean_text(name)
    if not candidate:
        return None
    if candidate in available:
        return candidate
    alias_candidate = alias_map.get(candidate)
    if alias_candidate and alias_candidate in available:
        return alias_candidate
    if candidate.endswith("es") and candidate[:-2] in available:
        return candidate[:-2]
    if candidate.endswith("s") and candidate[:-1] in available:
        return candidate[:-1]
    return None


def _find_substitute_name(missing: str, available: Dict[str, Dict[str, Any]]) -> Optional[str]:
    candidate = _clean_text(missing)
    if not candidate:
        return None
    direct = _RECIPE_SUBSTITUTION_MAP.get(candidate, [])
    for option in direct:
        key = _clean_text(option)
        if key in available:
            return key
    for token, options in _RECIPE_SUBSTITUTION_MAP.items():
        if token in candidate:
            for option in options:
                key = _clean_text(option)
                if key in available:
                    return key
    return None


class NeoEatsInventoryGetBlock(BlockBase):
    DESCRIPTION = "Read-only inventory fetcher for strict recipe generation (stub in safe modes, DB in live mode)."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "source": {"type": "string", "enum": ["db", "stub"]},
            "include_expired": {"type": "boolean"},
        },
        "required": ["user_id"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "inventory": {"type": "array", "items": {"type": "object"}},
            "updated_at": {"type": "string"},
        },
        "required": ["inventory"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_id = str(inputs.get("user_id") or context.get("user_id") or "anonymous").strip() or "anonymous"
        source = str(inputs.get("source") or "db").strip().lower()
        include_expired = bool(inputs.get("include_expired", False))
        safe_mode = _is_stub_or_dry_run(self._engine, context, inputs)

        if safe_mode:
            override = _extract_inventory_override(context)
            raw_rows = override if override is not None else _deterministic_stub_inventory(user_id)
            inventory = [item for item in (_normalize_inventory_item(row) for row in raw_rows) if item is not None]
            if not include_expired:
                inventory = [item for item in inventory if not _is_expired(item.get("expires_at"))]
            return {
                "inventory": inventory,
                "updated_at": "stub://inventory/v1",
            }

        if source != "db":
            raise _inventory_error(
                "LIVE execution requires source=db for inventory lookup.",
                user_id=user_id,
                reason="invalid_source_for_live",
            )

        db = getattr(self._engine, "db", None)
        if db is None:
            raise _inventory_error(
                "Database connection is not available for inventory lookup.",
                user_id=user_id,
                reason="db_missing",
            )

        try:
            rows = await db.fetch(
                """
                SELECT name, quantity, unit, expires_at, metadata, updated_at
                FROM storage_item
                WHERE (metadata->>'user_id') = $1
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
                """,
                user_id,
            )
        except Exception:
            raise _inventory_error(
                "Failed to query inventory for user.",
                user_id=user_id,
                reason="db_query_failed",
            ) from None

        inventory: List[Dict[str, Any]] = []
        updated_at: Optional[str] = None
        for row in rows or []:
            row_dict = dict(row)
            item = _normalize_inventory_item(row_dict)
            if item is None:
                continue
            metadata = row_dict.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            if isinstance(metadata, dict) and item.get("confidence") is None:
                confidence_raw = metadata.get("confidence")
                if confidence_raw is not None:
                    try:
                        item["confidence"] = float(confidence_raw)
                    except Exception:
                        item["confidence"] = None
            if not include_expired and _is_expired(item.get("expires_at")):
                continue
            inventory.append(item)
            if updated_at is None:
                row_updated = row_dict.get("updated_at")
                if isinstance(row_updated, datetime):
                    updated_at = row_updated.astimezone(timezone.utc).isoformat()
                elif row_updated is not None:
                    updated_at = str(row_updated)

        if not inventory:
            raise _inventory_error(
                "No inventory entries available for user.",
                user_id=user_id,
                reason="empty_inventory",
            )

        return {
            "inventory": inventory,
            "updated_at": updated_at,
        }


class NeoEatsInventoryNormalizeBlock(BlockBase):
    DESCRIPTION = "Normalize inventory names/units, merge duplicates, and apply alias canonicalization."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "inventory": {"type": "array", "items": {"type": "object"}},
            "pantry_staples": {"type": "array", "items": {"type": ["string", "object"]}},
            "aliases": {"type": "object"},
        },
        "required": ["inventory"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "normalized_inventory": {"type": "array", "items": {"type": "object"}},
            "alias_map": {"type": "object"},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["normalized_inventory", "alias_map", "notes"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        alias_map = _normalize_alias_map(inputs.get("aliases"))
        notes: List[str] = []
        merged: Dict[str, Dict[str, Any]] = {}
        merge_count = 0
        converted_units = 0

        raw_inventory = inputs.get("inventory") if isinstance(inputs.get("inventory"), list) else []
        for raw_item in raw_inventory:
            item = _normalize_inventory_item(raw_item)
            if item is None:
                continue
            canonical_name = alias_map.get(_clean_text(item.get("name")), _clean_text(item.get("name")))
            quantity, unit = _normalize_unit_quantity(float(item.get("quantity") or 0.0), str(item.get("unit") or ""))
            if unit != _clean_text(item.get("unit")):
                converted_units += 1
            key = f"{canonical_name}|{unit}"
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    "name": canonical_name,
                    "quantity": max(0.0, quantity),
                    "unit": unit,
                    "expires_at": _iso_date_or_none(item.get("expires_at")),
                    "confidence": item.get("confidence"),
                }
                continue

            merge_count += 1
            existing["quantity"] = float(existing.get("quantity") or 0.0) + max(0.0, quantity)
            existing_exp = _parse_iso_date(existing.get("expires_at"))
            new_exp = _parse_iso_date(item.get("expires_at"))
            if existing_exp is None and new_exp is not None:
                existing["expires_at"] = new_exp.date().isoformat()
            elif existing_exp is not None and new_exp is not None and new_exp < existing_exp:
                existing["expires_at"] = new_exp.date().isoformat()
            existing_conf = existing.get("confidence")
            new_conf = item.get("confidence")
            if existing_conf is None:
                existing["confidence"] = new_conf
            elif new_conf is not None:
                existing["confidence"] = max(float(existing_conf), float(new_conf))

        pantry_staples = inputs.get("pantry_staples") if isinstance(inputs.get("pantry_staples"), list) else []
        staples_added = 0
        for staple in pantry_staples:
            staple_item = _normalize_inventory_item(staple)
            if staple_item is None:
                continue
            canonical_name = alias_map.get(_clean_text(staple_item.get("name")), _clean_text(staple_item.get("name")))
            quantity, unit = _normalize_unit_quantity(
                float(staple_item.get("quantity") or 0.0),
                str(staple_item.get("unit") or ""),
            )
            key = f"{canonical_name}|{unit}"
            if key in merged:
                continue
            merged[key] = {
                "name": canonical_name,
                "quantity": max(0.0, quantity),
                "unit": unit,
                "expires_at": _iso_date_or_none(staple_item.get("expires_at")),
                "confidence": staple_item.get("confidence"),
            }
            staples_added += 1

        if merge_count:
            notes.append(f"duplicates_merged:{merge_count}")
        if converted_units:
            notes.append(f"unit_conversions:{converted_units}")
        if staples_added:
            notes.append(f"staples_added:{staples_added}")
        if not notes:
            notes.append("inventory_normalized")

        normalized_inventory = sorted(
            list(merged.values()),
            key=lambda item: (str(item.get("name") or ""), str(item.get("unit") or "")),
        )
        return {
            "normalized_inventory": normalized_inventory,
            "alias_map": alias_map,
            "notes": notes,
        }


class NeoEatsInputNormalizeBlock(BlockBase):
    DESCRIPTION = "Normalize NeoEats pantry input and dietary constraints."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "ingredients": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "object"},
        },
        "required": ["ingredients"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "normalized": {"type": "object"},
            "normalization_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["normalized"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        ingredients = _to_unique_ingredients(inputs.get("ingredients"))
        constraints = inputs.get("constraints") if isinstance(inputs.get("constraints"), dict) else {}
        user_id = str(inputs.get("user_id") or context.get("user_id") or "anonymous").strip() or "anonymous"

        servings = _parse_positive_int(constraints.get("servings"), minimum=1, maximum=16) or 2
        time_limit_minutes = _parse_positive_int(constraints.get("time_limit"), minimum=5, maximum=240)
        calories_target = _parse_positive_int(constraints.get("calories_target"), minimum=100, maximum=4000)

        normalized_constraints: Dict[str, Any] = {
            "diet": _normalize_diet(constraints.get("diet")),
            "allergens": _normalize_allergens(constraints.get("allergens")),
            "calories_target": calories_target,
            "cuisine": _clean_text(constraints.get("cuisine")) or None,
            "time_limit_minutes": time_limit_minutes,
            "servings": servings,
        }

        normalized_payload = {
            "user_id": user_id,
            "ingredients": ingredients,
            "constraints": normalized_constraints,
        }
        notes = [
            f"ingredients_normalized:{len(ingredients)}",
            f"diet:{normalized_constraints.get('diet') or 'none'}",
            f"allergens:{len(normalized_constraints.get('allergens') or [])}",
        ]
        return {"normalized": normalized_payload, "normalization_notes": notes}


class NeoEatsRecipeGenerateBlock(BlockBase):
    DESCRIPTION = "Generate a deterministic draft recipe JSON from normalized NeoEats input."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "normalized": {"type": "object"},
            "inventory": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["normalized"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "recipe": {"type": "object"},
            "used_inventory_only": {"type": "boolean"},
        },
        "required": ["recipe"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        normalized = inputs.get("normalized") if isinstance(inputs.get("normalized"), dict) else {}
        constraints = normalized.get("constraints") if isinstance(normalized.get("constraints"), dict) else {}
        ingredients = _to_unique_ingredients(normalized.get("ingredients"))

        inventory_names = _to_unique_ingredients(inputs.get("inventory"))
        if inventory_names:
            available = [item for item in ingredients if item in set(inventory_names)]
        else:
            available = ingredients
        if not available:
            available = inventory_names[:4] or ["rice", "tomato", "onion"]

        servings = _parse_positive_int(constraints.get("servings"), minimum=1, maximum=16) or 2
        time_limit = _parse_positive_int(constraints.get("time_limit_minutes"), minimum=5, maximum=240)
        time_minutes = time_limit or max(15, min(45, 12 + len(available) * 4))
        cuisine = _clean_text(constraints.get("cuisine"))
        diet = _normalize_diet(constraints.get("diet"))

        title_prefix = "Pantry"
        if cuisine:
            title_prefix = cuisine.title()
        if diet:
            title_prefix = f"{diet.replace('_', ' ').title()} {title_prefix}"
        title = f"{title_prefix} Smart Bowl"

        structured_ingredients: List[Dict[str, Any]] = []
        for name in available[:8]:
            quantity, unit = _quantity_unit_for(name)
            structured_ingredients.append(
                {
                    "name": name,
                    "quantity": quantity,
                    "unit": unit,
                }
            )

        steps = [
            "Wash and prep all ingredients.",
            "Cook base ingredients in one pan over medium heat.",
            "Add remaining ingredients, season, and cook until tender.",
            "Plate, adjust seasoning, and serve warm.",
        ]
        tags = ["neoeats", "recipe", "inventory"]
        if diet:
            tags.append(diet)
        if cuisine:
            tags.append(cuisine)

        recipe = {
            "title": title,
            "servings": servings,
            "time_minutes": time_minutes,
            "ingredients": structured_ingredients,
            "steps": steps,
            "tags": tags,
        }
        return {"recipe": recipe, "used_inventory_only": bool(inventory_names)}


class NeoEatsRecipeCompileStrictBlock(BlockBase):
    DESCRIPTION = "Compile draft recipe to inventory-backed ingredients and deterministic nutrition facts."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "draft_recipe": {"type": "object"},
            "normalized_inventory": {"type": "array", "items": {"type": "object"}},
            "constraints": {"type": "object"},
            "pantry_staples": {"type": "array", "items": {"type": ["string", "object"]}},
        },
        "required": ["draft_recipe", "normalized_inventory"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "recipe": {"type": "object"},
            "nutrition": {"type": "object"},
            "missing_items": {"type": "array", "items": {"type": "object"}},
            "substitutions": {"type": "array", "items": {"type": "object"}},
            "facts": {"type": "object"},
        },
        "required": ["recipe", "nutrition", "missing_items", "substitutions", "facts"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        draft_recipe = inputs.get("draft_recipe") if isinstance(inputs.get("draft_recipe"), dict) else {}
        constraints = inputs.get("constraints") if isinstance(inputs.get("constraints"), dict) else {}
        inventory_rows = inputs.get("normalized_inventory") if isinstance(inputs.get("normalized_inventory"), list) else []
        pantry_staples = inputs.get("pantry_staples") if isinstance(inputs.get("pantry_staples"), list) else []
        if not pantry_staples:
            pantry_staples = _default_staples_rows()

        inventory_lookup: Dict[str, Dict[str, Any]] = {}
        for row in inventory_rows:
            item = _normalize_inventory_item(row)
            if item is None:
                continue
            name = _clean_text(item.get("name"))
            if not name:
                continue
            inventory_lookup.setdefault(name, item)

        staples_lookup: Dict[str, Dict[str, Any]] = {}
        for staple in pantry_staples:
            item = _normalize_inventory_item(staple)
            if item is None:
                continue
            name = _clean_text(item.get("name"))
            if not name:
                continue
            staples_lookup.setdefault(name, item)

        allowed_lookup: Dict[str, Dict[str, Any]] = {}
        allowed_lookup.update(inventory_lookup)
        for name, item in staples_lookup.items():
            allowed_lookup.setdefault(name, item)

        alias_map = _normalize_alias_map(None)
        draft_ingredients = draft_recipe.get("ingredients") if isinstance(draft_recipe.get("ingredients"), list) else []
        compiled_rows: List[Dict[str, Any]] = []
        missing_items: List[Dict[str, Any]] = []
        substitutions: List[Dict[str, Any]] = []
        compiler_violations: List[Dict[str, Any]] = []
        staples_used: set[str] = set()

        for raw in draft_ingredients:
            item = _parse_recipe_ingredient(raw)
            if item is None:
                continue
            name = _clean_text(item.get("name"))
            resolved_name = _resolve_available_name(name, allowed_lookup, alias_map)
            if resolved_name is not None:
                source = inventory_lookup.get(resolved_name) or staples_lookup.get(resolved_name) or {}
                quantity = float(item.get("quantity") or 0.0) or float(source.get("quantity") or 0.0)
                unit = _clean_text(item.get("unit")) or _clean_text(source.get("unit")) or "g"
                source_type = "inventory" if resolved_name in inventory_lookup else "staple"
                expires_at = _iso_date_or_none(source.get("expires_at"))
                compiled_rows.append(
                    {
                        "name": resolved_name,
                        "quantity": quantity,
                        "unit": unit,
                        "source": source_type,
                        "expires_at": expires_at,
                        "days_to_expiry": _days_to_expiry(expires_at),
                    }
                )
                if resolved_name in staples_lookup:
                    staples_used.add(resolved_name)
                continue

            substitute = _find_substitute_name(name, allowed_lookup)
            if substitute is not None:
                source = inventory_lookup.get(substitute) or staples_lookup.get(substitute) or {}
                quantity = float(item.get("quantity") or 0.0) or float(source.get("quantity") or 0.0)
                unit = _clean_text(item.get("unit")) or _clean_text(source.get("unit")) or "g"
                source_type = "inventory" if substitute in inventory_lookup else "staple"
                expires_at = _iso_date_or_none(source.get("expires_at"))
                compiled_rows.append(
                    {
                        "name": substitute,
                        "quantity": quantity,
                        "unit": unit,
                        "source": source_type,
                        "expires_at": expires_at,
                        "days_to_expiry": _days_to_expiry(expires_at),
                    }
                )
                substitutions.append(
                    {
                        "missing": name,
                        "substitute": substitute,
                        "reason": "available_substitute",
                    }
                )
                if substitute in staples_lookup:
                    staples_used.add(substitute)
                continue

            suggested_qty = float(item.get("quantity") or 0.0)
            normalized_suggested = round(suggested_qty, 2) if suggested_qty > 0 else None
            missing_items.append(
                {
                    "name": name,
                    "suggested_qty": normalized_suggested,
                    "suggested_quantity": normalized_suggested,
                    "unit": _clean_text(item.get("unit")) or "g",
                }
            )
            compiler_violations.append(
                {
                    "type": "ingredient_missing_from_inventory",
                    "name": name,
                    "severity": "medium",
                }
            )

        if not compiled_rows:
            for row in list(inventory_lookup.values())[:4]:
                name = _clean_text(row.get("name"))
                if not name:
                    continue
                quantity = float(row.get("quantity") or 0.0)
                unit = _clean_text(row.get("unit")) or "g"
                expires_at = _iso_date_or_none(row.get("expires_at"))
                compiled_rows.append(
                    {
                        "name": name,
                        "quantity": quantity,
                        "unit": unit,
                        "source": "inventory",
                        "expires_at": expires_at,
                        "days_to_expiry": _days_to_expiry(expires_at),
                    }
                )
            if not compiled_rows:
                for row in list(staples_lookup.values())[:2]:
                    name = _clean_text(row.get("name"))
                    if not name:
                        continue
                    quantity = float(row.get("quantity") or 0.0)
                    unit = _clean_text(row.get("unit")) or "g"
                    expires_at = _iso_date_or_none(row.get("expires_at"))
                    compiled_rows.append(
                        {
                            "name": name,
                            "quantity": quantity,
                            "unit": unit,
                            "source": "staple",
                            "expires_at": expires_at,
                            "days_to_expiry": _days_to_expiry(expires_at),
                        }
                    )
                    staples_used.add(name)

        recipe_ingredients = _merge_recipe_ingredients(compiled_rows)
        servings = _parse_positive_int(
            draft_recipe.get("servings") or constraints.get("servings"),
            minimum=1,
            maximum=16,
        ) or 2
        time_minutes = _parse_positive_int(
            draft_recipe.get("time_minutes") or constraints.get("time_limit_minutes") or constraints.get("time_limit"),
            minimum=5,
            maximum=240,
        ) or 30
        title = str(draft_recipe.get("title") or "Inventory Strict Recipe").strip() or "Inventory Strict Recipe"
        draft_steps = draft_recipe.get("steps") if isinstance(draft_recipe.get("steps"), list) else []
        steps = [str(step).strip() for step in draft_steps if str(step).strip()]
        if not steps:
            steps = [
                "Prepare the available ingredients.",
                "Cook ingredients in sequence based on cooking time.",
                "Plate and season with measured amounts.",
            ]
        tags = [
            str(tag).strip()
            for tag in (draft_recipe.get("tags") if isinstance(draft_recipe.get("tags"), list) else [])
            if str(tag).strip()
        ]
        if "facts_first" not in tags:
            tags.append("facts_first")

        recipe = {
            "title": title,
            "servings": servings,
            "time_minutes": time_minutes,
            "ingredients": recipe_ingredients,
            "steps": steps,
            "tags": tags,
        }

        nutrition_index, nutrition_aliases = _build_nutrition_index()
        total_kcal = 0.0
        total_protein = 0.0
        total_fat = 0.0
        total_carbs = 0.0
        used_fallback = False
        for row in recipe_ingredients:
            totals = _nutrition_totals_for_ingredient(
                name=str(row.get("name") or ""),
                quantity=float(row.get("quantity") or 0.0),
                unit=str(row.get("unit") or ""),
                nutrition_index=nutrition_index,
                alias_index=nutrition_aliases,
            )
            total_kcal += float(totals.get("kcal") or 0.0)
            total_protein += float(totals.get("protein_g") or 0.0)
            total_fat += float(totals.get("fat_g") or 0.0)
            total_carbs += float(totals.get("carbs_g") or 0.0)
            used_fallback = used_fallback or bool(totals.get("used_fallback"))

        per_serving = {
            "kcal": round(total_kcal / float(servings), 1) if servings else round(total_kcal, 1),
            "protein_g": round(total_protein / float(servings), 1) if servings else round(total_protein, 1),
            "fat_g": round(total_fat / float(servings), 1) if servings else round(total_fat, 1),
            "carbs_g": round(total_carbs / float(servings), 1) if servings else round(total_carbs, 1),
        }
        nutrition = {
            "kcal_total": int(round(total_kcal)),
            "protein_g": round(total_protein, 1),
            "fat_g": round(total_fat, 1),
            "carbs_g": round(total_carbs, 1),
            "per_serving": per_serving,
            "confidence": "low" if used_fallback else "high",
        }
        if nutrition["kcal_total"] < 0:
            nutrition["kcal_total"] = 0
        for macro in ("protein_g", "fat_g", "carbs_g"):
            if float(nutrition.get(macro) or 0.0) < 0:
                nutrition[macro] = 0.0

        facts = {
            "used_inventory_only": bool(recipe_ingredients) and len(staples_used) == 0,
            "staples_used": sorted(staples_used),
            "compiler_violations": compiler_violations,
        }
        return {
            "recipe": recipe,
            "nutrition": nutrition,
            "missing_items": missing_items,
            "substitutions": substitutions,
            "facts": facts,
        }


class NeoEatsRecipeValidateBlock(BlockBase):
    DESCRIPTION = "Validate recipe constraints with local STUB/DRY_RUN-safe heuristics."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "recipe": {"type": "object"},
            "constraints": {"type": "object"},
            "normalized_inventory": {"type": "array", "items": {"type": "object"}},
            "nutrition": {"type": "object"},
        },
        "required": ["recipe", "constraints"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "violations": {"type": "array", "items": {"type": "object"}},
            "suggestions": {"type": "array", "items": {"type": "string"}},
            "estimated_calories": {"type": "integer"},
        },
        "required": ["ok", "violations", "suggestions"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        recipe = inputs.get("recipe") if isinstance(inputs.get("recipe"), dict) else {}
        constraints = inputs.get("constraints") if isinstance(inputs.get("constraints"), dict) else {}
        normalized_inventory = (
            inputs.get("normalized_inventory") if isinstance(inputs.get("normalized_inventory"), list) else []
        )
        nutrition = inputs.get("nutrition") if isinstance(inputs.get("nutrition"), dict) else {}

        ingredients = recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []
        ingredient_names = [
            _clean_text(item.get("name") if isinstance(item, dict) else item)
            for item in ingredients
        ]
        recipe_text = " ".join(
            [
                _clean_text(recipe.get("title")),
                " ".join(_clean_text(step) for step in (recipe.get("steps") or []) if isinstance(step, str)),
                " ".join(name for name in ingredient_names if name),
            ]
        )

        violations: List[Dict[str, Any]] = []
        suggestions: List[str] = []

        if normalized_inventory:
            allowed_names: set[str] = set()
            for row in normalized_inventory:
                item = _normalize_inventory_item(row)
                if item is None:
                    continue
                allowed_name = _clean_text(item.get("name"))
                if allowed_name:
                    allowed_names.add(allowed_name)
            inventory_misses = sorted(
                {
                    name
                    for name in ingredient_names
                    if name and name not in allowed_names
                }
            )
            if inventory_misses:
                violations.append(
                    {
                        "type": "ingredients_not_in_inventory",
                        "message": (
                            "Recipe contains ingredients outside allowed inventory: "
                            + ", ".join(inventory_misses[:6])
                        ),
                        "severity": "high",
                    }
                )
                suggestions.append("Run neoeats.recipe.compile_strict to enforce inventory-only ingredients.")

        if not nutrition or any(key not in nutrition for key in ("kcal_total", "protein_g", "fat_g", "carbs_g")):
            violations.append(
                {
                    "type": "nutrition_missing",
                    "message": "Nutrition fields are missing. Compile recipe with neoeats.recipe.compile_strict.",
                    "severity": "high",
                }
            )
            suggestions.append("Compile the recipe with neoeats.recipe.compile_strict before validation.")

        allergens = _normalize_allergens(constraints.get("allergens"))
        for allergen in allergens:
            if allergen == "tree_nut":
                matched = "nut" in recipe_text or "almond" in recipe_text or "walnut" in recipe_text
            else:
                matched = allergen in recipe_text
            if matched:
                violations.append(
                    {
                        "type": "allergen",
                        "message": f"Potential allergen detected: {allergen}.",
                        "severity": "high",
                    }
                )
                suggestions.append(f"Replace or remove ingredients related to {allergen}.")

        diet = _normalize_diet(constraints.get("diet"))
        if diet in _DIET_DISALLOWED_TOKENS:
            disallowed = sorted(token for token in _DIET_DISALLOWED_TOKENS[diet] if token in recipe_text)
            if disallowed:
                violations.append(
                    {
                        "type": "diet",
                        "message": f"Recipe conflicts with diet '{diet}': {', '.join(disallowed)}.",
                        "severity": "medium",
                    }
                )
                suggestions.append(f"Swap disallowed ingredients for {diet}-friendly alternatives.")

        calories_target = _parse_positive_int(constraints.get("calories_target"), minimum=100, maximum=4000)
        estimated_calories = None
        kcal_total_raw = nutrition.get("kcal_total")
        if kcal_total_raw is not None:
            try:
                estimated_calories = int(round(float(kcal_total_raw)))
            except Exception:
                estimated_calories = None
        if estimated_calories is None:
            estimated_calories = _estimate_recipe_calories(recipe)
        if calories_target and estimated_calories:
            upper_bound = int(calories_target * 1.2)
            lower_bound = int(calories_target * 0.6)
            if estimated_calories > upper_bound or estimated_calories < lower_bound:
                violations.append(
                    {
                        "type": "calories_target_mismatch",
                        "message": (
                            f"Estimated calories ({estimated_calories}) outside target range "
                            f"for goal {calories_target}."
                        ),
                        "severity": "low",
                    }
                )
                suggestions.append("Adjust portions or replace high-calorie ingredients.")

        ok = len(violations) == 0
        return {
            "ok": ok,
            "violations": violations,
            "suggestions": suggestions,
            "estimated_calories": estimated_calories,
        }


class InventoryBlock(BlockBase):
    DESCRIPTION = "Reserve, release, or commit inventory in the ledger."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "reserve|release|commit"},
            "order_id": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object"}},
            "reservation_id": {"type": "string"},
            "source": {"type": "string"},
        },
        "required": ["action"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "reservation_id": {"type": "string"},
            "ledger_version": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["ok"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        action = str(inputs.get("action") or "").lower().strip()
        if action not in {"reserve", "release", "commit"}:
            raise ValueError("InventoryBlock requires action: reserve|release|commit")

        db = _require_db(self._engine)
        reservation_id = str(inputs.get("reservation_id") or uuid.uuid4())
        order_id = inputs.get("order_id")
        source = inputs.get("source") or "order"

        if action == "reserve":
            if not order_id:
                raise ValueError("InventoryBlock reserve requires order_id")
            items = inputs.get("items") or []
            if not items:
                raise ValueError("InventoryBlock reserve requires items")

            ttl_min = int(inputs.get("reservation_ttl_min") or 15)
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_min)

            allocated: List[Dict[str, Any]] = []
            async with db.transaction() as conn:
                await conn.execute(
                    """
                    INSERT INTO inventory_reservation (reservation_id, order_id, status, expires_at)
                    VALUES ($1, $2, 'reserved', $3)
                    """,
                    reservation_id,
                    order_id,
                    expires_at,
                )

                for item in items:
                    item_id = item.get("item_id")
                    quantity = float(item.get("quantity") or 0)
                    lot_id = item.get("lot_id")
                    if not item_id or quantity <= 0:
                        raise ValueError("InventoryBlock reserve requires item_id and positive quantity")

                    if lot_id is None:
                        row = await conn.fetchrow(
                            """
                            SELECT lot_id, quantity_available
                            FROM inventory_lot
                            WHERE item_id = $1 AND quantity_available >= $2
                            ORDER BY expires_at NULLS LAST, created_at
                            LIMIT 1
                            """,
                            item_id,
                            quantity,
                        )
                        if not row:
                            raise ValueError(f"Insufficient inventory for item_id={item_id}")
                        lot_id = row["lot_id"]

                    updated = await conn.fetchrow(
                        """
                        UPDATE inventory_lot
                        SET quantity_available = quantity_available - $1, updated_at = now()
                        WHERE lot_id = $2 AND quantity_available >= $1
                        RETURNING lot_id
                        """,
                        quantity,
                        lot_id,
                    )
                    if not updated:
                        raise ValueError(f"Insufficient inventory for lot_id={lot_id}")

                    await conn.execute(
                        """
                        INSERT INTO inventory_reservation_line (reservation_id, lot_id, quantity)
                        VALUES ($1, $2, $3)
                        """,
                        reservation_id,
                        lot_id,
                        quantity,
                    )
                    await conn.execute(
                        """
                        INSERT INTO inventory_ledger_event (event_id, event_type, item_id, lot_id, quantity, source, reference_id)
                        VALUES (gen_random_uuid(), 'reserve', $1, $2, $3, $4, $5)
                        """,
                        item_id,
                        lot_id,
                        quantity,
                        source,
                        reservation_id,
                    )
                    allocated.append({"item_id": item_id, "lot_id": lot_id, "quantity": quantity})

                ledger_version = await conn.fetchval("SELECT txid_current()")

            return {
                "ok": True,
                "reservation_id": reservation_id,
                "ledger_version": str(ledger_version),
                "items": allocated,
            }

        if action in {"release", "commit"}:
            if not reservation_id:
                raise ValueError("InventoryBlock release/commit requires reservation_id")

            async with db.transaction() as conn:
                status = await conn.fetchval(
                    "SELECT status FROM inventory_reservation WHERE reservation_id = $1",
                    reservation_id,
                )
                if not status:
                    raise ValueError(f"Reservation not found: {reservation_id}")

                lines = await conn.fetch(
                    """
                    SELECT rl.lot_id, rl.quantity, il.item_id
                    FROM inventory_reservation_line rl
                    JOIN inventory_lot il ON il.lot_id = rl.lot_id
                    WHERE rl.reservation_id = $1
                    """,
                    reservation_id,
                )

                if action == "release":
                    for line in lines:
                        await conn.execute(
                            """
                            UPDATE inventory_lot
                            SET quantity_available = quantity_available + $1, updated_at = now()
                            WHERE lot_id = $2
                            """,
                            line["quantity"],
                            line["lot_id"],
                        )

                new_status = "released" if action == "release" else "committed"
                await conn.execute(
                    """
                    UPDATE inventory_reservation
                    SET status = $2, updated_at = now()
                    WHERE reservation_id = $1
                    """,
                    reservation_id,
                    new_status,
                )

                for line in lines:
                    await conn.execute(
                        """
                        INSERT INTO inventory_ledger_event (event_id, event_type, item_id, lot_id, quantity, source, reference_id)
                        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)
                        """,
                        new_status,
                        line["item_id"],
                        line["lot_id"],
                        line["quantity"],
                        source,
                        reservation_id,
                    )

                ledger_version = await conn.fetchval("SELECT txid_current()")

            return {
                "ok": True,
                "reservation_id": reservation_id,
                "ledger_version": str(ledger_version),
                "items": [dict(line) for line in lines],
            }

        raise ValueError("Unsupported inventory action")


class DailyExpiryScanBlock(BlockBase):
    DESCRIPTION = "Scan inventory lots for expiring items."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "as_of_date": {"type": "string", "description": "ISO date"},
            "window_days": {"type": "integer", "description": "Expiry window in days"},
            "location_id": {"type": "string"},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "expiring_items": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["expiring_items"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        window_days = int(inputs.get("window_days") or 14)
        as_of_date = inputs.get("as_of_date")
        location_id = inputs.get("location_id")

        if as_of_date:
            ref_date = datetime.fromisoformat(as_of_date).date()
        else:
            ref_date = datetime.now(timezone.utc).date()

        if location_id:
            rows = await db.fetch(
                """
                SELECT il.lot_id, il.item_id, il.expires_at, il.quantity_available, ii.name, ii.sku
                FROM inventory_lot il
                JOIN inventory_item ii ON ii.item_id = il.item_id
                WHERE il.location_id = $1
                  AND il.expires_at <= ($2::date + ($3::text || ' days')::interval)
                  AND il.quantity_available > 0
                ORDER BY il.expires_at
                """,
                location_id,
                ref_date,
                window_days,
            )
        else:
            rows = await db.fetch(
                """
                SELECT il.lot_id, il.item_id, il.expires_at, il.quantity_available, ii.name, ii.sku
                FROM inventory_lot il
                JOIN inventory_item ii ON ii.item_id = il.item_id
                WHERE il.expires_at <= ($1::date + ($2::text || ' days')::interval)
                  AND il.quantity_available > 0
                ORDER BY il.expires_at
                """,
                ref_date,
                window_days,
            )

        return {"expiring_items": [dict(row) for row in rows]}


class AlertBlock(BlockBase):
    DESCRIPTION = "Create staff alerts for expiring inventory."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "expiring_items": {"type": "array", "items": {"type": "object"}},
            "channel": {"type": "string"},
            "recipient_info": {"type": "object"},
        },
        "required": ["expiring_items"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "notified_count": {"type": "integer"},
        },
        "required": ["notified_count"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        expiring = inputs.get("expiring_items") or []
        channel = inputs.get("channel")
        recipient_info = inputs.get("recipient_info") or {}

        lines: List[str] = []
        for item in expiring:
            name = item.get("name") or item.get("sku") or "item"
            expires_at = item.get("expires_at") or ""
            quantity = item.get("quantity_available")
            lines.append(f"{name} expires {expires_at} (qty={quantity})")
        message_body = "\n".join(lines)

        from app.core.blocks import NotificationBlock

        notifier = NotificationBlock(
            engine=self._engine,
            params={"channel": channel, "recipient_info": recipient_info},
        )
        result = await notifier.execute(
            context,
            {
                "items": expiring,
                "message_body": message_body,
                "recipient_info": recipient_info,
                "channel": channel,
            },
        )
        return {"notified_count": int(result.get("notified_count") or 0)}


class BillingBlock(BlockBase):
    DESCRIPTION = "Compute billing totals and generate receipt metadata."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "line_items": {"type": "array", "items": {"type": "object"}},
            "cogs_total": {"type": "number"},
            "waste_overhead": {"type": "number"},
            "margin_pct": {"type": "number"},
            "vat_pct": {"type": "number"},
            "currency": {"type": "string"},
        },
        "required": ["order_id", "cogs_total", "margin_pct", "vat_pct"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "subtotal": {"type": "number"},
            "vat": {"type": "number"},
            "total": {"type": "number"},
            "receipt_id": {"type": "string"},
            "currency": {"type": "string"},
        },
        "required": ["total", "receipt_id"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        cogs_total = float(inputs.get("cogs_total") or 0.0)
        waste_overhead = float(inputs.get("waste_overhead") or 0.0)
        margin_pct = float(inputs.get("margin_pct") or 0.0)
        vat_pct = float(inputs.get("vat_pct") or 0.0)
        currency = inputs.get("currency") or "NOK"

        subtotal = (cogs_total + waste_overhead) * (1.0 + margin_pct)
        vat = subtotal * vat_pct
        total = subtotal + vat
        receipt_id = str(uuid.uuid4())

        return {
            "subtotal": round(subtotal, 2),
            "vat": round(vat, 2),
            "total": round(total, 2),
            "receipt_id": receipt_id,
            "currency": currency,
        }


class AccountingBlock(BlockBase):
    DESCRIPTION = "Post receipts and update daily financial ledger."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "receipt_id": {"type": "string"},
            "total": {"type": "number"},
            "vat": {"type": "number"},
            "currency": {"type": "string"},
            "source": {"type": "string"},
        },
        "required": ["order_id", "receipt_id", "total"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "posted": {"type": "boolean"},
            "journal_entry_id": {"type": "string"},
        },
        "required": ["posted"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        order_id = inputs.get("order_id")
        receipt_id = inputs.get("receipt_id")
        total = float(inputs.get("total") or 0.0)
        vat = float(inputs.get("vat") or 0.0)
        currency = inputs.get("currency") or "NOK"
        source = inputs.get("source") or "order"

        if not order_id or not receipt_id:
            raise ValueError("AccountingBlock requires order_id and receipt_id")

        async with db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO financial_receipt (receipt_id, order_id, subtotal, vat, total, currency)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (receipt_id) DO NOTHING
                """,
                receipt_id,
                order_id,
                float(inputs.get("subtotal") or 0.0),
                vat,
                total,
                currency,
            )
            journal_entry_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO financial_journal (entry_id, order_id, receipt_id, amount, vat, currency, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                journal_entry_id,
                order_id,
                receipt_id,
                total,
                vat,
                currency,
                source,
            )

        return {"posted": True, "journal_entry_id": journal_entry_id}


class AdminAddProductBlock(BlockBase):
    DESCRIPTION = "Add a new product into the inventory catalog."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string"},
            "unit": {"type": "string"},
            "initial_quantity": {"type": "number"},
            "expires_at": {"type": "string"},
            "location_id": {"type": "string"},
        },
        "required": ["sku", "name"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "lot_id": {"type": "string"},
        },
        "required": ["item_id"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        item_id = str(uuid.uuid4())
        lot_id = str(uuid.uuid4())

        sku = inputs.get("sku")
        name = inputs.get("name")
        category = inputs.get("category")
        unit = inputs.get("unit")
        initial_quantity = inputs.get("initial_quantity")
        expires_at = inputs.get("expires_at")
        location_id = inputs.get("location_id")

        if not sku or not name:
            raise ValueError("AdminAddProductBlock requires sku and name")

        async with db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO inventory_item (item_id, sku, name, category, unit, is_active)
                VALUES ($1, $2, $3, $4, $5, true)
                """,
                item_id,
                sku,
                name,
                category,
                unit,
            )

            if initial_quantity is not None:
                await conn.execute(
                    """
                    INSERT INTO inventory_lot (lot_id, item_id, expires_at, quantity_total, quantity_available, location_id)
                    VALUES ($1, $2, $3, $4, $4, $5)
                    """,
                    lot_id,
                    item_id,
                    expires_at,
                    float(initial_quantity),
                    location_id,
                )

        _invalidate_inventory_cache(self._engine)
        return {"item_id": item_id, "lot_id": lot_id}


class AdminUpdateProductBlock(BlockBase):
    DESCRIPTION = "Update product metadata or lot quantities."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "sku": {"type": "string"},
            "name": {"type": "string"},
            "category": {"type": "string"},
            "unit": {"type": "string"},
            "is_active": {"type": "boolean"},
        },
        "required": ["item_id"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "updated": {"type": "boolean"},
        },
        "required": ["updated"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        item_id = inputs.get("item_id")
        if not item_id:
            raise ValueError("AdminUpdateProductBlock requires item_id")

        fields = {k: inputs.get(k) for k in ["sku", "name", "category", "unit", "is_active"]}
        set_clauses: List[str] = []
        values: List[Any] = []
        index = 1
        for key, value in fields.items():
            if value is not None:
                set_clauses.append(f"{key} = ${index}")
                values.append(value)
                index += 1

        if not set_clauses:
            return {"updated": False}

        values.append(item_id)
        query = f"UPDATE inventory_item SET {', '.join(set_clauses)}, updated_at = now() WHERE item_id = ${index}"
        await db.execute(query, *values)

        _invalidate_inventory_cache(self._engine)
        return {"updated": True}


class AdminRemoveProductBlock(BlockBase):
    DESCRIPTION = "Deactivate a product in the catalog."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string"},
            "sku": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["item_id"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "removed": {"type": "boolean"},
        },
        "required": ["removed"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        item_id = inputs.get("item_id")
        sku = inputs.get("sku")
        if not item_id and not sku:
            raise ValueError("AdminRemoveProductBlock requires item_id or sku")

        if item_id:
            await db.execute(
                "UPDATE inventory_item SET is_active = false, updated_at = now() WHERE item_id = $1",
                item_id,
            )
        else:
            await db.execute(
                "UPDATE inventory_item SET is_active = false, updated_at = now() WHERE sku = $1",
                sku,
            )

        _invalidate_inventory_cache(self._engine)
        return {"removed": True}


class ReceiptScannerBlock(BlockBase):
    DESCRIPTION = "Extract structured receipt data for inventory and fiscal compliance."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "image_url": {"type": "string"},
            "image_base64": {"type": "string"},
            "vendor_hint": {"type": "string"},
            "currency": {"type": "string"},
            "locale": {"type": "string"},
            "mock_receipt": {"type": "object"},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "vendor_info": {"type": "object"},
            "fiscal_data": {"type": "object"},
            "line_items": {"type": "array", "items": {"type": "object"}},
            "vat_validation": {"type": "object"},
        },
        "required": ["vendor_info", "fiscal_data", "line_items"],
    }

    @staticmethod
    def calculate_vat_breakdown(
        *,
        total_amount: float,
        vat_lines: List[Dict[str, Any]],
        allowed_rates: Optional[List[float]] = None,
        tolerance: float = 0.5,
    ) -> Dict[str, Any]:
        allowed = allowed_rates or [0.15, 0.25]
        unknown_rates = [line for line in vat_lines if float(line.get("rate") or 0) not in allowed]
        vat_total = sum(float(line.get("vat_amount") or 0.0) for line in vat_lines)
        base_total = sum(float(line.get("base_amount") or 0.0) for line in vat_lines)
        expected_total = base_total + vat_total
        delta = abs(float(total_amount or 0.0) - expected_total)
        return {
            "vat_total": round(vat_total, 2),
            "base_total": round(base_total, 2),
            "expected_total": round(expected_total, 2),
            "delta": round(delta, 2),
            "within_tolerance": delta <= tolerance,
            "unknown_rates": [line.get("rate") for line in unknown_rates],
        }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        mock = inputs.get("mock_receipt")
        if isinstance(mock, dict):
            fiscal = mock.get("fiscal_data") or {}
            vat_validation = self.calculate_vat_breakdown(
                total_amount=float(fiscal.get("total_amount") or 0.0),
                vat_lines=list(fiscal.get("vat_breakdown") or []),
            )
            return {
                "vendor_info": mock.get("vendor_info") or {},
                "fiscal_data": fiscal,
                "line_items": mock.get("line_items") or [],
                "vat_validation": vat_validation,
            }
        raise NotImplementedError("ReceiptScannerBlock requires LLM-backed OCR integration.")


class ReceiptProcessorBlock(BlockBase):
    DESCRIPTION = "Validate receipt data and prepare ledger + fiscal transactions."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "receipt": {"type": "object"},
            "approved": {"type": "boolean"},
            "source": {"type": "string"},
        },
        "required": ["receipt", "approved"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "accepted": {"type": "boolean"},
            "ledger_updates": {"type": "array", "items": {"type": "object"}},
            "fiscal_transaction_id": {"type": "string"},
        },
        "required": ["accepted"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        approved = bool(inputs.get("approved"))
        if not approved:
            return {"accepted": False, "ledger_updates": []}
        raise NotImplementedError("ReceiptProcessorBlock requires ledger update integration.")


FORBIDDEN_COMBOS = [
    {"herring", "strawberry"},
    {"anchovy", "chocolate"},
    {"blue_cheese", "mango"},
]


def _normalize_ingredient(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _is_combo_allowed(ingredients: List[str]) -> bool:
    normalized = {_normalize_ingredient(item) for item in ingredients if item}
    for rule in FORBIDDEN_COMBOS:
        if rule.issubset(normalized):
            return False
    return True


def _build_hot_offer_prompt(priority_items: List[Dict[str, Any]], sales_stats: List[Dict[str, Any]]) -> str:
    return (
        "You are a culinary marketing expert. Generate a single hot offer using the priority items. "
        "Return ONLY JSON with keys: name, slogan, ingredients, cogs_total, currency, price. "
        "Ingredients should be a list of item names. Keep it realistic and appetizing.\n\n"
        f"Priority items: {json.dumps(priority_items)}\n"
        f"Sales stats: {json.dumps(sales_stats)}"
    )


def _build_validator_prompt(offer: Dict[str, Any]) -> str:
    return (
        "You are an expert culinary safety inspector and food critic. "
        "Score the offer for palatability and safety on a 1-10 scale. "
        "Return ONLY JSON with keys: palatability_score, safety_score, notes.\n\n"
        f"Offer: {json.dumps(offer)}"
    )


class PriorityInventoryScanBlock(BlockBase):
    DESCRIPTION = "Find priority inventory items for hot offers."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "expiry_days": {"type": "integer"},
            "overstock_threshold": {"type": "number"},
            "location_id": {"type": "string"},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["items"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        expiry_days = int(inputs.get("expiry_days") or 3)
        overstock_threshold = float(inputs.get("overstock_threshold") or 10)
        location_id = inputs.get("location_id")

        if location_id:
            rows = await db.fetch(
                """
                SELECT il.lot_id, il.item_id, il.expires_at, il.quantity_available,
                       ii.name, ii.category, ii.sku
                FROM inventory_lot il
                JOIN inventory_item ii ON ii.item_id = il.item_id
                WHERE il.location_id = $1
                  AND (
                    il.expires_at <= (now() + ($2::text || ' days')::interval)
                    OR il.quantity_available >= $3
                  )
                ORDER BY il.expires_at NULLS LAST, il.quantity_available DESC
                """,
                location_id,
                expiry_days,
                overstock_threshold,
            )
        else:
            rows = await db.fetch(
                """
                SELECT il.lot_id, il.item_id, il.expires_at, il.quantity_available,
                       ii.name, ii.category, ii.sku
                FROM inventory_lot il
                JOIN inventory_item ii ON ii.item_id = il.item_id
                WHERE (
                    il.expires_at <= (now() + ($1::text || ' days')::interval)
                    OR il.quantity_available >= $2
                )
                ORDER BY il.expires_at NULLS LAST, il.quantity_available DESC
                """,
                expiry_days,
                overstock_threshold,
            )

        return {"items": [dict(row) for row in rows]}


class SalesStatsFetchBlock(BlockBase):
    DESCRIPTION = "Fetch sales stats for popularity cross-referencing."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "day_of_week": {"type": "integer"},
            "hour_of_day": {"type": "integer"},
            "location_id": {"type": "string"},
            "limit": {"type": "integer"},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "stats": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["stats"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        day_of_week = inputs.get("day_of_week")
        hour_of_day = inputs.get("hour_of_day")
        location_id = inputs.get("location_id")
        limit = int(inputs.get("limit") or 50)

        clauses: List[str] = []
        params: List[Any] = []
        if location_id:
            params.append(location_id)
            clauses.append(f"location_id = ${len(params)}")
        if day_of_week is not None:
            params.append(int(day_of_week))
            clauses.append(f"day_of_week = ${len(params)}")
        if hour_of_day is not None:
            params.append(int(hour_of_day))
            clauses.append(f"hour_of_day = ${len(params)}")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        query = (
            "SELECT stat_id, location_id, day_of_week, hour_of_day, category, recipe_name, avg_units_sold "
            "FROM sales_stats "
            f"{where} "
            "ORDER BY avg_units_sold DESC "
            f"LIMIT {max(1, min(limit, 200))}"
        )
        rows = await db.fetch(query, *params)
        return {"stats": [dict(row) for row in rows]}


class HotOfferGeneratorBlock(BlockBase):
    DESCRIPTION = "Generate a hot offer from priority inventory and sales stats."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "priority_items": {"type": "array", "items": {"type": "object"}},
            "sales_stats": {"type": "array", "items": {"type": "object"}},
            "currency": {"type": "string"},
            "margin_pct": {"type": "number"},
            "waste_overhead": {"type": "number"},
            "mock_offer": {"type": "object"},
        },
        "required": ["priority_items"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "offer": {"type": "object"},
            "offer_id": {"type": "string"},
        },
        "required": ["offer", "offer_id"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        metrics = get_metrics()
        metrics.increment("neoeats.hot_offer.generate.attempt", 1)

        priority_items = inputs.get("priority_items") or []
        sales_stats = inputs.get("sales_stats") or []
        currency = inputs.get("currency") or "NOK"
        margin_pct = float(inputs.get("margin_pct") or 0.25)
        waste_overhead = float(inputs.get("waste_overhead") or 0.0)

        try:
            if inputs.get("mock_offer"):
                offer = dict(inputs.get("mock_offer") or {})
            else:
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    raise RuntimeError("GEMINI_API_KEY is not configured")
                model_name = os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-2.0-flash"
                prompt = _build_hot_offer_prompt(priority_items, sales_stats)
                gemini = _build_gemini_client(api_key=api_key, default_model=model_name)

                def _run_call() -> str:
                    return gemini.generate_content(prompt, model=model_name)

                text = await asyncio.to_thread(_run_call)
                offer = json.loads(_strip_json_fence(text))
        except Exception:
            metrics.increment("neoeats.hot_offer.generate.error", 1)
            raise

        ingredients = offer.get("ingredients") or []
        if not isinstance(ingredients, list):
            raise ValueError("Hot offer ingredients must be a list")
        if not _is_combo_allowed([str(item) for item in ingredients]):
            raise ValueError("Hot offer contains forbidden ingredient combination")

        cogs_total = float(offer.get("cogs_total") or 0.0)
        if cogs_total <= 0:
            cogs_total = sum(float(item.get("cost_total") or 0.0) for item in priority_items)
        subtotal = (cogs_total + waste_overhead) * (1.0 + margin_pct)
        price = float(offer.get("price") or round(subtotal, 2))

        offer_id = str(uuid.uuid4())
        offer_payload = {
            "name": offer.get("name"),
            "slogan": offer.get("slogan"),
            "ingredients": ingredients,
            "cogs_total": round(cogs_total, 2),
            "currency": currency,
            "price": round(price, 2),
            "margin_pct": margin_pct,
            "waste_overhead": waste_overhead,
        }

        await db.execute(
            """
            INSERT INTO pending_offers (offer_id, status, offer_payload)
            VALUES ($1, 'pending', $2)
            """,
            offer_id,
            json.dumps(offer_payload),
        )
        metrics.increment("neoeats.hot_offer.generate.success", 1)
        return {"offer": offer_payload, "offer_id": offer_id}


class CulinaryValidatorBlock(BlockBase):
    DESCRIPTION = "Validate hot offer palatability and safety using LLM scoring."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "offer": {"type": "object"},
            "threshold": {"type": "number"},
            "terminate_on_reject": {"type": "boolean"},
            "retry_on_reject": {"type": "boolean"},
            "retry_attempt": {"type": "integer"},
            "max_retries": {"type": "integer"},
            "mock_validation": {"type": "object"},
        },
        "required": ["offer"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "palatability_score": {"type": "number"},
            "safety_score": {"type": "number"},
            "accepted": {"type": "boolean"},
            "notes": {"type": "string"},
            "should_retry": {"type": "boolean"},
        },
        "required": ["palatability_score", "safety_score", "accepted"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        metrics = get_metrics()
        offer = inputs.get("offer") or {}
        threshold = float(
            inputs.get("threshold")
            or os.getenv("NEOEATS_HOT_OFFER_THRESHOLD")
            or 8
        )

        if inputs.get("mock_validation"):
            payload = dict(inputs.get("mock_validation") or {})
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            model_name = os.getenv("SEED_GEMINI_MODEL_BALANCED") or "gemini-2.0-flash"
            prompt = _build_validator_prompt(offer)
            gemini = _build_gemini_client(api_key=api_key, default_model=model_name)

            def _run_call() -> str:
                return gemini.generate_content(prompt, model=model_name)

            text = await asyncio.to_thread(_run_call)
            payload = json.loads(_strip_json_fence(text))

        palatability = float(payload.get("palatability_score") or 0.0)
        safety = float(payload.get("safety_score") or 0.0)
        accepted = palatability >= threshold and safety >= threshold
        retry_on_reject = bool(inputs.get("retry_on_reject"))
        retry_attempt = int(inputs.get("retry_attempt") or 0)
        max_retries = int(
            inputs.get("max_retries")
            or os.getenv("NEOEATS_HOT_OFFER_MAX_RETRIES")
            or 0
        )
        should_retry = (not accepted) and retry_on_reject and retry_attempt < max_retries

        if not accepted:
            metrics.increment("neoeats.hot_offer.validation.rejected", 1)
        if not accepted and bool(inputs.get("terminate_on_reject")) and not should_retry:
            raise ValueError("culinary_validation_failed")

        return {
            "palatability_score": palatability,
            "safety_score": safety,
            "accepted": accepted,
            "notes": payload.get("notes", ""),
            "should_retry": should_retry,
        }


class ApprovalBlock(BlockBase):
    DESCRIPTION = "Approve or reject a hot offer and persist final status."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "offer_id": {"type": "string"},
            "approved": {"type": "boolean"},
            "notes": {"type": "string"},
        },
        "required": ["offer_id", "approved"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "status": {"type": "string"},
        },
        "required": ["approved", "status"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        metrics = get_metrics()
        offer_id = inputs.get("offer_id")
        approved = bool(inputs.get("approved"))
        notes = inputs.get("notes")
        status = "approved" if approved else "rejected"

        row = await db.fetchrow(
            "SELECT offer_payload, created_at FROM pending_offers WHERE offer_id = $1",
            offer_id,
        )
        if not row:
            raise ValueError("Pending offer not found")

        await db.execute(
            """
            UPDATE pending_offers
            SET status = $2, validation_scores = coalesce(validation_scores, '{}'::jsonb), updated_at = now()
            WHERE offer_id = $1
            """,
            offer_id,
            status,
        )

        if approved:
            await db.execute(
                """
                INSERT INTO hot_offer_history (offer_id, status, offer_payload, notes)
                VALUES ($1, 'active', $2, $3)
                """,
                offer_id,
                row.get("offer_payload"),
                notes,
            )

        try:
            created_at = row.get("created_at")
            if created_at:
                latency_ms = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds() * 1000)
                metrics.timing("neoeats.hot_offer.approval.latency_ms", latency_ms)
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        metrics.increment(f"neoeats.hot_offer.approval.{status}", 1)

        return {"approved": approved, "status": status}


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


async def _load_image_bytes(image_url: Optional[str], image_base64: Optional[str]) -> bytes:
    if image_base64:
        payload = image_base64.split(",")[-1]
        return base64.b64decode(payload)
    if not image_url:
        raise ValueError("VisionAnalyzerBlock requires image_url or image_base64")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(image_url)
        response.raise_for_status()
        return response.content


def _build_vision_prompt(intent: str, extra_prompt: Optional[str] = None) -> str:
    base = (
        "You are an inventory vision assistant. Extract structured data for inventory updates. "
        "Return ONLY JSON with keys: product_name, quantity, unit, expires_at, sku, barcode, confidence, notes. "
        "Use ISO date for expires_at when visible. If not visible, set expires_at to null."
    )
    if intent:
        base += f"\nIntent: {intent}."
    if extra_prompt:
        base += f"\nAdditional instruction: {extra_prompt}."
    return base


def _validate_vision_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    product_name = payload.get("product_name") or payload.get("name")
    quantity = payload.get("quantity")
    unit = payload.get("unit")
    if not product_name or quantity is None or not unit:
        raise ValueError("Vision analysis missing required fields: product_name, quantity, unit")
    payload["product_name"] = product_name
    payload["quantity"] = float(quantity)
    payload["unit"] = unit
    return payload


class VisionIntakeBlock(BlockBase):
    DESCRIPTION = "Store a vision intake request for inventory or storage updates."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "intent": {"type": "string", "description": "inventory_update|storage_update"},
            "image_url": {"type": "string"},
            "image_base64": {"type": "string"},
            "prompt": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["intent"],
        "anyOf": [
            {"required": ["image_url"]},
            {"required": ["image_base64"]},
        ],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "intake_id": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["intake_id", "status"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        intake_id = str(uuid.uuid4())
        intent = str(inputs.get("intent") or "").strip() or "storage_update"
        image_url = inputs.get("image_url")
        image_base64 = inputs.get("image_base64")
        user_id = inputs.get("user_id") or context.get("user_id")
        prompt = inputs.get("prompt")
        metadata = inputs.get("metadata") or {}

        raw_payload = {
            "image_url": image_url,
            "image_base64": "provided" if image_base64 else None,
            "metadata": metadata,
        }

        await db.execute(
            """
            INSERT INTO vision_intake (
                intake_id, user_id, intent, image_url, image_base64, prompt, raw_payload, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'received')
            """,
            intake_id,
            user_id,
            intent,
            image_url,
            image_base64,
            prompt,
            json.dumps(raw_payload),
        )
        return {"intake_id": intake_id, "status": "received"}


class VisionAnalyzerBlock(BlockBase):
    DESCRIPTION = "Analyze a product image with a vision model and extract inventory signals."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "intake_id": {"type": "string"},
            "image_url": {"type": "string"},
            "image_base64": {"type": "string"},
            "intent": {"type": "string"},
            "prompt": {"type": "string"},
            "model_name": {"type": "string"},
            "mock_analysis": {"type": "object"},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "analysis": {"type": "object"},
            "confidence": {"type": "number"},
            "model_name": {"type": "string"},
        },
        "required": ["analysis"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        intake_id = inputs.get("intake_id")
        intent = inputs.get("intent")
        prompt = inputs.get("prompt")
        image_url = inputs.get("image_url")
        image_base64 = inputs.get("image_base64")
        model_name = inputs.get("model_name") or os.getenv("SEED_GEMINI_VISION_MODEL") or "gemini-1.5-flash"

        stored = None
        if intake_id:
            stored = await db.fetchrow(
                """
                SELECT intake_id, intent, image_url, image_base64, prompt
                FROM vision_intake
                WHERE intake_id = $1
                """,
                intake_id,
            )

        if stored:
            intent = intent or stored.get("intent")
            image_url = image_url or stored.get("image_url")
            image_base64 = image_base64 or stored.get("image_base64")
            prompt = prompt or stored.get("prompt")

        if inputs.get("mock_analysis"):
            analysis = _validate_vision_payload(dict(inputs.get("mock_analysis") or {}))
            confidence = float(analysis.get("confidence") or 0.0)
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")
            if not Image:
                raise RuntimeError("Pillow is required for vision analysis")

            gemini = _build_gemini_client(api_key=api_key, default_model=model_name)
            image_bytes = await _load_image_bytes(image_url, image_base64)
            image = Image.open(io.BytesIO(image_bytes))
            vision_prompt = _build_vision_prompt(intent or "", prompt)

            def _run_call() -> str:
                return gemini.generate_content([vision_prompt, image], model=model_name)

            text = await asyncio.to_thread(_run_call)
            parsed = json.loads(_strip_json_fence(text))
            analysis = _validate_vision_payload(parsed)
            confidence = float(analysis.get("confidence") or 0.0)

        if intake_id:
            await db.execute(
                """
                UPDATE vision_intake
                SET analysis = $2, confidence = $3, model_name = $4, status = 'analyzed', updated_at = now()
                WHERE intake_id = $1
                """,
                intake_id,
                json.dumps(analysis),
                confidence,
                model_name,
            )

        return {"analysis": analysis, "confidence": confidence, "model_name": model_name}


class VisionConfirmationBlock(BlockBase):
    DESCRIPTION = "Confirm or reject vision analysis before applying updates."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "intake_id": {"type": "string"},
            "approved": {"type": "boolean"},
            "notes": {"type": "string"},
        },
        "required": ["intake_id", "approved"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "accepted": {"type": "boolean"},
            "status": {"type": "string"},
        },
        "required": ["accepted", "status"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        intake_id = inputs.get("intake_id")
        approved = bool(inputs.get("approved"))
        notes = inputs.get("notes")
        status = "approved" if approved else "rejected"

        await db.execute(
            """
            UPDATE vision_intake
            SET status = $2, confirmation_notes = $3, updated_at = now()
            WHERE intake_id = $1
            """,
            intake_id,
            status,
            notes,
        )
        return {"accepted": approved, "status": status}


class VisionApplyUpdateBlock(BlockBase):
    DESCRIPTION = "Apply confirmed vision analysis to storage or inventory."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "intake_id": {"type": "string"},
            "analysis": {"type": "object"},
            "target": {"type": "string", "description": "storage|inventory"},
            "approved": {"type": "boolean"},
        },
        "required": ["intake_id"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "applied": {"type": "boolean"},
            "storage_id": {"type": "string"},
            "lot_id": {"type": "string"},
        },
        "required": ["applied"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        db = _require_db(self._engine)
        intake_id = inputs.get("intake_id")
        approved = inputs.get("approved")

        row = await db.fetchrow(
            """
            SELECT intent, analysis, status
            FROM vision_intake
            WHERE intake_id = $1
            """,
            intake_id,
        )
        if not row:
            raise ValueError("Vision intake not found")

        if approved is False or row.get("status") == "rejected":
            return {"applied": False}

        analysis = inputs.get("analysis") or row.get("analysis")
        if isinstance(analysis, str):
            analysis = json.loads(analysis)
        if not isinstance(analysis, dict):
            raise ValueError("VisionApplyUpdateBlock requires analysis payload")

        analysis = _validate_vision_payload(dict(analysis))
        target = inputs.get("target") or ("inventory" if row.get("intent") == "inventory_update" else "storage")

        if target == "inventory":
            item_id = analysis.get("item_id")
            if not item_id:
                item_id = await db.fetchval(
                    "SELECT item_id FROM inventory_item WHERE lower(name) = lower($1) LIMIT 1",
                    analysis.get("product_name"),
                )
            if not item_id:
                raise ValueError("Inventory item not found for vision update")

            lot_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO inventory_lot (lot_id, item_id, expires_at, quantity_total, quantity_available)
                VALUES ($1, $2, $3, $4, $4)
                """,
                lot_id,
                item_id,
                analysis.get("expires_at"),
                float(analysis.get("quantity")),
            )
            await db.execute(
                """
                UPDATE vision_intake
                SET status = 'applied', updated_at = now()
                WHERE intake_id = $1
                """,
                intake_id,
            )
            _invalidate_inventory_cache(self._engine)
            return {"applied": True, "lot_id": lot_id}

        storage_id = str(uuid.uuid4())
        await db.execute(
            """
            INSERT INTO storage_item (storage_id, name, quantity, unit, expires_at, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            storage_id,
            analysis.get("product_name"),
            float(analysis.get("quantity")),
            analysis.get("unit"),
            analysis.get("expires_at"),
            json.dumps({"source": "vision", "analysis": analysis}),
        )
        await db.execute(
            """
            UPDATE vision_intake
            SET status = 'applied', updated_at = now()
            WHERE intake_id = $1
            """,
            intake_id,
        )
        return {"applied": True, "storage_id": storage_id}
