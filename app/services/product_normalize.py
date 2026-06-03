"""Product normalization utilities and date helpers.

Extracted from ``app.main`` to reduce the god-file footprint.
All functions are pure (no closure dependencies).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.pantry_normalizer import (
    canonicalize_product,
    normalize_quantity_unit,
)


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        normalized = str(val).strip()
        if "T" in normalized:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        try:
            return datetime.fromisoformat(normalized)
        except Exception:
            return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_iso_date_safe(val: str | None) -> date | None:
    if val is None:
        return None
    raw = str(val).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except Exception:
        return None


def _sanitize_vision_expiry(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parsed: Optional[date] = None
    try:
        parsed = date.fromisoformat(raw)
    except Exception:
        try:
            parsed_dt = _parse_dt(raw)
            parsed = parsed_dt.date() if parsed_dt else None
        except Exception:
            parsed = None
    if parsed is None:
        return None

    today = datetime.now(timezone.utc).date()
    if parsed.year < today.year:
        return None
    if parsed.year > today.year + 10:
        return None
    return parsed.isoformat()


def _coerce_date_safe(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed_iso = _parse_iso_date_safe(str(value))
    if parsed_iso is not None:
        return parsed_iso
    parsed_dt = _parse_dt(str(value))
    return parsed_dt.date() if parsed_dt else None


# ---------------------------------------------------------------------------
# Product identity helpers
# ---------------------------------------------------------------------------

def _normalize_product_name(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return normalized


def _normalize_brand(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return normalized


def _build_product_id(name: str, brand: str) -> str:
    payload = f"{_normalize_brand(brand)}|{_normalize_product_name(name)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _looks_like_packaging_character(name: str) -> bool:
    n = _normalize_product_name(name)
    blocked_phrases = {
        "gingerbread man",
        "bearded man",
    }
    if any(phrase in n for phrase in blocked_phrases):
        return True
    words = set(re.findall(r"[a-z]+", n))
    blocked_words = {
        "mascot",
        "character",
        "cartoon",
        "man",
        "woman",
        "boy",
        "girl",
        "face",
        "person",
    }
    return bool(words.intersection(blocked_words))


def _merge_expiry_date(existing_value: Any, incoming_value: Optional[date]) -> Optional[date]:
    existing_date = _coerce_date_safe(existing_value)
    if incoming_value and existing_date:
        return min(incoming_value, existing_date)
    return incoming_value or existing_date


# ---------------------------------------------------------------------------
# Storage upsert
# ---------------------------------------------------------------------------

async def _upsert_storage_item_for_user(
    conn: Any,
    *,
    user_id: str,
    name: str,
    quantity: float,
    unit: str,
    expires_at: Optional[date],
    metadata: Optional[Dict[str, Any]],
) -> Any:
    incoming_raw_name = str(name or "").strip()
    if not incoming_raw_name:
        return None

    incoming_meta = dict(metadata or {})
    incoming_brand = str(incoming_meta.get("brand") or "").strip() or None
    canonicalized = canonicalize_product(incoming_raw_name, brand=incoming_brand, preferred_language="en")

    provided_canonical = str(incoming_meta.get("canonical_name") or "").strip().lower()
    canonical_name = provided_canonical or str(canonicalized.get("canonical_name") or "").strip().lower()
    if not canonical_name:
        canonical_name = _normalize_product_name(incoming_raw_name)

    display_name = (
        str(incoming_meta.get("display_name") or "").strip()
        or str(canonicalized.get("display_name") or "").strip()
        or canonical_name
    )
    if not display_name:
        display_name = incoming_raw_name

    resolved_category = str(incoming_meta.get("category") or canonicalized.get("category") or "").strip() or None
    resolved_brand = incoming_brand or str(canonicalized.get("brand") or "").strip() or None

    normalized_quantity, normalized_unit = normalize_quantity_unit(
        quantity,
        unit,
        name=display_name,
    )

    product_id = str(
        incoming_meta.get("product_id")
        or canonicalized.get("product_id")
        or hashlib.sha1(f"canon|{canonical_name}".encode("utf-8")).hexdigest()[:20]
    )
    name_norm = _normalize_product_name(canonical_name or display_name)
    brand_norm = _normalize_brand(resolved_brand or "")

    incoming_meta["user_id"] = user_id
    incoming_meta["product_name_norm"] = name_norm
    incoming_meta["brand_norm"] = brand_norm
    incoming_meta["product_id"] = product_id
    incoming_meta["canonical_name"] = canonical_name
    incoming_meta["display_name"] = display_name
    incoming_meta["original_name"] = str(incoming_meta.get("original_name") or incoming_raw_name).strip()
    if resolved_category:
        incoming_meta["category"] = resolved_category
    if resolved_brand:
        incoming_meta["brand"] = resolved_brand

    existing = await conn.fetchrow(
        """
        SELECT storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
        FROM storage_item
        WHERE (metadata->>'user_id') = $1
          AND (
                (metadata->>'product_id') = $2
             OR (metadata->>'canonical_name') = $3
             OR lower(trim(name)) = $3
             OR (
                    lower(trim(name)) = $3
                AND COALESCE(metadata->>'brand_norm', '') = $4
                )
          )
        ORDER BY updated_at DESC NULLS LAST
        LIMIT 1
        """,
        user_id,
        product_id,
        name_norm,
        brand_norm,
    )

    if existing:
        existing_dict = dict(existing)
        try:
            current_quantity = float(existing_dict.get("quantity") or 0.0)
        except Exception:
            current_quantity = 0.0
        merged_quantity = current_quantity + float(normalized_quantity or 0.0)

        existing_meta = existing_dict.get("metadata") or {}
        if isinstance(existing_meta, str):
            try:
                existing_meta = json.loads(existing_meta)
            except Exception:
                existing_meta = {}
        merged_meta = dict(existing_meta or {})
        merged_meta.update(incoming_meta)

        merged_expiry = _merge_expiry_date(existing_dict.get("expires_at"), expires_at)
        row = await conn.fetchrow(
            """
            UPDATE storage_item
            SET quantity = $2,
                unit = $3,
                expires_at = $4,
                metadata = $5,
                updated_at = now()
            WHERE storage_id = $1
            RETURNING storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
            """,
            str(existing_dict.get("storage_id")),
            merged_quantity,
            str(existing_dict.get("unit") or normalized_unit or "pcs"),
            merged_expiry,
            json.dumps(merged_meta, ensure_ascii=False),
        )
        return row

    row = await conn.fetchrow(
        """
        INSERT INTO storage_item (storage_id, name, quantity, unit, expires_at, metadata)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
        """,
        str(uuid.uuid4()),
        display_name,
        float(normalized_quantity or 0.0),
        normalized_unit or "pcs",
        expires_at,
        json.dumps(incoming_meta, ensure_ascii=False),
    )
    return row


# ---------------------------------------------------------------------------
# De-duplication & misc
# ---------------------------------------------------------------------------

def _dedupe_by_product_identity(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for item in items:
        metadata = item.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        product_id = str((metadata or {}).get("product_id") or "").strip()
        name_norm = _normalize_product_name(item.get("name") or "")
        key = product_id or name_norm
        if not key:
            continue

        if key not in merged:
            merged[key] = dict(item)
            continue

        existing = merged[key]
        try:
            existing_qty = float(existing.get("quantity") or 0.0)
        except Exception:
            existing_qty = 0.0
        try:
            incoming_qty = float(item.get("quantity") or 0.0)
        except Exception:
            incoming_qty = 0.0
        existing["quantity"] = existing_qty + incoming_qty

        existing_exp = _coerce_date_safe(existing.get("expires_at"))
        incoming_exp = _coerce_date_safe(item.get("expires_at"))
        merged_exp = _merge_expiry_date(existing_exp, incoming_exp)
        existing["expires_at"] = merged_exp.isoformat() if merged_exp else existing.get("expires_at")

    return list(merged.values())


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        import uuid as _uuid

        _uuid.UUID(str(value))
        return True
    except Exception:
        return False
