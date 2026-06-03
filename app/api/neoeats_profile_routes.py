from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.auth import authenticate, require_admin_key
from app.infrastructure.db.sqlite import DB
from app.services.neoeats_memory_controls import (
    clear_structured_memory,
    memory_learning_enabled,
    memory_controls_from_meta,
    memory_retrieval_enabled,
    patch_memory_controls,
)
from app.services.neoeats_rag_memory import (
    backfill_memory_event_embeddings,
    backfill_memory_event_embeddings_for_all_users,
    delete_memory_events,
    embedding_provider_available,
    export_memory_events,
    memory_embedding_global_stats,
    memory_context_from_events,
    memory_event_stats,
    record_memory_event,
    retrieve_memory_events,
)
from app.services.product_normalize import _normalize_product_name


DEFAULT_NOTIFICATIONS = {
    "hot_offer_alerts": True,
    "ai_suggestions": True,
    "order_status": True,
    "sustainability_milestones": False,
}

DEFAULT_PREFERENCES = {
    "spiciness": 35,
    "protein_focus": 35,
    "cyber_fusion": 20,
    "vegan_preference": 0,
    "local_ingredients": 35,
}

DEFAULT_DIETARY_PROFILE = {
    "diet_tags": [],
    "allergies": [],
    "avoided_ingredients": [],
    "goals": [],
    "favorite_cuisines": [],
    "likes": [],
}

MAX_LAUNCH_EVENTS = 250
MAX_MISSING_LISTS = 50
MAX_MISSING_LIST_ITEMS = 40
FOOD_LAUNCH_EVENT_TYPES = {"first_food_added", "food_added", "receipt_confirmed"}
MISSING_LIST_SOURCES = {"explore", "fridge", "chat", "recipe_brain"}

LAUNCH_EVENT_TYPES = {
    "registration_completed",
    "first_food_added",
    "food_added",
    "live_scan_used",
    "receipt_confirmed",
    "recommendation_requested",
    "recommendation_succeeded",
    "recommendation_failed",
    "recommendation_feedback",
    "missing_list_saved",
    "missing_list_confirmed",
    "recipe_saved",
    "cooking_started",
    "cooking_completed",
    "profile_food_rules_updated",
}


def _embedding_provider_from_app(app: Any) -> Any:
    return getattr(app.state, "llm_engine", None)


def _embedding_model_from_provider(provider: Any) -> str:
    return str(getattr(provider, "embedding_model", "text-embedding-004") or "text-embedding-004")


def _parse_embedding_statuses(value: str | None) -> List[str] | None:
    if not value:
        return None
    statuses = [
        item.strip().lower()
        for item in str(value).replace(";", ",").split(",")
        if item.strip()
    ]
    return statuses or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _safe_launch_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return str(value)[:160]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        return value.strip()[:240]
    if isinstance(value, list):
        return [_safe_launch_value(item, depth=depth + 1) for item in value[:24]]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in list(value.items())[:24]:
            normalized_key = str(key or "").strip().lower().replace(" ", "_")[:80]
            if normalized_key:
                out[normalized_key] = _safe_launch_value(item, depth=depth + 1)
        return out
    return str(value)[:160]


def _normalize_launch_event_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(raw.get("event_type") or raw.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if event_type not in LAUNCH_EVENT_TYPES:
        raise HTTPException(status_code=400, detail="invalid_launch_event_type")

    payload_source = raw.get("payload") if isinstance(raw.get("payload"), dict) else {
        key: value
        for key, value in raw.items()
        if key not in {"event_type", "type", "created_at", "id"}
    }
    payload = _safe_launch_value(payload_source)
    return {
        "event_type": event_type,
        "payload": payload if isinstance(payload, dict) else {},
    }


def _launch_events_from_meta(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = meta.get("neoeats_launch_events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _append_launch_event(meta: Dict[str, Any], event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    events = _launch_events_from_meta(meta)
    has_prior_food_signal = any(
        str(event.get("event_type") or "").strip() in FOOD_LAUNCH_EVENT_TYPES
        for event in events
    )
    if event_type == "food_added" and not has_prior_food_signal:
        event_type = "first_food_added"
    elif event_type == "first_food_added" and has_prior_food_signal:
        event_type = "food_added"

    event = {
        "id": f"launch_{uuid.uuid4().hex}",
        "event_type": event_type,
        "payload": payload,
        "created_at": _now_iso(),
    }
    events.append(event)
    meta["neoeats_launch_events"] = events[-MAX_LAUNCH_EVENTS:]
    return event


def _launch_event_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    first_seen: Dict[str, str] = {}
    last_seen: Dict[str, str] = {}
    for event in events:
        event_type = str(event.get("event_type") or "").strip()
        if not event_type:
            continue
        created_at = str(event.get("created_at") or "")
        counts[event_type] = counts.get(event_type, 0) + 1
        if created_at and event_type not in first_seen:
            first_seen[event_type] = created_at
        if created_at:
            last_seen[event_type] = created_at

    has_food_signal = any(key in counts for key in FOOD_LAUNCH_EVENT_TYPES)
    has_recommendation_signal = any(
        key in counts
        for key in (
            "recommendation_succeeded",
            "recommendation_requested",
            "recipe_saved",
        )
    )
    activated = has_food_signal and has_recommendation_signal
    return {
        "event_count": len(events),
        "by_event_type": counts,
        "first_seen_at": first_seen,
        "last_seen_at": last_seen,
        "activated": activated,
    }


def _missing_lists_from_meta(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    drafts = meta.get("neoeats_missing_lists")
    if not isinstance(drafts, list):
        return []
    return [draft for draft in drafts if isinstance(draft, dict)]


def _clean_missing_list_text(value: Any, *, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _positive_number(value: Any, *, default: float = 1.0, upper: float = 9999.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed != parsed or parsed <= 0:
        return default
    return min(parsed, upper)


def _normalize_missing_list_item(raw: Any) -> Dict[str, Any] | None:
    if isinstance(raw, str):
        name = _clean_missing_list_text(raw, limit=120)
        return {"name": name, "quantity": 1, "unit": "pcs"} if name else None
    if not isinstance(raw, dict):
        return None

    name = _clean_missing_list_text(raw.get("name") or raw.get("item_name"), limit=120)
    if not name:
        return None
    quantity = _positive_number(raw.get("quantity"), default=1.0)
    item: Dict[str, Any] = {
        "name": name,
        "quantity": int(quantity) if quantity.is_integer() else round(quantity, 3),
        "unit": _clean_missing_list_text(raw.get("unit") or "pcs", limit=32) or "pcs",
    }
    try:
        price = float(raw.get("price") if raw.get("price") is not None else raw.get("price_est"))
    except Exception:
        price = None
    if price is not None and price == price and price >= 0:
        item["price"] = round(min(price, 999999.0), 2)

    for source_key, target_key, limit in (
        ("catalog_item_id", "catalog_item_id", 120),
        ("product_id", "catalog_item_id", 120),
        ("sku", "sku", 80),
        ("category", "category", 80),
        ("currency", "currency", 8),
    ):
        text = _clean_missing_list_text(raw.get(source_key), limit=limit)
        if text and target_key not in item:
            item[target_key] = text
    return item


def _normalize_missing_list_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    source = _clean_missing_list_text(raw.get("source") or "chat", limit=40).lower().replace("-", "_").replace(" ", "_")
    if source not in MISSING_LIST_SOURCES:
        raise HTTPException(status_code=400, detail="invalid_missing_list_source")

    recipe_id = _clean_missing_list_text(raw.get("recipe_id") or raw.get("recipeId") or raw.get("id"), limit=160)
    recipe_name = _clean_missing_list_text(raw.get("recipe_name") or raw.get("recipeName") or raw.get("name") or raw.get("title"), limit=180)
    if not recipe_id and not recipe_name:
        raise HTTPException(status_code=400, detail="missing_list_recipe_required")

    raw_items = raw.get("missing_items") if "missing_items" in raw else raw.get("missingItems")
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="missing_items_required")
    items = [
        item
        for item in (_normalize_missing_list_item(entry) for entry in raw_items[:MAX_MISSING_LIST_ITEMS])
        if item
    ]
    if not items:
        raise HTTPException(status_code=400, detail="missing_items_required")

    return {
        "source": source,
        "recipe_id": recipe_id or f"recipe_{uuid.uuid4().hex[:12]}",
        "recipe_name": recipe_name or "Untitled recipe",
        "missing_items": items,
        "currency": _clean_missing_list_text(raw.get("currency") or "NOK", limit=8).upper() or "NOK",
        "notes": _clean_missing_list_text(raw.get("notes"), limit=400) or None,
    }


def _normalize_store_catalog_row(raw: Dict[str, Any]) -> Dict[str, Any] | None:
    item_id = _clean_missing_list_text(raw.get("item_id") or raw.get("id"), limit=160)
    name = _clean_missing_list_text(raw.get("name"), limit=160)
    if not item_id and not name:
        return None
    out: Dict[str, Any] = {
        "item_id": item_id or f"catalog_{uuid.uuid4().hex[:12]}",
        "sku": _clean_missing_list_text(raw.get("sku"), limit=80) or None,
        "name": name,
        "name_norm": _normalize_product_name(name),
        "category": _clean_missing_list_text(raw.get("category"), limit=80) or None,
        "unit": _clean_missing_list_text(raw.get("unit"), limit=32) or None,
        "quantity_available": 0.0,
        "last_price_paid": None,
    }
    try:
        out["quantity_available"] = max(0.0, float(raw.get("quantity_available") or 0.0))
    except Exception:
        out["quantity_available"] = 0.0
    try:
        price = float(raw.get("last_price_paid") if raw.get("last_price_paid") is not None else raw.get("price"))
    except Exception:
        price = None
    if price is not None and price == price and price >= 0:
        out["last_price_paid"] = round(price, 2)
    return out


async def _load_store_catalog_items(
    get_neoeats_db: Callable[..., Awaitable[Any]],
    app: Any,
) -> List[Dict[str, Any]]:
    try:
        neoeats_db = await get_neoeats_db(app)
        rows = await neoeats_db.fetch(
            """
            SELECT ii.item_id,
                   ii.sku,
                   ii.name,
                   ii.category,
                   ii.unit,
                   ii.last_price_paid,
                   COALESCE(SUM(il.quantity_available), 0) AS quantity_available
            FROM inventory_item ii
            LEFT JOIN inventory_lot il ON il.item_id = ii.item_id
            WHERE ii.is_active = true
            GROUP BY ii.item_id, ii.sku, ii.name, ii.category, ii.unit, ii.last_price_paid
            ORDER BY ii.name
            """,
        )
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows or []:
        item = _normalize_store_catalog_row(dict(row))
        if not item:
            continue
        key = str(item.get("item_id") or item.get("name_norm") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _missing_list_catalog_match(item: Dict[str, Any], catalog_items: List[Dict[str, Any]]) -> tuple[Dict[str, Any] | None, float]:
    item_id = _clean_missing_list_text(item.get("catalog_item_id"), limit=160)
    sku = _clean_missing_list_text(item.get("sku"), limit=80).lower()
    name_norm = _normalize_product_name(item.get("name") or "")
    name_tokens = {token for token in name_norm.split(" ") if len(token) >= 3}

    for catalog in catalog_items:
        if item_id and item_id == str(catalog.get("item_id") or ""):
            return catalog, 1.0
        if sku and sku == str(catalog.get("sku") or "").lower():
            return catalog, 1.0

    for catalog in catalog_items:
        if name_norm and name_norm == str(catalog.get("name_norm") or ""):
            return catalog, 0.96

    best: tuple[Dict[str, Any] | None, float] = (None, 0.0)
    for catalog in catalog_items:
        candidate_norm = str(catalog.get("name_norm") or "")
        if not name_norm or not candidate_norm:
            continue
        confidence = 0.0
        if name_norm in candidate_norm or candidate_norm in name_norm:
            confidence = 0.82
        else:
            candidate_tokens = {token for token in candidate_norm.split(" ") if len(token) >= 3}
            if name_tokens and candidate_tokens:
                overlap = len(name_tokens.intersection(candidate_tokens)) / max(len(name_tokens), len(candidate_tokens))
                if overlap >= 0.5:
                    confidence = 0.62 + min(0.2, overlap * 0.2)
        if confidence > best[1]:
            best = (catalog, confidence)
    return best if best[1] >= 0.62 else (None, 0.0)


def _enrich_missing_list_payload(normalized: Dict[str, Any], catalog_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not catalog_items:
        normalized["catalog_source"] = "unavailable"
        normalized["catalog_match_count"] = 0
        normalized["catalog_unmatched_count"] = len(normalized["missing_items"])
        normalized["catalog_available_count"] = 0
        return normalized

    enriched_items: List[Dict[str, Any]] = []
    match_count = 0
    available_count = 0
    for item in normalized["missing_items"]:
        enriched = dict(item)
        match, confidence = _missing_list_catalog_match(enriched, catalog_items)
        if match:
            match_count += 1
            available = float(match.get("quantity_available") or 0.0)
            if available > 0:
                available_count += 1
            enriched.update(
                {
                    "catalog_item_id": str(match.get("item_id") or ""),
                    "catalog_name": str(match.get("name") or enriched.get("name") or ""),
                    "sku": match.get("sku") or enriched.get("sku"),
                    "category": match.get("category") or enriched.get("category"),
                    "catalog_unit": match.get("unit"),
                    "quantity_available": available,
                    "stock_available": available > 0,
                    "match_status": "matched",
                    "match_confidence": round(confidence, 2),
                }
            )
            if enriched.get("price") is None and match.get("last_price_paid") is not None:
                enriched["price"] = match["last_price_paid"]
        else:
            enriched.update(
                {
                    "quantity_available": 0.0,
                    "stock_available": False,
                    "match_status": "unmatched",
                    "match_confidence": 0.0,
                }
            )
        enriched_items.append(enriched)

    normalized["missing_items"] = enriched_items
    normalized["catalog_source"] = "inventory_item"
    normalized["catalog_match_count"] = match_count
    normalized["catalog_unmatched_count"] = len(enriched_items) - match_count
    normalized["catalog_available_count"] = available_count
    normalized["catalog_enriched_at"] = _now_iso()
    return normalized


def _missing_list_summary(drafts: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_source: Dict[str, int] = {}
    total_items = 0
    active = 0
    for draft in drafts:
        source = str(draft.get("source") or "unknown")
        by_source[source] = by_source.get(source, 0) + 1
        total_items += int(draft.get("item_count") or len(draft.get("missing_items") or []))
        if str(draft.get("status") or "draft") == "draft":
            active += 1
    return {
        "draft_count": len(drafts),
        "active_count": active,
        "total_missing_items": total_items,
        "by_source": by_source,
    }


def _upsert_missing_list(meta: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Any]:
    drafts = _missing_lists_from_meta(meta)
    now = _now_iso()
    existing = next(
        (
            draft
            for draft in drafts
            if str(draft.get("source") or "") == normalized["source"]
            and str(draft.get("recipe_id") or "") == normalized["recipe_id"]
        ),
        None,
    )
    total_estimate = round(
        sum(float(item.get("price") or 0.0) * float(item.get("quantity") or 1) for item in normalized["missing_items"]),
        2,
    )
    draft = {
        "id": str(existing.get("id")) if existing else f"missing_{uuid.uuid4().hex}",
        "source": normalized["source"],
        "recipe_id": normalized["recipe_id"],
        "recipe_name": normalized["recipe_name"],
        "missing_items": normalized["missing_items"],
        "item_count": len(normalized["missing_items"]),
        "total_estimate": total_estimate,
        "currency": normalized["currency"],
        "status": "draft",
        "notes": normalized.get("notes"),
        "catalog_source": normalized.get("catalog_source") or "unavailable",
        "catalog_match_count": int(normalized.get("catalog_match_count") or 0),
        "catalog_unmatched_count": int(normalized.get("catalog_unmatched_count") or 0),
        "catalog_available_count": int(normalized.get("catalog_available_count") or 0),
        "catalog_enriched_at": normalized.get("catalog_enriched_at"),
        "created_at": str(existing.get("created_at")) if existing and existing.get("created_at") else now,
        "updated_at": now,
    }
    next_drafts = [
        item
        for item in drafts
        if not (
            str(item.get("source") or "") == normalized["source"]
            and str(item.get("recipe_id") or "") == normalized["recipe_id"]
        )
    ]
    meta["neoeats_missing_lists"] = [draft, *next_drafts][:MAX_MISSING_LISTS]
    return draft


def _clamp_percent(value: Any, default: int) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except Exception:
        return default


def _merge_percent_map(current: Dict[str, Any], defaults: Dict[str, int]) -> Dict[str, int]:
    return {key: _clamp_percent(current.get(key), fallback) for key, fallback in defaults.items()}


def _coerce_bool_map(current: Dict[str, Any], defaults: Dict[str, bool]) -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    for key, fallback in defaults.items():
        value = current.get(key)
        result[key] = bool(value) if isinstance(value, bool) else fallback
    return result


def _string_list(value: Any, *, limit: int = 20) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for entry in value[:limit]:
        text = str(entry or "").strip()
        if text:
            out.append(text[:120])
    return out


def _normalized_tag_list(value: Any, *, limit: int = 20) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for entry in value[: limit * 2]:
        text = str(entry or "").strip().lower().replace("-", "_").replace(" ", "_")
        text = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "/"})[:80]
        if text and text not in seen:
            out.append(text)
            seen.add(text)
        if len(out) >= limit:
            break
    return out


def _merge_unique_lists(*values: List[str], limit: int = 20) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value:
            text = str(item or "").strip().lower().replace("-", "_").replace(" ", "_")
            if text and text not in seen:
                out.append(text[:80])
                seen.add(text)
            if len(out) >= limit:
                return out
    return out


def _normalize_dietary_profile(raw: Dict[str, Any] | None, *, base: Dict[str, Any] | None = None) -> Dict[str, Any]:
    current = base if isinstance(base, dict) else {}
    source = raw if isinstance(raw, dict) else {}
    profile: Dict[str, Any] = {}
    for key, fallback_limit in (
        ("diet_tags", 12),
        ("allergies", 20),
        ("avoided_ingredients", 24),
        ("goals", 16),
        ("favorite_cuisines", 16),
        ("likes", 24),
    ):
        value = source[key] if key in source else current.get(key)
        profile[key] = _normalized_tag_list(value, limit=fallback_limit)
    if current.get("updated_at") and "updated_at" not in profile:
        profile["updated_at"] = str(current.get("updated_at"))
    return profile


def _build_dietary_profile(meta: Dict[str, Any]) -> Dict[str, Any]:
    profile = meta.get("neoeats_profile") if isinstance(meta.get("neoeats_profile"), dict) else {}
    stored = profile.get("dietary_profile") if isinstance(profile.get("dietary_profile"), dict) else {}
    explicit = _normalize_dietary_profile(stored)
    signals = _memory_signals(meta)
    dietary = {
        "diet_tags": _merge_unique_lists(explicit["diet_tags"], signals.get("diet_tags") or [], limit=12),
        "allergies": explicit["allergies"],
        "avoided_ingredients": _merge_unique_lists(
            explicit["avoided_ingredients"],
            signals.get("constraints") or [],
            limit=24,
        ),
        "goals": _merge_unique_lists(explicit["goals"], signals.get("goals") or [], limit=16),
        "favorite_cuisines": _merge_unique_lists(
            explicit["favorite_cuisines"],
            signals.get("cuisines") or [],
            limit=16,
        ),
        "likes": _merge_unique_lists(explicit["likes"], signals.get("likes") or [], limit=24),
    }
    if stored.get("updated_at"):
        dietary["updated_at"] = str(stored.get("updated_at"))
    return dietary


def _ingredient_summary(value: Any, *, limit: int = 24) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in value[:limit]:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name[:120],
                    "status": str(entry.get("status") or "").strip()[:40] or None,
                    "category": str(entry.get("category") or "").strip()[:80] or None,
                }
            )
        else:
            name = str(entry or "").strip()
            if name:
                out.append({"name": name[:120]})
    return out


def _normalize_recipe_feedback_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    feedback_raw = str(raw.get("feedback") or raw.get("feedback_type") or raw.get("action") or "").strip().lower()
    feedback_aliases = {
        "accept": "accepted",
        "accepted": "accepted",
        "like": "accepted",
        "liked": "accepted",
        "save": "accepted",
        "saved": "accepted",
        "start": "accepted",
        "started": "accepted",
        "started_cooking": "accepted",
        "ordered_missing": "accepted",
        "mark_all_owned": "accepted",
        "marked_all_owned": "accepted",
        "reject": "rejected",
        "rejected": "rejected",
        "dislike": "rejected",
        "disliked": "rejected",
        "not_for_me": "rejected",
        "dismissed": "rejected",
    }
    feedback = feedback_aliases.get(feedback_raw)
    if not feedback:
        raise HTTPException(status_code=400, detail="invalid_recipe_feedback")

    action = str(raw.get("action") or feedback_raw or feedback).strip().lower().replace(" ", "_")
    recipe_id = str(raw.get("recipe_id") or raw.get("id") or "").strip()
    recipe_name = str(raw.get("recipe_name") or raw.get("name") or raw.get("title") or "").strip()
    if not recipe_id and not recipe_name:
        raise HTTPException(status_code=400, detail="recipe_identity_required")

    payload: Dict[str, Any] = {
        "recipe_id": recipe_id or None,
        "recipe_name": recipe_name or None,
        "feedback": feedback,
        "action": action,
        "source": str(raw.get("source") or "frontend_recipe_card").strip()[:80],
        "reason": str(raw.get("reason") or "").strip()[:500] or None,
        "reason_code": str(raw.get("reason_code") or raw.get("reasonCode") or "").strip().lower().replace(" ", "_")[:80] or None,
        "reason_tags": _string_list(raw.get("reason_tags") or raw.get("reasonTags"), limit=10),
        "ingredients": _ingredient_summary(raw.get("ingredients")),
        "available_items": _string_list(raw.get("available_items")),
        "missing_items": _string_list(raw.get("missing_items")),
    }
    try:
        rating = int(float(raw.get("rating") or raw.get("rating_value") or raw.get("ratingValue")))
    except Exception:
        rating = None
    if rating is not None:
        payload["rating"] = max(1, min(5, rating))
    for key in ("score", "confidence", "match_score", "price_to_complete"):
        try:
            value = float(raw.get(key))
        except Exception:
            value = None
        if value is not None:
            payload[key] = value
    return payload


def _rank_from_points(points: int) -> tuple[int, str]:
    if points >= 500:
        return 5, "Zero-Waste Hero"
    if points >= 250:
        return 4, "Pantry Strategist"
    if points >= 100:
        return 3, "Freshness Guardian"
    if points >= 25:
        return 2, "Kitchen Starter"
    return 1, "New Pantry"


def _memory_signals(meta: Dict[str, Any]) -> Dict[str, List[str]]:
    memory = meta.get("neoeats_memory") if isinstance(meta.get("neoeats_memory"), dict) else {}
    signals = memory.get("signals") if isinstance(memory.get("signals"), dict) else {}
    normalized: Dict[str, List[str]] = {}
    for key in ("diet_tags", "goals", "cuisines", "likes", "dislikes", "constraints"):
        value = signals.get(key)
        normalized[key] = [str(item).strip().lower() for item in value if str(item).strip()] if isinstance(value, list) else []
    return normalized


def _derive_preferences(meta: Dict[str, Any]) -> Dict[str, int]:
    stored = meta.get("neoeats_profile") if isinstance(meta.get("neoeats_profile"), dict) else {}
    stored_preferences = stored.get("preferences") if isinstance(stored.get("preferences"), dict) else {}
    preferences = _merge_percent_map(stored_preferences, DEFAULT_PREFERENCES)

    if stored_preferences:
        return preferences

    signals = _memory_signals(meta)
    goals = set(signals.get("goals") or [])
    cuisines = set(signals.get("cuisines") or [])
    diet_tags = set(signals.get("diet_tags") or [])
    likes = set(signals.get("likes") or [])
    dietary_profile = _build_dietary_profile(meta)
    goals.update(dietary_profile.get("goals") or [])
    cuisines.update(dietary_profile.get("favorite_cuisines") or [])
    diet_tags.update(dietary_profile.get("diet_tags") or [])
    likes.update(dietary_profile.get("likes") or [])

    if goals.intersection({"high_protein"}):
        preferences["protein_focus"] = 75
    if diet_tags.intersection({"vegan", "vegetarian"}):
        preferences["vegan_preference"] = 85 if "vegan" in diet_tags else 65
    if cuisines.intersection({"indian", "mexican", "asian", "japanese"}) or any("spicy" in item for item in likes):
        preferences["spiciness"] = 70
    if cuisines.intersection({"norwegian"}) or goals.intersection({"zero_waste"}):
        preferences["local_ingredients"] = 70
    if signals.get("likes") or signals.get("cuisines") or signals.get("goals"):
        preferences["cyber_fusion"] = 40

    return preferences


def _build_ai_insights(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    memory = meta.get("neoeats_memory") if isinstance(meta.get("neoeats_memory"), dict) else {}
    signals = _memory_signals(meta)
    facts = memory.get("facts") if isinstance(memory.get("facts"), list) else []
    insights: List[Dict[str, Any]] = []

    for fact in facts:
        if not isinstance(fact, dict):
            continue
        kind = str(fact.get("kind") or "").strip().lower()
        value = str(fact.get("value") or "").strip()
        if not value or kind not in {"diet", "goal", "constraint", "like", "frequent_ingredient"}:
            continue
        category = "preference"
        if kind == "goal":
            category = "recommendation"
        elif kind == "frequent_ingredient":
            category = "behavior"
        elif kind == "constraint":
            category = "preference"
        text_by_kind = {
            "diet": f"Your meal suggestions now respect your {value.replace('_', ' ')} preference.",
            "goal": f"I am prioritizing {value.replace('_', ' ')} choices in your cooking recommendations.",
            "constraint": f"I will avoid {value} when shaping future recommendations.",
            "like": f"I have learned that you like {value}.",
            "frequent_ingredient": f"{value.title()} appears often in your pantry history.",
        }
        insights.append(
            {
                "id": str(fact.get("id") or f"{kind}:{value}")[:80],
                "text": text_by_kind[kind],
                "confidence": _clamp_percent(float(fact.get("confidence") or 0.6) * 100, 60),
                "timestamp": str(fact.get("updated_at") or fact.get("created_at") or _now_iso()),
                "category": category,
            }
        )
        if len(insights) >= 4:
            break

    if not insights and any(signals.values()):
        insights.append(
            {
                "id": "memory-summary",
                "text": "Your profile is being shaped from pantry, chat, and cooking signals.",
                "confidence": 55,
                "timestamp": str(memory.get("updated_at") or _now_iso()),
                "category": "behavior",
            }
        )

    return insights


def _build_profile_payload(row: Any, meta: Dict[str, Any], dashboard: Dict[str, Any] | None = None) -> Dict[str, Any]:
    profile = meta.get("neoeats_profile") if isinstance(meta.get("neoeats_profile"), dict) else {}
    dashboard = dashboard or {}
    sustainability = dashboard.get("sustainability") if isinstance(dashboard.get("sustainability"), dict) else {}
    username = str(profile.get("username") or meta.get("username") or row["id"]).strip() or str(row["id"])

    return {
        "id": str(row["id"]),
        "username": username,
        "email": row["email"],
        "avatar_url": profile.get("avatar_url") if isinstance(profile.get("avatar_url"), str) else None,
        "neural_link_active": True,
        "preferences": _derive_preferences(meta),
        "dietary_profile": _build_dietary_profile(meta),
        "sustainability": {
            "total_waste_saved_kg": float(sustainability.get("total_waste_saved_kg") or 0.0),
            "hot_offers_purchased": int(sustainability.get("hot_offers_purchased") or 0),
            "eco_points": int(sustainability.get("eco_points") or 0),
            "rank_level": int(sustainability.get("rank_level") or 1),
            "rank_title": str(sustainability.get("rank_title") or "New Pantry"),
        },
        "payment_methods": [
            item
            for item in profile.get("payment_methods", [])
            if isinstance(item, dict)
        ] if isinstance(profile.get("payment_methods"), list) else [],
        "notifications": _coerce_bool_map(
            profile.get("notifications") if isinstance(profile.get("notifications"), dict) else {},
            DEFAULT_NOTIFICATIONS,
        ),
        "ai_insights": _build_ai_insights(meta),
        "memory_controls": memory_controls_from_meta(meta),
        "data_sources": {
            "profile": "users.meta_json.neoeats_profile",
            "memory": "users.meta_json.neoeats_memory",
            "memory_controls": "users.meta_json.neoeats_memory_controls",
            "sustainability": "derived_from_neoeats_events",
            "payments": "not_connected",
        },
    }


async def _build_dashboard_payload(user_id: str, get_neoeats_db: Callable[..., Awaitable[Any]], app: Any) -> Dict[str, Any]:
    empty = {
        "inventory": {
            "item_count": 0,
            "freshness_avg_pct": 0,
            "expiring_soon_count": 0,
            "categories": {},
        },
        "orders": {
            "active_count": 0,
            "delivered_count": 0,
            "active_order_description": "No active order right now.",
            "active_chefs": 0,
        },
        "receipts": {
            "count": 0,
            "total_spend": 0.0,
            "currency": "NOK",
            "last_uploaded_at": None,
        },
        "recommendations": {
            "daily_recommendation_description": "Add pantry items to unlock personalized recommendations.",
            "hot_discovery_description": "Your pantry has no urgent expiry signals.",
        },
        "sustainability": {
            "total_waste_saved_kg": 0.0,
            "hot_offers_purchased": 0,
            "eco_points": 0,
            "rank_level": 1,
            "rank_title": "New Pantry",
        },
        "data_sources": {
            "neoeats_db": False,
        },
    }

    try:
        neoeats_db = await get_neoeats_db(app)
    except Exception:
        return empty

    inventory_source_ready = True
    orders_source_ready = True
    receipts_source_ready = True

    try:
        rows = await neoeats_db.fetch(
            """
            SELECT name, quantity, unit, expires_at, metadata
            FROM storage_item
            WHERE (metadata->>'user_id') = $1
            """,
            user_id,
        )
    except Exception:
        rows = []
        inventory_source_ready = False
    inventory_rows = [dict(row) for row in (rows or [])]
    item_count = len(inventory_rows)
    expiring_soon = 0
    freshness_values: List[int] = []
    categories: Dict[str, int] = {}
    estimated_saved_kg = 0.0
    today = datetime.now(timezone.utc).date()

    for item in inventory_rows:
        metadata = _safe_json(item.get("metadata"))
        category = str(metadata.get("category") or "other").strip().lower() or "other"
        categories[category] = categories.get(category, 0) + 1
        expires_at = item.get("expires_at")
        if expires_at:
            expiry_date = expires_at.date() if hasattr(expires_at, "date") else None
            if expiry_date:
                days = (expiry_date - today).days
                if days <= 2:
                    expiring_soon += 1
                freshness_values.append(int(max(0, min(100, (days / 14) * 100))))
        try:
            quantity = float(item.get("quantity") or 0.0)
            unit = str(item.get("unit") or "").strip().lower()
            if unit in {"kg", "l"}:
                estimated_saved_kg += quantity
            elif unit in {"g", "ml"}:
                estimated_saved_kg += quantity / 1000
            elif unit in {"pcs", "pc", "pack"}:
                estimated_saved_kg += quantity * 0.18
        except Exception:
            pass

    try:
        order_rows = await neoeats_db.fetch(
            """
            SELECT state, payload, result, created_at, updated_at
            FROM sagas
            WHERE saga_type = 'neoeats_order'
              AND (payload->>'user_id') = $1
            ORDER BY created_at DESC
            LIMIT 25
            """,
            user_id,
        )
    except Exception:
        order_rows = []
        orders_source_ready = False
    orders = [dict(row) for row in (order_rows or [])]
    active_orders = [row for row in orders if str(row.get("state") or "").upper() != "DELIVERED"]
    delivered_count = len(orders) - len(active_orders)
    active_description = "No active order right now."
    if active_orders:
        payload = _safe_json(active_orders[0].get("payload"))
        order_id = str(payload.get("order_id") or "order")[:8].upper()
        state = str(active_orders[0].get("state") or "pending").replace("_", " ").lower()
        active_description = f"Order {order_id} is {state}."

    try:
        receipt_row = await neoeats_db.fetchrow(
            """
            SELECT COUNT(*) AS count,
                   COALESCE(SUM(total_amount), 0) AS total_spend,
                   MAX(currency) AS currency,
                   MAX(scanned_at) AS last_uploaded_at
            FROM receipts
            WHERE user_id = $1
            """,
            user_id,
        )
    except Exception:
        receipt_row = None
        receipts_source_ready = False
    receipt = dict(receipt_row) if receipt_row else {}
    receipt_count = int(receipt.get("count") or 0)
    eco_points = int(item_count * 8 + receipt_count * 20 + delivered_count * 30 + max(0, expiring_soon) * 5)
    rank_level, rank_title = _rank_from_points(eco_points)
    freshness_avg = round(sum(freshness_values) / len(freshness_values)) if freshness_values else 0

    return {
        "inventory": {
            "item_count": item_count,
            "freshness_avg_pct": freshness_avg,
            "expiring_soon_count": expiring_soon,
            "categories": categories,
        },
        "orders": {
            "active_count": len(active_orders),
            "delivered_count": delivered_count,
            "active_order_description": active_description,
            "active_chefs": 0,
        },
        "receipts": {
            "count": receipt_count,
            "total_spend": float(receipt.get("total_spend") or 0.0),
            "currency": str(receipt.get("currency") or "NOK"),
            "last_uploaded_at": receipt.get("last_uploaded_at").isoformat() if receipt.get("last_uploaded_at") else None,
        },
        "recommendations": {
            "daily_recommendation_description": (
                f"{expiring_soon} pantry items should be used soon."
                if expiring_soon
                else "Add receipts or pantry items to improve recommendations."
            ),
            "hot_discovery_description": (
                "Build a zero-waste meal from expiring pantry items."
                if expiring_soon
                else "Your pantry has no urgent expiry signals."
            ),
        },
        "sustainability": {
            "total_waste_saved_kg": round(max(0.0, estimated_saved_kg), 2),
            "hot_offers_purchased": 0,
            "eco_points": eco_points,
            "rank_level": rank_level,
            "rank_title": rank_title,
        },
        "data_sources": {
            "neoeats_db": True,
            "storage_item": inventory_source_ready,
            "sagas": orders_source_ready,
            "receipts": receipts_source_ready,
        },
    }


def build_neoeats_profile_router(
    *,
    db: DB,
    get_neoeats_db: Callable[..., Awaitable[Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/neoeats", tags=["neoeats", "profile"])

    def _load_user(user_id: str) -> tuple[Any, Dict[str, Any]]:
        row = db.fetchone("SELECT id, email, meta_json FROM users WHERE id = ?", (user_id,))
        if not row:
            raise HTTPException(status_code=404, detail="user_not_found")
        return row, _safe_json(row["meta_json"])

    def _store_launch_event(user_id: str, normalized: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        with db.transaction() as conn:
            row = conn.execute("SELECT id, email, meta_json FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="user_not_found")
            meta = _safe_json(row["meta_json"])
            event = _append_launch_event(
                meta,
                event_type=normalized["event_type"],
                payload=normalized["payload"],
            )
            conn.execute(
                "UPDATE users SET meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), user_id),
            )
        return event, _launch_events_from_meta(meta)

    def _store_missing_list(user_id: str, normalized: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        with db.transaction() as conn:
            row = conn.execute("SELECT id, email, meta_json FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="user_not_found")
            meta = _safe_json(row["meta_json"])
            draft = _upsert_missing_list(meta, normalized)
            _append_launch_event(
                meta,
                event_type="missing_list_saved",
                payload={
                    "source": draft["source"],
                    "recipe_id": draft["recipe_id"],
                    "recipe_name": draft["recipe_name"],
                    "item_count": draft["item_count"],
                    "total_estimate": draft["total_estimate"],
                    "currency": draft["currency"],
                    "catalog_match_count": draft.get("catalog_match_count") or 0,
                    "catalog_available_count": draft.get("catalog_available_count") or 0,
                },
            )
            conn.execute(
                "UPDATE users SET meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), user_id),
            )
        return draft, _missing_lists_from_meta(meta), _launch_events_from_meta(meta)

    def _delete_missing_list(user_id: str, draft_id: str) -> List[Dict[str, Any]]:
        with db.transaction() as conn:
            row = conn.execute("SELECT id, email, meta_json FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="user_not_found")
            meta = _safe_json(row["meta_json"])
            drafts = _missing_lists_from_meta(meta)
            next_drafts = [draft for draft in drafts if str(draft.get("id") or "") != draft_id]
            if len(next_drafts) == len(drafts):
                raise HTTPException(status_code=404, detail="missing_list_not_found")
            meta["neoeats_missing_lists"] = next_drafts
            conn.execute(
                "UPDATE users SET meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), user_id),
            )
        return next_drafts

    def _confirm_missing_list(user_id: str, draft_id: str) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        with db.transaction() as conn:
            row = conn.execute("SELECT id, email, meta_json FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="user_not_found")
            meta = _safe_json(row["meta_json"])
            drafts = _missing_lists_from_meta(meta)
            now = _now_iso()
            confirmed: Dict[str, Any] | None = None
            next_drafts: List[Dict[str, Any]] = []
            for draft in drafts:
                if str(draft.get("id") or "") == draft_id:
                    confirmed = {
                        **draft,
                        "status": "confirmed",
                        "confirmed_at": draft.get("confirmed_at") or now,
                        "updated_at": now,
                    }
                    next_drafts.append(confirmed)
                else:
                    next_drafts.append(draft)
            if confirmed is None:
                raise HTTPException(status_code=404, detail="missing_list_not_found")
            meta["neoeats_missing_lists"] = next_drafts
            _append_launch_event(
                meta,
                event_type="missing_list_confirmed",
                payload={
                    "source": confirmed.get("source"),
                    "recipe_id": confirmed.get("recipe_id"),
                    "recipe_name": confirmed.get("recipe_name"),
                    "item_count": confirmed.get("item_count") or len(confirmed.get("missing_items") or []),
                    "total_estimate": confirmed.get("total_estimate") or 0,
                    "currency": confirmed.get("currency") or "NOK",
                    "catalog_match_count": confirmed.get("catalog_match_count") or 0,
                    "catalog_available_count": confirmed.get("catalog_available_count") or 0,
                },
            )
            conn.execute(
                "UPDATE users SET meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), user_id),
            )
        return confirmed, _missing_lists_from_meta(meta), _launch_events_from_meta(meta)

    @router.get("/dashboard")
    async def get_dashboard(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        dashboard = await _build_dashboard_payload(ctx.user_id, get_neoeats_db, request.app)
        profile = _build_profile_payload(row, meta, dashboard=dashboard)
        return {
            "user": {
                "id": profile["id"],
                "username": profile["username"],
                "email": profile["email"],
            },
            **dashboard,
        }

    @router.get("/profile")
    async def get_profile(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        dashboard = await _build_dashboard_payload(ctx.user_id, get_neoeats_db, request.app)
        return _build_profile_payload(row, meta, dashboard=dashboard)

    @router.post("/launch/events")
    async def record_launch_event(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        normalized = _normalize_launch_event_payload(raw)
        event, events = _store_launch_event(ctx.user_id, normalized)
        return {
            "ok": True,
            "event": event,
            "summary": _launch_event_summary(events),
            "data_sources": {
                "launch_events": "users.meta_json.neoeats_launch_events",
            },
        }

    @router.get("/launch/events")
    async def get_launch_events(
        request: Request,
        limit: int = Query(50, ge=1, le=250),
    ) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        events = _launch_events_from_meta(meta)
        return {
            "ok": True,
            "user": {
                "id": str(row["id"]),
                "email": row["email"],
            },
            "events": events[-limit:],
            "summary": _launch_event_summary(events),
            "data_sources": {
                "launch_events": "users.meta_json.neoeats_launch_events",
            },
        }

    @router.get("/launch/events/admin/summary")
    async def admin_launch_events_summary(request: Request) -> Dict[str, Any]:
        require_admin_key(request)
        rows = db.fetchall("SELECT id, email, meta_json FROM users")
        all_events: List[Dict[str, Any]] = []
        users_with_events = 0
        activated_users = 0
        for row in rows:
            meta = _safe_json(row["meta_json"])
            events = _launch_events_from_meta(meta)
            if not events:
                continue
            users_with_events += 1
            summary = _launch_event_summary(events)
            if summary["activated"]:
                activated_users += 1
            for event in events:
                all_events.append(
                    {
                        **event,
                        "user_id": str(row["id"]),
                    }
                )

        summary = _launch_event_summary(all_events)
        summary["user_count"] = len(rows)
        summary["users_with_events"] = users_with_events
        summary["activated_user_count"] = activated_users
        summary["activation_rate_pct"] = round((activated_users / users_with_events) * 100, 2) if users_with_events else 0.0
        return {
            "ok": True,
            "summary": summary,
            "data_sources": {
                "launch_events": "users.meta_json.neoeats_launch_events",
            },
        }

    @router.get("/missing-lists")
    async def get_missing_lists(
        request: Request,
        limit: int = Query(25, ge=1, le=50),
    ) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        drafts = _missing_lists_from_meta(meta)
        return {
            "ok": True,
            "user": {
                "id": str(row["id"]),
                "email": row["email"],
            },
            "drafts": drafts[:limit],
            "summary": _missing_list_summary(drafts),
            "data_sources": {
                "missing_lists": "users.meta_json.neoeats_missing_lists",
            },
        }

    @router.post("/missing-lists")
    async def save_missing_list(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        normalized = _normalize_missing_list_payload(raw)
        normalized = _enrich_missing_list_payload(
            normalized,
            await _load_store_catalog_items(get_neoeats_db, request.app),
        )
        draft, drafts, events = _store_missing_list(ctx.user_id, normalized)
        return {
            "ok": True,
            "draft": draft,
            "summary": _missing_list_summary(drafts),
            "launch_summary": _launch_event_summary(events),
            "data_sources": {
                "missing_lists": "users.meta_json.neoeats_missing_lists",
                "launch_events": "users.meta_json.neoeats_launch_events",
            },
        }

    @router.delete("/missing-lists/{draft_id}")
    async def delete_missing_list(request: Request, draft_id: str) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        drafts = _delete_missing_list(ctx.user_id, draft_id)
        return {
            "ok": True,
            "summary": _missing_list_summary(drafts),
            "data_sources": {
                "missing_lists": "users.meta_json.neoeats_missing_lists",
            },
        }

    @router.post("/missing-lists/{draft_id}/confirm")
    async def confirm_missing_list(request: Request, draft_id: str) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        draft, drafts, events = _confirm_missing_list(ctx.user_id, draft_id)
        return {
            "ok": True,
            "draft": draft,
            "summary": _missing_list_summary(drafts),
            "launch_summary": _launch_event_summary(events),
            "data_sources": {
                "missing_lists": "users.meta_json.neoeats_missing_lists",
                "launch_events": "users.meta_json.neoeats_launch_events",
            },
        }

    @router.get("/memory")
    async def get_memory(
        request: Request,
        query: str = Query("", max_length=500),
        limit: int = Query(12, ge=1, le=30),
    ) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        structured_memory = meta.get("neoeats_memory") if isinstance(meta.get("neoeats_memory"), dict) else {}
        controls = memory_controls_from_meta(meta)
        source_ready = True
        events: List[Dict[str, Any]] = []
        stats: Dict[str, Any] = {
            "event_count": 0,
            "last_updated_at": None,
            "by_event_type": {},
            "by_embedding_status": {},
            "embedding_ready_count": 0,
            "embedding_coverage_pct": 0.0,
        }
        embedding_provider = _embedding_provider_from_app(request.app)
        embedding_model = _embedding_model_from_provider(embedding_provider)
        try:
            neoeats_db = await get_neoeats_db(request.app)
            stats = await memory_event_stats(neoeats_db, user_id=ctx.user_id)
            if memory_retrieval_enabled(meta):
                events = await retrieve_memory_events(
                    neoeats_db,
                    user_id=ctx.user_id,
                    query=query,
                    limit=limit,
                    lookback=max(80, limit * 8),
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                )
        except Exception:
            source_ready = False

        return {
            "user": {
                "id": str(row["id"]),
                "email": row["email"],
            },
            "memory_controls": controls,
            "memory_stats": stats,
            "structured_memory": structured_memory,
            "rag_memory": memory_context_from_events(events),
            "data_sources": {
                "structured_memory": "users.meta_json.neoeats_memory",
                "memory_controls": "users.meta_json.neoeats_memory_controls",
                "rag_events": "neoeats_user_memory_events",
                "rag_events_ready": source_ready,
                "rag_retrieval_enabled": memory_retrieval_enabled(meta),
                "rag_embedding_provider_available": embedding_provider_available(embedding_provider),
                "rag_embedding_model": embedding_model,
            },
        }

    @router.get("/memory/export")
    async def export_memory(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        structured_memory = meta.get("neoeats_memory") if isinstance(meta.get("neoeats_memory"), dict) else {}
        events: List[Dict[str, Any]] = []
        stats: Dict[str, Any] = {
            "event_count": 0,
            "last_updated_at": None,
            "by_event_type": {},
            "by_embedding_status": {},
            "embedding_ready_count": 0,
            "embedding_coverage_pct": 0.0,
        }
        embedding_provider = _embedding_provider_from_app(request.app)
        embedding_model = _embedding_model_from_provider(embedding_provider)
        source_ready = True
        try:
            neoeats_db = await get_neoeats_db(request.app)
            events = await export_memory_events(neoeats_db, user_id=ctx.user_id, limit=1000)
            stats = await memory_event_stats(neoeats_db, user_id=ctx.user_id)
        except Exception:
            source_ready = False

        return {
            "schema_version": "neoeats_memory_export_v1",
            "exported_at": _now_iso(),
            "user": {
                "id": str(row["id"]),
                "email": row["email"],
            },
            "memory_controls": memory_controls_from_meta(meta),
            "memory_stats": stats,
            "structured_memory": structured_memory,
            "rag_events": events,
            "data_sources": {
                "structured_memory": "users.meta_json.neoeats_memory",
                "memory_controls": "users.meta_json.neoeats_memory_controls",
                "rag_events": "neoeats_user_memory_events",
                "rag_events_ready": source_ready,
                "rag_embedding_provider_available": embedding_provider_available(embedding_provider),
                "rag_embedding_model": embedding_model,
            },
        }

    @router.post("/memory/embeddings/backfill")
    async def backfill_memory_embeddings(
        request: Request,
        limit: int = Query(50, ge=1, le=250),
    ) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        _row, meta = _load_user(ctx.user_id)
        controls = memory_controls_from_meta(meta)
        embedding_provider = _embedding_provider_from_app(request.app)
        embedding_model = _embedding_model_from_provider(embedding_provider)

        if not memory_retrieval_enabled(meta):
            return {
                "ok": False,
                "reason": "rag_retrieval_disabled",
                "memory_controls": controls,
                "backfill": {
                    "provider_available": embedding_provider_available(embedding_provider),
                    "embedding_model": embedding_model,
                    "attempted": 0,
                    "ready": 0,
                    "unavailable": 0,
                    "failed": 0,
                    "skipped": 0,
                    "event_ids": [],
                },
            }

        provider_available = embedding_provider_available(embedding_provider)
        if not provider_available:
            return {
                "ok": False,
                "reason": "embedding_provider_unavailable",
                "memory_controls": controls,
                "backfill": {
                    "provider_available": False,
                    "embedding_model": embedding_model,
                    "attempted": 0,
                    "ready": 0,
                    "unavailable": 0,
                    "failed": 0,
                    "skipped": limit,
                    "event_ids": [],
                },
            }

        source_ready = True
        backfill: Dict[str, Any]
        stats: Dict[str, Any] = {
            "event_count": 0,
            "last_updated_at": None,
            "by_event_type": {},
            "by_embedding_status": {},
            "embedding_ready_count": 0,
            "embedding_coverage_pct": 0.0,
        }
        try:
            neoeats_db = await get_neoeats_db(request.app)
            backfill = await backfill_memory_event_embeddings(
                neoeats_db,
                user_id=ctx.user_id,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                limit=limit,
            )
            stats = await memory_event_stats(neoeats_db, user_id=ctx.user_id)
        except Exception:
            source_ready = False
            backfill = {
                "provider_available": provider_available,
                "embedding_model": embedding_model,
                "attempted": 0,
                "ready": 0,
                "unavailable": 0,
                "failed": 0,
                "skipped": 0,
                "event_ids": [],
                "reason": "rag_events_unavailable",
            }

        return {
            "ok": source_ready,
            "memory_controls": controls,
            "memory_stats": stats,
            "backfill": backfill,
            "data_sources": {
                "rag_events": "neoeats_user_memory_events",
                "rag_events_ready": source_ready,
                "rag_embedding_provider_available": provider_available,
                "rag_embedding_model": embedding_model,
            },
        }

    @router.get("/memory/embeddings/admin/status")
    async def admin_memory_embedding_status(
        request: Request,
        statuses: str | None = Query(None, description="Comma-separated embedding statuses counted as backlog."),
    ) -> Dict[str, Any]:
        require_admin_key(request)
        embedding_provider = _embedding_provider_from_app(request.app)
        embedding_model = _embedding_model_from_provider(embedding_provider)
        provider_available = embedding_provider_available(embedding_provider)
        source_ready = True
        stats: Dict[str, Any]
        try:
            neoeats_db = await get_neoeats_db(request.app)
            stats = await memory_embedding_global_stats(
                neoeats_db,
                statuses=_parse_embedding_statuses(statuses),
            )
        except Exception:
            source_ready = False
            stats = {
                "event_count": 0,
                "user_count": 0,
                "last_updated_at": None,
                "by_embedding_status": {},
                "users_by_embedding_status": {},
                "embedding_ready_count": 0,
                "embedding_coverage_pct": 0.0,
                "backlog_statuses": _parse_embedding_statuses(statuses) or ["pending", "failed", "unavailable"],
                "backlog_event_count": 0,
                "backlog_user_count": 0,
            }

        return {
            "ok": source_ready,
            "memory_embedding_stats": stats,
            "data_sources": {
                "rag_events": "neoeats_user_memory_events",
                "rag_events_ready": source_ready,
                "rag_embedding_provider_available": provider_available,
                "rag_embedding_model": embedding_model,
            },
        }

    @router.post("/memory/embeddings/admin/backfill")
    async def admin_backfill_memory_embeddings(
        request: Request,
        limit_per_user: int = Query(50, ge=1, le=250),
        max_users: int = Query(25, ge=1, le=200),
        statuses: str | None = Query(None, description="Comma-separated embedding statuses to backfill."),
        dry_run: bool = Query(False),
    ) -> Dict[str, Any]:
        require_admin_key(request)
        embedding_provider = _embedding_provider_from_app(request.app)
        embedding_model = _embedding_model_from_provider(embedding_provider)
        provider_available = embedding_provider_available(embedding_provider)
        source_ready = True
        backfill: Dict[str, Any]
        stats: Dict[str, Any] = {
            "event_count": 0,
            "user_count": 0,
            "last_updated_at": None,
            "by_embedding_status": {},
            "users_by_embedding_status": {},
            "embedding_ready_count": 0,
            "embedding_coverage_pct": 0.0,
            "backlog_statuses": _parse_embedding_statuses(statuses) or ["pending", "failed", "unavailable"],
            "backlog_event_count": 0,
            "backlog_user_count": 0,
        }
        try:
            neoeats_db = await get_neoeats_db(request.app)
            backfill = await backfill_memory_event_embeddings_for_all_users(
                neoeats_db,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
                limit_per_user=limit_per_user,
                max_users=max_users,
                statuses=_parse_embedding_statuses(statuses),
                dry_run=dry_run,
            )
            stats = await memory_embedding_global_stats(
                neoeats_db,
                statuses=_parse_embedding_statuses(statuses),
            )
        except Exception:
            source_ready = False
            backfill = {
                "provider_available": provider_available,
                "embedding_model": embedding_model,
                "limit_per_user": limit_per_user,
                "max_users": max_users,
                "statuses": _parse_embedding_statuses(statuses) or ["pending", "failed", "unavailable"],
                "dry_run": bool(dry_run),
                "users_considered": 0,
                "attempted": 0,
                "ready": 0,
                "unavailable": 0,
                "failed": 0,
                "skipped": 0,
                "event_ids": [],
                "users": [],
                "reason": "rag_events_unavailable",
            }

        return {
            "ok": source_ready,
            "memory_embedding_stats": stats,
            "backfill": backfill,
            "data_sources": {
                "rag_events": "neoeats_user_memory_events",
                "rag_events_ready": source_ready,
                "rag_embedding_provider_available": provider_available,
                "rag_embedding_model": embedding_model,
            },
        }

    @router.post("/recipes/feedback")
    async def record_recipe_feedback(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        _row, meta = _load_user(ctx.user_id)
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        feedback_payload = _normalize_recipe_feedback_payload(raw)
        controls = memory_controls_from_meta(meta)
        if not memory_learning_enabled(meta, source="recipe_feedback"):
            return {
                "ok": True,
                "memory_recorded": False,
                "reason": "recipe_memory_disabled",
                "memory_controls": controls,
            }

        event_type = f"recipe_feedback_{feedback_payload['feedback']}"
        embedding_provider = _embedding_provider_from_app(request.app)
        embedding_model = _embedding_model_from_provider(embedding_provider)
        source_ready = True
        event_id: str | None = None
        try:
            neoeats_db = await get_neoeats_db(request.app)
            event_id = await record_memory_event(
                neoeats_db,
                user_id=ctx.user_id,
                event_type=event_type,
                source="recipe_feedback",
                subject=str(feedback_payload.get("recipe_name") or feedback_payload.get("recipe_id") or "").strip() or None,
                payload=feedback_payload,
                confidence=0.9 if feedback_payload["feedback"] == "accepted" else 0.82,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
            )
        except Exception:
            source_ready = False

        return {
            "ok": bool(source_ready and event_id),
            "memory_recorded": bool(event_id),
            "event_id": event_id,
            "event_type": event_type,
            "feedback": feedback_payload["feedback"],
            "memory_controls": controls,
            "data_sources": {
                "rag_events": "neoeats_user_memory_events",
                "rag_events_ready": source_ready,
                "rag_embedding_provider_available": embedding_provider_available(embedding_provider),
                "rag_embedding_model": embedding_model,
            },
        }

    @router.patch("/memory/settings")
    async def patch_memory_settings(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        _row, meta = _load_user(ctx.user_id)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        controls = patch_memory_controls(meta, payload)
        db.execute(
            "UPDATE users SET meta_json = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), ctx.user_id),
        )
        return {
            "ok": True,
            "memory_controls": controls,
        }

    @router.delete("/memory")
    async def clear_memory(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        _row, meta = _load_user(ctx.user_id)
        structured_memory = clear_structured_memory(meta)
        db.execute(
            "UPDATE users SET meta_json = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), ctx.user_id),
        )

        source_ready = True
        try:
            neoeats_db = await get_neoeats_db(request.app)
            await delete_memory_events(neoeats_db, user_id=ctx.user_id)
        except Exception:
            source_ready = False

        return {
            "ok": True,
            "structured_memory": structured_memory,
            "memory_controls": memory_controls_from_meta(meta),
            "rag_events_cleared": source_ready,
        }

    @router.patch("/profile")
    async def patch_profile(request: Request) -> Dict[str, Any]:
        ctx = authenticate(request, db)
        row, meta = _load_user(ctx.user_id)
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid_payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid_payload")

        profile = meta.get("neoeats_profile") if isinstance(meta.get("neoeats_profile"), dict) else {}
        profile = dict(profile)

        if "username" in payload:
            username = str(payload.get("username") or "").strip()
            if username:
                profile["username"] = username[:64]
        if "avatar_url" in payload:
            avatar_url = payload.get("avatar_url")
            profile["avatar_url"] = str(avatar_url).strip()[:500] if avatar_url else None
        if isinstance(payload.get("preferences"), dict):
            profile["preferences"] = _merge_percent_map(payload["preferences"], _derive_preferences(meta))
        dietary_profile_updated = False
        if isinstance(payload.get("dietary_profile"), dict):
            current_dietary = profile.get("dietary_profile") if isinstance(profile.get("dietary_profile"), dict) else {}
            next_dietary = _normalize_dietary_profile(payload["dietary_profile"], base=current_dietary)
            next_dietary["updated_at"] = _now_iso()
            profile["dietary_profile"] = next_dietary
            dietary_profile_updated = True
        if isinstance(payload.get("notifications"), dict):
            current_notifications = profile.get("notifications") if isinstance(profile.get("notifications"), dict) else {}
            profile["notifications"] = _coerce_bool_map(
                {**current_notifications, **payload["notifications"]},
                DEFAULT_NOTIFICATIONS,
            )

        profile["updated_at"] = _now_iso()
        meta["neoeats_profile"] = profile
        db.execute(
            "UPDATE users SET meta_json = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), ctx.user_id),
        )

        if dietary_profile_updated and memory_learning_enabled(meta, source="profile_preferences"):
            try:
                neoeats_db = await get_neoeats_db(request.app)
                dietary_payload = profile.get("dietary_profile") if isinstance(profile.get("dietary_profile"), dict) else {}
                await record_memory_event(
                    neoeats_db,
                    user_id=ctx.user_id,
                    event_type="profile_dietary_updated",
                    source="profile_preferences",
                    subject="dietary profile",
                    payload=dietary_payload,
                    confidence=0.96,
                    embedding_provider=_embedding_provider_from_app(request.app),
                    embedding_model=_embedding_model_from_provider(_embedding_provider_from_app(request.app)),
                )
            except Exception:
                pass

        row, meta = _load_user(ctx.user_id)
        dashboard = await _build_dashboard_payload(ctx.user_id, get_neoeats_db, request.app)
        return _build_profile_payload(row, meta, dashboard=dashboard)

    return router
