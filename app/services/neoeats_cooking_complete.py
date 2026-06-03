from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class CookingConsumption:
    pantry_item_id: str
    name: str
    quantity: float
    unit: str


def _positive_float(value: Any, default: float = 1.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def group_cooking_consumption(raw_items: Iterable[Any]) -> Tuple[List[CookingConsumption], List[Dict[str, Any]]]:
    groups: Dict[str, CookingConsumption] = {}
    units_by_pantry_id: Dict[str, str] = {}
    failed: List[Dict[str, Any]] = []

    for entry in raw_items:
        if not isinstance(entry, dict):
            continue

        pantry_item_id = _clean_text(entry.get("pantry_item_id") or entry.get("item_id"))
        name = _clean_text(entry.get("name"), "ingredient")
        unit = _clean_text(entry.get("unit"), "pcs").lower()
        quantity = _positive_float(entry.get("quantity"), 1.0)

        if not pantry_item_id:
            failed.append({"name": name, "reason": "missing_pantry_item_id"})
            continue

        previous_unit = units_by_pantry_id.get(pantry_item_id)
        if previous_unit and previous_unit != unit:
            failed.append({
                "pantry_item_id": pantry_item_id,
                "name": name,
                "reason": "mixed_units_for_same_pantry_item",
            })
            continue
        units_by_pantry_id[pantry_item_id] = unit

        existing = groups.get(pantry_item_id)
        if existing:
            groups[pantry_item_id] = CookingConsumption(
                pantry_item_id=pantry_item_id,
                name=existing.name,
                quantity=round(existing.quantity + quantity, 4),
                unit=unit,
            )
            continue

        groups[pantry_item_id] = CookingConsumption(
            pantry_item_id=pantry_item_id,
            name=name,
            quantity=quantity,
            unit=unit,
        )

    return list(groups.values()), failed


def decide_consumption_action(
    *,
    current_quantity: Any,
    current_unit: Any,
    requested_quantity: float,
    requested_unit: str,
) -> Dict[str, Any]:
    current_qty = _positive_float(current_quantity, 0.0)
    current_unit_norm = _clean_text(current_unit).lower()
    requested_unit_norm = _clean_text(requested_unit, "pcs").lower()

    if current_unit_norm != requested_unit_norm:
        return {
            "action": "failed",
            "reason": "unit_mismatch",
            "current_unit": current_unit_norm,
            "requested_unit": requested_unit_norm,
        }

    if current_qty > requested_quantity:
        return {
            "action": "update",
            "next_quantity": round(current_qty - requested_quantity, 4),
        }

    return {"action": "delete"}
