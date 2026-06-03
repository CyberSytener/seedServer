from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

from app.services.pantry_normalizer import (
    canonicalize_product,
    extract_items_from_message,
    normalize_quantity_unit,
)


_COOKING_MARKERS = {
    "cook",
    "recipe",
    "recipes",
    "dinner",
    "lunch",
    "breakfast",
    "meal",
    "dish",
    "recommend",
    "suggest",
}

_INVENTORY_MARKERS = {
    "add",
    "added",
    "bought",
    "buy",
    "got",
    "have",
    "fridge",
    "pantry",
    "inventory",
    "receipt",
    "scan",
    "milk",
    "eggs",
    "bread",
    "chicken",
    "rice",
    "tomato",
    "tomatoes",
}

_UNIT_MARKER_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|gram|grams|l|liter|litre|ml|pcs|pc|piece|pieces|pack|bottle|can)\b",
    flags=re.IGNORECASE,
)


def _confidence_percent(value: Any, default: float = 82.0) -> float:
    try:
        raw = float(value)
    except Exception:
        raw = default
    if raw <= 1.0:
        raw *= 100.0
    return max(0.0, min(100.0, raw))


def _looks_like_sentence_food_name(value: str) -> bool:
    words = [part for part in str(value or "").split() if part]
    if len(words) > 5:
        return True
    lowered = str(value or "").lower().strip()
    if any(marker in lowered.split() for marker in _COOKING_MARKERS):
        return True
    return False


def _apply_default_food_quantity(display_name: str, quantity: float, unit: str) -> tuple[float, str]:
    lowered = str(display_name or "").lower()
    if unit != "pcs" or quantity != 1.0:
        return quantity, unit
    if any(token in lowered for token in ("milk", "juice", "cream", "kefir")):
        return 1.0, "l"
    if any(token in lowered for token in ("rice", "pasta", "flour", "sugar", "oats")):
        return 1.0, "kg"
    if any(token in lowered for token in ("chicken", "beef", "pork", "fish", "salmon", "turkey", "shrimp")):
        return 500.0, "g"
    if any(token in lowered for token in ("cheese", "ham", "bacon", "butter")):
        return 200.0, "g"
    if "egg" in lowered:
        return 6.0, "pcs"
    if "bread" in lowered:
        return 1.0, "loaf"
    return quantity, unit


def looks_like_inventory_text(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    words = set(re.findall(r"[\w'-]+", text))
    if words & _COOKING_MARKERS and not (words & _INVENTORY_MARKERS):
        return False
    if words & _INVENTORY_MARKERS:
        return True
    if _UNIT_MARKER_RE.search(text):
        return True
    if "," in text or "&" in text or re.search(r"\band\b", text):
        return True
    return len(words) <= 3


def normalize_inventory_items(raw_items: Iterable[Any]) -> List[Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}

    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        raw_name = str(entry.get("canonical_name") or entry.get("name") or entry.get("product_name") or "").strip()
        if not raw_name or _looks_like_sentence_food_name(raw_name):
            continue

        brand = str(entry.get("brand") or "").strip() or None
        original_name = str(entry.get("original_name") or entry.get("display_name") or entry.get("name") or raw_name).strip()
        canonicalized = canonicalize_product(raw_name, brand=brand, preferred_language="en")
        canonical_name = str(canonicalized.get("canonical_name") or raw_name).strip().lower()
        display_name = original_name or str(canonicalized.get("display_name") or canonical_name or raw_name).strip()
        if not display_name or _looks_like_sentence_food_name(display_name):
            continue

        quantity, unit = normalize_quantity_unit(
            entry.get("quantity"),
            entry.get("unit"),
            name=display_name,
        )
        quantity, unit = _apply_default_food_quantity(display_name, quantity, unit)
        expiry_date = entry.get("expiry_date") if entry.get("expiry_date") is not None else entry.get("expires_at")
        confidence = _confidence_percent(entry.get("confidence") or entry.get("confidence_score") or 0.82)
        key = f"{canonical_name}::{unit}"
        existing = normalized.get(key)
        if existing:
            existing["quantity"] = float(existing.get("quantity") or 0.0) + quantity
            existing["confidence"] = max(float(existing.get("confidence") or 0.0), confidence)
            existing["confidence_score"] = float(existing["confidence"]) / 100.0
            continue

        normalized[key] = {
            "name": display_name,
            "canonical_name": canonical_name,
            "display_name": display_name,
            "category": entry.get("category") or canonicalized.get("category"),
            "quantity": quantity,
            "unit": unit,
            "expiry_date": expiry_date,
            "expires_at": expiry_date,
            "confidence": confidence,
            "confidence_score": confidence / 100.0,
            "brand": brand,
            "original_name": original_name,
        }

    return list(normalized.values())


def _extract_with_llm(
    *,
    llm_engine: Any,
    message: str,
    user_inventory: Optional[List[Dict[str, Any]]] = None,
    store_inventory: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if llm_engine is None:
        return []

    try:
        result = llm_engine.orchestrate_chat(
            message=f"Add these pantry items only. Do not recommend recipes: {message}",
            user_inventory=user_inventory or [],
            store_inventory=store_inventory or [],
            user_taste_profile={},
            context={"goal": "inventory_quick_add"},
        )
    except Exception:
        logging.exception("NeoEats inventory extraction LLM call failed")
        return []

    if not isinstance(result, dict):
        return []
    return normalize_inventory_items(result.get("detected_items") or [])


def extract_inventory_items(
    message: str,
    *,
    llm_engine: Any = None,
    structured_items: Optional[Iterable[Any]] = None,
    user_inventory: Optional[List[Dict[str, Any]]] = None,
    store_inventory: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if structured_items is not None:
        normalized_structured = normalize_inventory_items(structured_items)
        if normalized_structured:
            return normalized_structured

    text = str(message or "").strip()
    if not looks_like_inventory_text(text):
        return []

    llm_items = _extract_with_llm(
        llm_engine=llm_engine,
        message=text,
        user_inventory=user_inventory,
        store_inventory=store_inventory,
    )
    if llm_items:
        return llm_items

    return normalize_inventory_items(extract_items_from_message(text))


def build_inventory_extract_response(
    message: str,
    *,
    llm_engine: Any = None,
    structured_items: Optional[Iterable[Any]] = None,
    user_inventory: Optional[List[Dict[str, Any]]] = None,
    store_inventory: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    items = extract_inventory_items(
        message,
        llm_engine=llm_engine,
        structured_items=structured_items,
        user_inventory=user_inventory,
        store_inventory=store_inventory,
    )
    item_names = [str(item.get("name") or "").strip() for item in items if str(item.get("name") or "").strip()]
    persona_message = (
        f"Detected {len(item_names)} pantry item{'s' if len(item_names) != 1 else ''}: {', '.join(item_names)}."
        if item_names
        else "No pantry items detected."
    )
    pantry_updates = [
        {
            "name": item["name"],
            "quantity": item["quantity"],
            "unit": item["unit"],
        }
        for item in items
    ]

    return {
        "persona_message": persona_message,
        "items": items,
        "detected_items": items,
        "pantry_updates": pantry_updates,
        "inventory_persisted": False,
        "recommendations": [],
        "flavor_architect": [],
    }
