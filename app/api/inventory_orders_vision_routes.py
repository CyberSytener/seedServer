from __future__ import annotations

import hashlib
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from app.core.auth import _hash_key, authenticate
from app.models.neoeats import (
    FridgeItem,
    FridgeItemCreate,
    FridgeItemPatch,
    OrderInitRequest,
    OrderInitResponse,
    OrderItem,
    OrderSummary,
    StoreItem,
    VisionDetectedItem,
)
from app.services.hybrid_recipes import suggest_hybrid_recipes
from app.services.neoeats_memory_controls import memory_learning_enabled, safe_meta_json
from app.services.neoeats_cooking_complete import decide_consumption_action, group_cooking_consumption
from app.services.neoeats_inventory_extract import build_inventory_extract_response
from app.services.neoeats_rag_memory import record_memory_event
from app.services.order_stream import OrderStreamHub
from app.services.pantry_normalizer import canonicalize_product, normalize_quantity_unit
from app.services.product_normalize import (
    _coerce_date_safe,
    _dedupe_by_product_identity,
    _is_uuid,
    _looks_like_packaging_character,
    _normalize_product_name,
    _parse_dt,
    _parse_iso_date_safe,
    _sanitize_vision_expiry,
    _upsert_storage_item_for_user,
)
from app.settings import get_settings


# ---------------------------------------------------------------------------
# Helpers (moved from create_app closure)
# ---------------------------------------------------------------------------


def _freshness_metrics(expires_at: datetime | None) -> tuple[Optional[int], Optional[int]]:
    if not expires_at:
        return None, None
    today = datetime.now(timezone.utc).date()
    days_to_expiry = (expires_at.date() - today).days
    window_days = 14
    freshness = int(max(0, min(100, (days_to_expiry / window_days) * 100)))
    return freshness, days_to_expiry


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "isoformat"):
        try:
            return datetime.fromisoformat(value.isoformat())
        except Exception:
            return None
    if isinstance(value, str):
        return _parse_dt(value)
    return None


def _finite_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _slug_token(value: Any) -> str:
    normalized = _normalize_product_name(str(value or ""))
    return "-".join(part for part in normalized.split() if part)[:48]


def _vision_icon_key(name: str, category: Optional[str]) -> str:
    text = f"{name} {category or ''}".lower()
    rules = [
        ("cheese", ("cheese", "mozzarella", "parmesan", "brie", "gouda")),
        ("potato", ("potato",)),
        ("onion", ("onion", "garlic")),
        ("poultry", ("chicken", "turkey")),
        ("dairy", ("milk", "yogurt", "skyr", "cream", "dairy")),
        ("egg", ("egg",)),
        ("bakery", ("bread", "bagel", "bun", "bakery")),
        ("vegetable", ("tomato", "cucumber", "lettuce", "spinach", "broccoli", "carrot", "vegetable", "produce")),
        ("fruit", ("apple", "banana", "orange", "berry", "fruit")),
        ("seafood", ("fish", "salmon", "tuna", "cod", "shrimp", "seafood")),
        ("meat", ("beef", "pork", "lamb", "steak", "meat", "protein")),
        ("grain", ("rice", "oat", "pasta", "noodle", "grain", "cereal")),
    ]
    for icon_key, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return icon_key
    return "grocery"


def _vision_detection_id(
    *,
    canonical_name: str,
    display_name: str,
    brand: Optional[str],
    geometry: Dict[str, Any],
    index: int,
) -> str:
    geometry_key = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    raw = "|".join([
        canonical_name,
        display_name,
        brand or "",
        geometry_key,
        str(index),
    ])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    slug = _slug_token(canonical_name or display_name) or f"item-{index + 1}"
    return f"vision-{slug}-{digest}"


def _vision_confidence_score(item: VisionDetectedItem) -> float:
    raw = item.confidence_score
    if raw is None:
        raw = item.confidence
    parsed = _finite_float(raw)
    if parsed is None:
        return 0.8
    score = parsed / 100.0 if parsed > 1.0 else parsed
    return max(0.0, min(1.0, score))


def _vision_trust_level(score: float) -> str:
    if score < 0.7:
        return "review"
    if score < 0.85:
        return "check"
    return "trusted"


def _vision_identity_key(item: VisionDetectedItem) -> str:
    name = _normalize_product_name(item.canonical_name or item.display_name or item.name or "")
    brand = _normalize_product_name(item.brand or "")
    unit = _normalize_product_name(item.unit or "")
    if not name:
        return ""
    return "|".join([name, brand, unit])


def _vision_bbox(item: VisionDetectedItem) -> Optional[tuple[float, float, float, float]]:
    bbox = item.bbox if isinstance(item.bbox, dict) else None
    x = _finite_float((bbox or {}).get("x")) if bbox else None
    y = _finite_float((bbox or {}).get("y")) if bbox else None
    width = _finite_float((bbox or {}).get("width")) if bbox else None
    height = _finite_float((bbox or {}).get("height")) if bbox else None

    if x is None:
        x = _finite_float(item.bbox_x)
    if y is None:
        y = _finite_float(item.bbox_y)
    if width is None:
        width = _finite_float(item.bbox_width)
    if height is None:
        height = _finite_float(item.bbox_height)

    if x is None or y is None or width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return x, y, width, height


def _vision_center(item: VisionDetectedItem) -> Optional[tuple[float, float]]:
    x = _finite_float(item.center_x)
    y = _finite_float(item.center_y)

    if x is None:
        x = _finite_float(item.x)
    if y is None:
        y = _finite_float(item.y)

    if (x is None or y is None) and isinstance(item.coordinates, dict):
        if x is None:
            x = _finite_float(item.coordinates.get("x"))
        if y is None:
            y = _finite_float(item.coordinates.get("y"))

    if x is not None and y is not None:
        return x, y

    bbox = _vision_bbox(item)
    if bbox:
        box_x, box_y, box_width, box_height = bbox
        return box_x + box_width / 2.0, box_y + box_height / 2.0

    return None


def _vision_iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right

    overlap_x = max(0.0, min(left_x + left_width, right_x + right_width) - max(left_x, right_x))
    overlap_y = max(0.0, min(left_y + left_height, right_y + right_height) - max(left_y, right_y))
    overlap_area = overlap_x * overlap_y
    if overlap_area <= 0:
        return 0.0

    left_area = left_width * left_height
    right_area = right_width * right_height
    union_area = left_area + right_area - overlap_area
    if union_area <= 0:
        return 0.0
    return overlap_area / union_area


def _vision_centers_are_close(left: tuple[float, float], right: tuple[float, float]) -> bool:
    max_axis = max(abs(left[0]), abs(left[1]), abs(right[0]), abs(right[1]))
    threshold = 0.12 if max_axis <= 1.5 else 72.0
    dx = left[0] - right[0]
    dy = left[1] - right[1]
    return (dx * dx + dy * dy) <= (threshold * threshold)


def _vision_items_same_marker(left: VisionDetectedItem, right: VisionDetectedItem) -> bool:
    if _vision_identity_key(left) != _vision_identity_key(right):
        return False

    left_bbox = _vision_bbox(left)
    right_bbox = _vision_bbox(right)
    if left_bbox and right_bbox:
        if _vision_iou(left_bbox, right_bbox) >= 0.45:
            return True

    left_center = _vision_center(left)
    right_center = _vision_center(right)
    if left_center and right_center:
        return _vision_centers_are_close(left_center, right_center)

    return left_bbox is None and right_bbox is None and left_center is None and right_center is None


def _vision_with_review_contract(item: VisionDetectedItem, *, duplicate_count: int = 1) -> VisionDetectedItem:
    score = _vision_confidence_score(item)
    return item.model_copy(update={
        "dedupe_key": item.dedupe_key or _vision_identity_key(item),
        "trust_level": _vision_trust_level(score),
        "review_required": score < 0.7,
        "duplicate_count": duplicate_count if duplicate_count > 1 else item.duplicate_count,
    })


def _dedupe_vision_items_for_overlay(items: List[VisionDetectedItem]) -> List[VisionDetectedItem]:
    deduped: List[VisionDetectedItem] = []
    duplicate_counts: List[int] = []

    for raw_item in items:
        item = _vision_with_review_contract(raw_item)
        match_index: Optional[int] = None
        for index, existing in enumerate(deduped):
            if _vision_items_same_marker(existing, item):
                match_index = index
                break

        if match_index is None:
            deduped.append(item)
            duplicate_counts.append(1)
            continue

        existing = deduped[match_index]
        duplicate_counts[match_index] += 1
        existing_score = _vision_confidence_score(existing)
        item_score = _vision_confidence_score(item)
        best = item if item_score > existing_score else existing
        best_quantity = max(float(existing.quantity or 0.0), float(item.quantity or 0.0), 1.0)
        deduped[match_index] = best.model_copy(update={"quantity": best_quantity})

    return [
        _vision_with_review_contract(item, duplicate_count=duplicate_counts[index])
        for index, item in enumerate(deduped)
    ]


def _extract_vision_geometry(row: Dict[str, Any]) -> Dict[str, Any]:
    geometry: Dict[str, Any] = {}

    for key in ("x", "y", "center_x", "center_y", "bbox_x", "bbox_y", "bbox_width", "bbox_height"):
        value = _finite_float(row.get(key))
        if value is not None:
            geometry[key] = value

    center = row.get("center")
    if isinstance(center, dict):
        center_x = _finite_float(center.get("x"))
        center_y = _finite_float(center.get("y"))
        if center_x is not None and "center_x" not in geometry:
            geometry["center_x"] = center_x
        if center_y is not None and "center_y" not in geometry:
            geometry["center_y"] = center_y

    position = row.get("position")
    if isinstance(position, dict):
        pos_x = _finite_float(position.get("x"))
        pos_y = _finite_float(position.get("y"))
        if pos_x is not None and "center_x" not in geometry and "x" not in geometry:
            geometry["center_x"] = pos_x
        if pos_y is not None and "center_y" not in geometry and "y" not in geometry:
            geometry["center_y"] = pos_y

    coordinates = row.get("coordinates")
    if isinstance(coordinates, dict):
        coord_payload: Dict[str, float] = {}
        for key in ("x", "y"):
            value = _finite_float(coordinates.get(key))
            if value is not None:
                coord_payload[key] = value
        if coord_payload:
            geometry["coordinates"] = coord_payload

    bbox = row.get("bbox")
    if isinstance(bbox, dict):
        bbox_payload: Dict[str, float] = {}
        for key in ("x", "y", "width", "height"):
            value = _finite_float(bbox.get(key))
            if value is not None:
                bbox_payload[key] = value
        if bbox_payload:
            geometry["bbox"] = bbox_payload
    elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        bbox_values = [_finite_float(value) for value in bbox[:4]]
        if all(value is not None for value in bbox_values):
            geometry["bbox"] = {
                "x": float(bbox_values[0]),
                "y": float(bbox_values[1]),
                "width": float(bbox_values[2]),
                "height": float(bbox_values[3]),
            }

    return geometry


def _fridge_item_from_row(row: Any) -> FridgeItem:
    expires_dt = _coerce_datetime(row.get("expires_at"))
    freshness_pct, days_to_expiry = _freshness_metrics(expires_dt)
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = None
    metadata_dict = metadata if isinstance(metadata, dict) else {}
    canonical_name = str(
        metadata_dict.get("canonical_name")
        or _normalize_product_name(row.get("name") or "")
    ).strip() or None
    display_name = str(
        metadata_dict.get("display_name")
        or row.get("name")
        or ""
    ).strip() or None

    return FridgeItem(
        item_id=str(row.get("storage_id")),
        name=str(row.get("name") or ""),
        canonical_name=canonical_name,
        display_name=display_name,
        quantity=float(row.get("quantity") or 0.0),
        unit=str(row.get("unit") or ""),
        expires_at=expires_dt.date().isoformat() if expires_dt else None,
        freshness_pct=freshness_pct,
        days_to_expiry=days_to_expiry,
        category=metadata_dict.get("category"),
        metadata=metadata_dict or None,
        created_at=_coerce_datetime(row.get("created_at")).isoformat() if row.get("created_at") else None,
        updated_at=_coerce_datetime(row.get("updated_at")).isoformat() if row.get("updated_at") else None,
    )


def _memory_payload_from_fridge_item(item: FridgeItem) -> Dict[str, Any]:
    payload = item.model_dump()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "item": payload,
        "item_id": payload.get("item_id"),
        "product_id": metadata.get("product_id"),
        "canonical_name": payload.get("canonical_name") or metadata.get("canonical_name"),
        "display_name": payload.get("display_name") or payload.get("name"),
        "category": payload.get("category") or metadata.get("category"),
        "detection_id": metadata.get("detection_id"),
    }


async def _record_pantry_memory_events(
    neoeats_db: Any,
    *,
    user_id: str,
    items: List[FridgeItem],
    source: str,
    memory_allowed: bool = True,
    embedding_provider: Optional[Any] = None,
    embedding_model: str = "text-embedding-004",
) -> None:
    if not memory_allowed:
        return
    for item in items:
        payload = _memory_payload_from_fridge_item(item)
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        confidence = metadata.get("confidence") if isinstance(metadata, dict) else 0.86
        event_type = "scan_item_confirmed" if str(source).startswith("vision") else "pantry_item_confirmed"
        await record_memory_event(
            neoeats_db,
            user_id=user_id,
            event_type=event_type,
            source=source,
            subject=str(item.display_name or item.name or "").strip() or None,
            payload=payload,
            confidence=float(confidence or 0.86),
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def build_inventory_orders_vision_router(
    *,
    db: Any,
    settings: Any,
    get_neoeats_db: Any,
    saga_orchestrator: Any,
    order_stream: Any,
    llm_engine: Any,
) -> APIRouter:
    router = APIRouter()

    def _memory_allowed(user_id: str, source: str) -> bool:
        try:
            row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (user_id,))
            meta = safe_meta_json(row["meta_json"] if row else {})
            return memory_learning_enabled(meta, source=source)
        except Exception:
            logging.exception("NeoEats memory control lookup failed")
            return True

    def _embedding_model() -> str:
        return str(getattr(llm_engine, "embedding_model", "text-embedding-004") or "text-embedding-004")

    # -- WebSocket: order stream ------------------------------------------------

    @router.websocket("/api/v1/orders/stream")
    async def orders_stream_ws(
        websocket: WebSocket,
        token: Optional[str] = Query(None),
        user_id: Optional[str] = Query(None),
    ):
        await websocket.accept()
        settings_local = get_settings()
        resolved_user: Optional[str] = None
        bearer_token = (token or "").strip()

        if not bearer_token:
            auth_header = str(websocket.headers.get("Authorization") or "").strip()
            if auth_header.lower().startswith("bearer "):
                bearer_token = auth_header.split(" ", 1)[1].strip()

        if bearer_token:
            if (
                settings_local.test_auth_mode
                and settings_local.environment in {"development", "test"}
                and bearer_token.startswith("test_")
            ):
                candidate = bearer_token[5:].split("|", 1)[0].strip() or "sim-user"
                resolved_user = candidate
            if not resolved_user:
                try:
                    from app.api.ws.auth import JWTHandler

                    resolved_user = JWTHandler().extract_user_id(bearer_token) or resolved_user
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
            if not resolved_user:
                try:
                    row = db.fetchone(
                        "SELECT id, is_banned FROM users WHERE api_key_hash = ?",
                        (_hash_key(bearer_token),),
                    )
                    if row and int(row["is_banned"] or 0) != 1:
                        resolved_user = str(row["id"])
                except Exception:
                    resolved_user = None
        elif settings_local.enable_legacy_x_user_id:
            resolved_user = (user_id or "").strip() or str(websocket.headers.get("X-User-ID") or "").strip() or None

        if not resolved_user:
            await websocket.close(code=4001)
            return

        stream: OrderStreamHub = order_stream
        await stream.connect(resolved_user, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await stream.disconnect(resolved_user, websocket)

    # -- Inventory: fridge ledger -----------------------------------------------

    @router.get("/api/v1/inventory/ledger", response_model=Dict[str, List[FridgeItem]])
    async def list_fridge_items(request: Request):
        try:
            ctx = authenticate(request, db)
            neoeats_db = await get_neoeats_db(request.app)
            rows = await neoeats_db.fetch(
                """
                SELECT storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
                FROM storage_item
                WHERE (metadata->>'user_id') = $1
                ORDER BY updated_at DESC NULLS LAST
                """,
                ctx.user_id,
            )
            if not rows:
                return {"items": []}
            return {"items": [_fridge_item_from_row(dict(row)) for row in rows]}
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("Inventory ledger fetch failed for user=%s", getattr(request, "headers", {}).get("X-User-ID"))
            logging.warning("Returning empty ledger envelope after failure: %s", exc)
            return {"items": []}

    @router.post("/api/v1/inventory/items", response_model=List[FridgeItem])
    async def create_fridge_items(request: Request):
        ctx = authenticate(request, db)
        payload = await request.json()

        if isinstance(payload, dict) and "items" in payload:
            raw_items = payload.get("items") or []
        elif isinstance(payload, list):
            raw_items = payload
        else:
            raw_items = [payload]

        items = [FridgeItemCreate.model_validate(item) for item in raw_items]
        neoeats_db = await get_neoeats_db(request.app)

        created: List[FridgeItem] = []
        async with neoeats_db.transaction() as conn:
            for item in items:
                metadata = dict(item.metadata or {})
                metadata["user_id"] = ctx.user_id
                provided_brand = str(metadata.get("brand") or "").strip() or None
                canonicalized = canonicalize_product(
                    item.canonical_name or item.name,
                    brand=provided_brand,
                    preferred_language="en",
                )
                canonical_name = str(canonicalized.get("canonical_name") or "").strip().lower()
                display_name = str(canonicalized.get("display_name") or item.name).strip()
                normalized_quantity, normalized_unit = normalize_quantity_unit(
                    item.quantity,
                    item.unit,
                    name=display_name,
                )
                resolved_category = item.category or str(canonicalized.get("category") or "").strip() or None

                metadata["canonical_name"] = canonical_name
                metadata["display_name"] = display_name
                metadata["original_name"] = str(metadata.get("original_name") or item.name).strip()
                metadata["product_id"] = str(
                    metadata.get("product_id")
                    or canonicalized.get("product_id")
                    or hashlib.sha1(f"canon|{canonical_name}".encode("utf-8")).hexdigest()[:20]
                )
                if resolved_category:
                    metadata["category"] = resolved_category
                metadata["brand"] = provided_brand

                row = await _upsert_storage_item_for_user(
                    conn,
                    user_id=ctx.user_id,
                    name=display_name,
                    quantity=float(normalized_quantity),
                    unit=normalized_unit,
                    expires_at=_parse_iso_date_safe(item.expires_at),
                    metadata=metadata,
                )
                if row:
                    created.append(_fridge_item_from_row(dict(row)))

        try:
            await _record_pantry_memory_events(
                neoeats_db,
                user_id=ctx.user_id,
                items=created,
                source="inventory_items",
                memory_allowed=_memory_allowed(ctx.user_id, "inventory_items"),
                embedding_provider=llm_engine,
                embedding_model=_embedding_model(),
            )
        except Exception:
            logging.exception("NeoEats pantry memory event recording failed")

        return created

    @router.post("/api/v1/inventory/extract")
    async def extract_inventory_items(request: Request):
        authenticate(request, db)
        payload = await request.json() if request.headers.get("content-length") else {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        message = str(payload.get("message") or payload.get("text") or "").strip()
        structured_items = payload.get("items") if isinstance(payload.get("items"), list) else None
        if not message and not structured_items:
            raise HTTPException(status_code=400, detail="message or items is required")

        return build_inventory_extract_response(
            message,
            llm_engine=llm_engine,
            structured_items=structured_items,
        )

    @router.post("/api/v1/cooking/complete")
    async def complete_cooking_session(request: Request):
        ctx = authenticate(request, db)
        payload = await request.json() if request.headers.get("content-length") else {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        recipe_id = str(payload.get("recipe_id") or "").strip() or None
        recipe_name = str(payload.get("recipe_name") or payload.get("name") or "recipe").strip() or "recipe"
        raw_ingredients = payload.get("ingredients") if isinstance(payload.get("ingredients"), list) else []
        consumption_groups, failed_items = group_cooking_consumption(raw_ingredients)
        if not consumption_groups and not failed_items:
            raise HTTPException(status_code=400, detail="No pantry ingredients supplied")

        neoeats_db = await get_neoeats_db(request.app)
        updated_items: List[FridgeItem] = []
        deleted_item_ids: List[str] = []

        async with neoeats_db.transaction() as conn:
            for group in consumption_groups:
                row = await conn.fetchrow(
                    """
                    SELECT storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
                    FROM storage_item
                    WHERE storage_id = $1
                    """,
                    group.pantry_item_id,
                )
                if not row:
                    failed_items.append({
                        "pantry_item_id": group.pantry_item_id,
                        "name": group.name,
                        "reason": "item_not_found",
                    })
                    continue

                row_dict = dict(row)
                metadata = row_dict.get("metadata")
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                metadata_dict = metadata if isinstance(metadata, dict) else {}
                if metadata_dict.get("user_id") != ctx.user_id:
                    raise HTTPException(status_code=403, detail="forbidden")

                decision = decide_consumption_action(
                    current_quantity=row_dict.get("quantity"),
                    current_unit=row_dict.get("unit"),
                    requested_quantity=group.quantity,
                    requested_unit=group.unit,
                )
                if decision["action"] == "failed":
                    failed_items.append({
                        "pantry_item_id": group.pantry_item_id,
                        "name": group.name,
                        "reason": decision["reason"],
                        "current_unit": decision.get("current_unit"),
                        "requested_unit": decision.get("requested_unit"),
                    })
                    continue

                if decision["action"] == "delete":
                    await conn.execute("DELETE FROM storage_item WHERE storage_id = $1", group.pantry_item_id)
                    deleted_item_ids.append(group.pantry_item_id)
                    continue

                next_metadata = {
                    **metadata_dict,
                    "last_cooked_recipe": recipe_name,
                    "last_cooked_recipe_id": recipe_id,
                    "last_cooked_at": datetime.now(timezone.utc).isoformat(),
                    "last_consumed_quantity": group.quantity,
                    "last_consumed_unit": group.unit,
                    "user_id": ctx.user_id,
                }
                updated = await conn.fetchrow(
                    """
                    UPDATE storage_item
                    SET quantity = $1, metadata = $2, updated_at = $3
                    WHERE storage_id = $4
                    RETURNING storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
                    """,
                    float(decision["next_quantity"]),
                    json.dumps(next_metadata),
                    datetime.now(timezone.utc),
                    group.pantry_item_id,
                )
                if updated:
                    updated_items.append(_fridge_item_from_row(dict(updated)))

        try:
            if _memory_allowed(ctx.user_id, "cooking_complete"):
                await record_memory_event(
                    neoeats_db,
                    user_id=ctx.user_id,
                    event_type="cooking_completed",
                    source="cooking_complete",
                    subject=recipe_name,
                    payload={
                        "recipe_id": recipe_id,
                        "recipe_name": recipe_name,
                        "ingredients": raw_ingredients,
                        "updated_item_ids": [item.item_id for item in updated_items],
                        "deleted_item_ids": deleted_item_ids,
                        "failed_items": failed_items,
                    },
                    confidence=0.82 if not failed_items else 0.58,
                    embedding_provider=llm_engine,
                    embedding_model=_embedding_model(),
                )
        except Exception:
            logging.exception("NeoEats cooking memory event recording failed")

        return {
            "ok": len(failed_items) == 0,
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "updated_items": updated_items,
            "deleted_item_ids": deleted_item_ids,
            "failed_items": failed_items,
        }

    @router.patch("/api/v1/inventory/items/{item_id}", response_model=FridgeItem)
    async def patch_fridge_item(item_id: str, request: Request):
        ctx = authenticate(request, db)
        req = FridgeItemPatch.model_validate(await request.json())
        neoeats_db = await get_neoeats_db(request.app)

        row = await neoeats_db.fetchrow(
            """
            SELECT storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
            FROM storage_item
            WHERE storage_id = $1
            """,
            item_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="item_not_found")
        row = dict(row)
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if (metadata or {}).get("user_id") != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")

        updates: List[str] = []
        params: List[Any] = []
        def _add(field: str, value: Any) -> None:
            params.append(value)
            updates.append(f"{field} = ${len(params)}")

        if req.name is not None:
            _add("name", req.name)
        if req.quantity is not None:
            _add("quantity", float(req.quantity))
        if req.unit is not None:
            _add("unit", req.unit)
        if req.expires_at is not None:
            _add("expires_at", req.expires_at)

        updated_metadata = dict(metadata or {})
        if req.metadata:
            updated_metadata.update(req.metadata)
        if req.category is not None:
            updated_metadata["category"] = req.category
        if req.canonical_name is not None:
            updated_metadata["canonical_name"] = str(req.canonical_name).strip().lower()
        if req.display_name is not None:
            updated_metadata["display_name"] = str(req.display_name).strip()
        updated_metadata["user_id"] = ctx.user_id
        _add("metadata", json.dumps(updated_metadata))
        _add("updated_at", datetime.now(timezone.utc))

        if not updates:
            return _fridge_item_from_row(dict(row))

        params.append(item_id)
        updated = await neoeats_db.fetchrow(
            f"""
            UPDATE storage_item
            SET {", ".join(updates)}
            WHERE storage_id = ${len(params)}
            RETURNING storage_id, name, quantity, unit, expires_at, metadata, created_at, updated_at
            """,
            *params,
        )
        return _fridge_item_from_row(dict(updated))

    @router.delete("/api/v1/inventory/items/{item_id}")
    async def delete_fridge_item(item_id: str, request: Request):
        ctx = authenticate(request, db)
        neoeats_db = await get_neoeats_db(request.app)

        row = await neoeats_db.fetchrow(
            "SELECT metadata FROM storage_item WHERE storage_id = $1",
            item_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="item_not_found")
        metadata = dict(row).get("metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if (metadata or {}).get("user_id") != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")

        await neoeats_db.execute("DELETE FROM storage_item WHERE storage_id = $1", item_id)
        return {"ok": True}

    # -- Inventory: store -------------------------------------------------------

    @router.get("/api/v1/inventory/store")
    async def list_store_inventory(request: Request, include_hybrid: bool = False):
        try:
            ctx = authenticate(request, db)
            neoeats_db = await get_neoeats_db(request.app)
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

            row_dicts = [dict(row) for row in (rows or [])]
            items_map: Dict[str, Dict[str, Any]] = {}
            for row in row_dicts:
                try:
                    normalized_row = {
                        "item_id": str(row.get("item_id")),
                        "sku": str(row.get("sku")) if row.get("sku") is not None else None,
                        "name": str(row.get("name") or ""),
                        "category": str(row.get("category")) if row.get("category") is not None else None,
                        "unit": str(row.get("unit")) if row.get("unit") is not None else None,
                        "last_price_paid": (
                            float(row.get("last_price_paid"))
                            if row.get("last_price_paid") is not None
                            else None
                        ),
                        "quantity_available": float(row.get("quantity_available") or 0.0),
                    }
                    item_payload = StoreItem(**normalized_row).model_dump()
                    dedupe_key = str(item_payload.get("item_id") or "").strip() or _normalize_product_name(item_payload.get("name") or "")
                    if not dedupe_key:
                        continue
                    if dedupe_key not in items_map:
                        items_map[dedupe_key] = item_payload
                    else:
                        prev = items_map[dedupe_key]
                        prev["quantity_available"] = float(prev.get("quantity_available") or 0.0) + float(item_payload.get("quantity_available") or 0.0)
                        if prev.get("last_price_paid") is None and item_payload.get("last_price_paid") is not None:
                            prev["last_price_paid"] = item_payload.get("last_price_paid")
                except Exception:
                    continue
            items: List[Dict[str, Any]] = sorted(list(items_map.values()), key=lambda x: str(x.get("name") or "").lower())

            if not include_hybrid:
                return {
                    "items": items,
                    "hybrid_recipes": [],
                }

            user_rows = await neoeats_db.fetch(
                """
                SELECT name, quantity, unit, expires_at, metadata
                FROM storage_item
                WHERE (metadata->>'user_id') = $1
                """,
                ctx.user_id,
            )

            try:
                suggestions = suggest_hybrid_recipes(
                    _dedupe_by_product_identity([dict(row) for row in (user_rows or [])]),
                    items,
                )
            except Exception:
                logging.exception("Hybrid recipe suggestion failed for user=%s", ctx.user_id)
                traceback.print_exc()
                suggestions = []

            return {
                "items": items,
                "hybrid_recipes": [suggestion.model_dump() for suggestion in (suggestions or [])],
            }
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("Store inventory fetch failed")
            logging.warning("Returning empty store envelope after failure: %s", exc)
            return {
                "items": [],
                "hybrid_recipes": [],
            }

    # -- Orders: saga init / list / get -----------------------------------------

    @router.post("/api/v1/orders/saga/init", response_model=OrderInitResponse)
    async def init_order_saga(request: Request, response: Response):
        ctx = authenticate(request, db)
        if saga_orchestrator is None:
            raise HTTPException(status_code=503, detail="Saga orchestrator not available")

        body = await request.json()
        req = OrderInitRequest.model_validate(body)
        order_id = str(uuid.uuid4())
        action_id = str(uuid.uuid4())

        saga_payload = {
            "order_id": order_id,
            "user_id": ctx.user_id,
            "items": [item.model_dump() for item in req.items],
            "delivery": req.delivery.model_dump() if req.delivery else {},
            "payment": req.payment.model_dump() if req.payment else {},
            "notes": req.notes,
        }

        saga_user_id = ctx.user_id if _is_uuid(ctx.user_id) else None
        saga_id = await saga_orchestrator.start_saga(
            action_id=action_id,
            saga_type="neoeats_order",
            payload=saga_payload,
            user_id=saga_user_id,
        )
        response.headers["x-saga-id"] = saga_id
        return OrderInitResponse(order_id=order_id, saga_id=saga_id, status="PAYMENT_PENDING")

    @router.get("/api/v1/orders", response_model=List[OrderSummary])
    async def list_orders(request: Request):
        ctx = authenticate(request, db)
        neoeats_db = await get_neoeats_db(request.app)
        rows = await neoeats_db.fetch(
            """
            SELECT saga_id, state, payload, result, created_at, updated_at
            FROM sagas
            WHERE saga_type = 'neoeats_order'
              AND (payload->>'user_id') = $1
            ORDER BY created_at DESC
            """,
            ctx.user_id,
        )

        orders: List[OrderSummary] = []
        for row in rows:
            row = dict(row)
            payload = row.get("payload") or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            result = row.get("result") or {}
            if isinstance(result, str):
                result = json.loads(result)

            billing = result if isinstance(result, dict) else {}
            orders.append(
                OrderSummary(
                    order_id=str(payload.get("order_id") or ""),
                    saga_id=str(row.get("saga_id")),
                    status=str(row.get("state") or ""),
                    items=[OrderItem(**item) for item in payload.get("items") or []],
                    total=billing.get("total"),
                    currency=billing.get("currency"),
                    created_at=_coerce_datetime(row.get("created_at")).isoformat() if row.get("created_at") else None,
                    updated_at=_coerce_datetime(row.get("updated_at")).isoformat() if row.get("updated_at") else None,
                )
            )

        return orders

    @router.get("/api/v1/orders/{order_id}", response_model=OrderSummary)
    async def get_order(order_id: str, request: Request):
        ctx = authenticate(request, db)
        neoeats_db = await get_neoeats_db(request.app)
        row = await neoeats_db.fetchrow(
            """
            SELECT saga_id, state, payload, result, created_at, updated_at
            FROM sagas
            WHERE saga_type = 'neoeats_order'
              AND (payload->>'order_id') = $1
              AND (payload->>'user_id') = $2
            LIMIT 1
            """,
            order_id,
            ctx.user_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="order_not_found")
        row = dict(row)
        payload = row.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        result = row.get("result") or {}
        if isinstance(result, str):
            result = json.loads(result)

        billing = result if isinstance(result, dict) else {}
        return OrderSummary(
            order_id=str(payload.get("order_id") or ""),
            saga_id=str(row.get("saga_id")),
            status=str(row.get("state") or ""),
            items=[OrderItem(**item) for item in payload.get("items") or []],
            total=billing.get("total"),
            currency=billing.get("currency"),
            created_at=_coerce_datetime(row.get("created_at")).isoformat() if row.get("created_at") else None,
            updated_at=_coerce_datetime(row.get("updated_at")).isoformat() if row.get("updated_at") else None,
        )

    # -- Vision: analyze --------------------------------------------------------

    @router.post("/api/v1/vision/analyze", response_model=List[VisionDetectedItem])
    async def vision_analyze(
        request: Request,
        image: Optional[UploadFile] = File(None),
        metadata: Optional[str] = Form(None),
    ):
        ctx = authenticate(request, db)
        parsed_meta: Dict[str, Any] = {}
        if metadata:
            try:
                parsed_meta = json.loads(metadata)
            except Exception:
                parsed_meta = {}

        image_bytes: Optional[bytes] = None
        image_mime = "image/jpeg"
        if image is not None:
            try:
                image_bytes = await image.read()
                image_mime = image.content_type or "image/jpeg"
            except Exception:
                image_bytes = None

        llm_rows = llm_engine.analyze_vision(
            image_bytes=image_bytes,
            mime_type=image_mime,
        )

        if isinstance(parsed_meta.get("items"), list) and parsed_meta.get("items"):
            llm_rows = list(parsed_meta.get("items") or [])

        items: List[VisionDetectedItem] = []
        min_confidence = float((parsed_meta or {}).get("min_confidence") or 0.35)
        allow_multi_item = bool((parsed_meta or {}).get("allow_multi_item") or False)
        blocked_sources = {
            "packaging_illustration",
            "mascot",
            "promotional_graphic",
            "background_noise",
            "decorative",
            "illustration",
        }
        for row in llm_rows or []:
            if not isinstance(row, dict):
                continue
            source_type = str(row.get("source_type") or "").strip().lower()
            if source_type in blocked_sources:
                continue
            if row.get("is_primary_product") is False:
                continue
            name = str(row.get("canonical_name") or row.get("name") or row.get("product_name") or "").strip()
            if not name:
                continue
            if _looks_like_packaging_character(name):
                continue
            brand = str(row.get("brand") or "").strip() or None
            canonicalized = canonicalize_product(name, brand=brand, preferred_language="en")
            canonical_name = str(canonicalized.get("canonical_name") or name).strip().lower()
            display_name = str(canonicalized.get("display_name") or canonical_name).strip()
            quantity, unit = normalize_quantity_unit(
                row.get("quantity"),
                row.get("unit"),
                name=display_name,
            )
            expires_at = _sanitize_vision_expiry(row.get("expires_at") or row.get("expiry_date"))
            try:
                confidence_raw = float(
                    row.get("confidence_score")
                    if row.get("confidence_score") is not None
                    else row.get("confidence")
                    if row.get("confidence") is not None
                    else 0.8
                )
            except Exception:
                confidence_raw = 0.8
            confidence_score = confidence_raw / 100.0 if confidence_raw > 1.0 else confidence_raw
            if confidence_score < min_confidence:
                continue
            confidence_pct = max(0.0, min(100.0, confidence_score * 100.0))
            category = str(row.get("category") or canonicalized.get("category") or "").strip() or None
            geometry = _extract_vision_geometry(row)
            detection_id = _vision_detection_id(
                canonical_name=canonical_name,
                display_name=display_name,
                brand=brand,
                geometry=geometry,
                index=len(items),
            )
            items.append(
                VisionDetectedItem(
                    id=detection_id,
                    detection_id=detection_id,
                    icon_key=_vision_icon_key(canonical_name or display_name, category),
                    name=display_name,
                    canonical_name=canonical_name,
                    display_name=display_name,
                    category=category,
                    brand=brand,
                    quantity=quantity,
                    unit=unit,
                    expires_at=expires_at,
                    confidence=confidence_pct,
                    confidence_score=confidence_score,
                    **geometry,
                )
            )

        items = _dedupe_vision_items_for_overlay(items)

        if not allow_multi_item and len(items) > 1:
            items = sorted(
                items,
                key=lambda item: float(item.confidence_score or item.confidence or 0.0),
                reverse=True,
            )[:1]

        auto_save = bool((parsed_meta or {}).get("confirm") or (parsed_meta or {}).get("auto_save"))
        if auto_save:
            try:
                neoeats_db = await get_neoeats_db(request.app)
                saved_items: List[FridgeItem] = []
                async with neoeats_db.transaction() as conn:
                    for item in items:
                        payload = item.model_dump()
                        brand = str(payload.get("brand") or "").strip() or None
                        canonical_name = str(payload.get("canonical_name") or payload.get("name") or "").strip().lower()
                        row_meta = {
                            "user_id": ctx.user_id,
                            "source": "vision_analyze",
                            "detection_id": payload.get("detection_id") or payload.get("id"),
                            "icon_key": payload.get("icon_key"),
                            "dedupe_key": payload.get("dedupe_key"),
                            "confidence": float(payload.get("confidence_score") or 0.8),
                            "trust_level": payload.get("trust_level"),
                            "review_required": payload.get("review_required"),
                            "duplicate_count": payload.get("duplicate_count"),
                            "brand": brand,
                            "canonical_name": canonical_name,
                            "display_name": str(payload.get("display_name") or payload.get("name") or "").strip(),
                            "category": payload.get("category"),
                            "original_name": str(payload.get("name") or "").strip(),
                            "vision_geometry": {
                                key: payload.get(key)
                                for key in ("x", "y", "center_x", "center_y", "bbox_x", "bbox_y", "bbox_width", "bbox_height", "coordinates", "bbox")
                                if payload.get(key) is not None
                            },
                        }
                        row = await _upsert_storage_item_for_user(
                            conn,
                            user_id=ctx.user_id,
                            name=payload["name"],
                            quantity=float(payload["quantity"]),
                            unit=payload["unit"],
                            expires_at=_coerce_date_safe(payload.get("expires_at")),
                            metadata=row_meta,
                        )
                        if row:
                            saved_items.append(_fridge_item_from_row(dict(row)))
                try:
                    await _record_pantry_memory_events(
                        neoeats_db,
                        user_id=ctx.user_id,
                        items=saved_items,
                        source="vision_analyze_confirmed",
                        memory_allowed=_memory_allowed(ctx.user_id, "vision_analyze_confirmed"),
                        embedding_provider=llm_engine,
                        embedding_model=_embedding_model(),
                    )
                except Exception:
                    logging.exception("Vision memory event recording failed")
            except Exception:
                logging.exception("Vision auto-save failed")

        return items

    return router
