from __future__ import annotations

import json
import logging
import os
import re
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.auth import authenticate
from app.infrastructure.db.postgres import AsyncPGDatabase
from app.models.receipts import (
    ReceiptConfirmRequest,
    ReceiptExtractionResult,
    ReceiptPersistResponse,
)
from app.services.neoeats_memory_controls import memory_learning_enabled, safe_meta_json
from app.services.neoeats_rag_memory import record_memory_event

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return out[:24] or "item"


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _build_match_id(name: str) -> str:
    normalized = _normalize_name(name)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]


def build_receipts_router(
    get_neoeats_db: Callable[[Any], Awaitable[AsyncPGDatabase]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/vision", tags=["vision", "receipts"])

    @router.post("/receipt", response_model=ReceiptExtractionResult)
    async def analyze_receipt(
        request: Request,
        image: Optional[UploadFile] = File(None),
        metadata: Optional[str] = Form(None),
    ) -> ReceiptExtractionResult:
        db = request.app.state.seed.db
        ctx = authenticate(request, db)

        if image is None:
            raise HTTPException(status_code=400, detail="image is required")

        image_bytes = await image.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="empty image payload")

        neoeats_db = await get_neoeats_db(request.app)
        pantry_rows = await neoeats_db.fetch(
            """
            SELECT name, metadata
            FROM storage_item
            WHERE (metadata->>'user_id') = $1
            """,
            str(ctx.user_id),
        )
        pantry_items: list[Dict[str, Any]] = []
        for row in pantry_rows or []:
            item = dict(row)
            metadata_obj = item.get("metadata")
            if isinstance(metadata_obj, str):
                try:
                    metadata_obj = json.loads(metadata_obj)
                except Exception:
                    metadata_obj = {}
            metadata_obj = metadata_obj or {}
            pantry_items.append(
                {
                    "name": item.get("name"),
                    "product_name_norm": metadata_obj.get("product_name_norm") or _normalize_name(str(item.get("name") or "")),
                    "product_id": metadata_obj.get("product_id"),
                }
            )

        receipt_engine = getattr(request.app.state, "receipt_vision_engine", None)
        analyzer = receipt_engine or request.app.state.llm_engine

        payload = analyzer.analyze_receipt(
            image_bytes=image_bytes,
            mime_type=image.content_type or "image/jpeg",
            pantry_items=pantry_items,
        )

        if metadata:
            try:
                overrides = json.loads(metadata)
                if isinstance(overrides, dict) and isinstance(overrides.get("currency"), str):
                    payload["currency"] = overrides["currency"].strip().upper()
            except Exception:
                logging.debug("Suppressed exception", exc_info=True)
        receipt = ReceiptExtractionResult.model_validate(payload)
        if not receipt.validation_passed:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "receipt_validation_failed",
                    "errors": receipt.validation_errors,
                    "receipt": receipt.model_dump(),
                },
            )

        return receipt

    @router.post("/receipt/confirm", response_model=ReceiptPersistResponse)
    async def confirm_receipt(
        req: ReceiptConfirmRequest,
        request: Request,
    ) -> ReceiptPersistResponse:
        db = request.app.state.seed.db
        ctx = authenticate(request, db)
        neoeats_db = await get_neoeats_db(request.app)

        receipt_id = str(uuid.uuid4())
        scanned_at = req.scanned_at or datetime.now(timezone.utc)
        if scanned_at.tzinfo is None:
            scanned_at = scanned_at.replace(tzinfo=timezone.utc)

        raw_payload = req.model_dump(mode="json")

        store_prices_updated = 0
        items_saved = 0
        memory_items: list[dict[str, Any]] = []

        async with neoeats_db.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO receipts(id, user_id, image_url, total_amount, currency, merchant_name, scanned_at, raw_payload)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                receipt_id,
                ctx.user_id,
                req.image_url,
                float(req.total_amount),
                str(req.currency or "NOK").upper(),
                req.merchant_name,
                scanned_at,
                json.dumps(raw_payload, ensure_ascii=False),
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_ledger_event (
                    event_id uuid PRIMARY KEY,
                    event_type text NOT NULL,
                    item_id uuid,
                    lot_id uuid,
                    quantity numeric,
                    source text,
                    reference_id uuid,
                    created_at timestamptz DEFAULT now()
                )
                """
            )

            for item in req.items:
                item_name = item.name.strip()
                if not item_name:
                    continue

                item_price = float(item.price)
                item_qty = float(item.qty)
                item_unit = str(item.unit or "pcs").strip() or "pcs"
                match_id = str(item.match_id or _build_match_id(item_name))

                inventory_row = await conn.fetchrow(
                    """
                    SELECT item_id FROM inventory_item
                    WHERE lower(name) = lower($1)
                      AND is_active = true
                    LIMIT 1
                    """,
                    item_name,
                )

                if inventory_row:
                    inventory_item_id = str(inventory_row["item_id"])
                    await conn.execute(
                        """
                        UPDATE inventory_item
                        SET last_price_paid = $2,
                            updated_at = now()
                        WHERE item_id = $1
                        """,
                        inventory_item_id,
                        item_price,
                    )
                else:
                    inventory_item_id = str(uuid.uuid4())
                    sku = f"RCPT-{_slugify(item_name)}-{uuid.uuid4().hex[:6].upper()}"
                    await conn.execute(
                        """
                        INSERT INTO inventory_item (item_id, sku, name, category, unit, last_price_paid, is_active)
                        VALUES ($1, $2, $3, $4, $5, $6, true)
                        """,
                        inventory_item_id,
                        sku,
                        item_name,
                        item.category,
                        item_unit,
                        item_price,
                    )

                existing_storage = await conn.fetchrow(
                    """
                    SELECT storage_id, quantity, unit, metadata, expires_at
                    FROM storage_item
                    WHERE (metadata->>'user_id') = $1
                      AND (
                            (metadata->>'product_id') = $2
                         OR lower(trim(name)) = $3
                      )
                    ORDER BY updated_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    ctx.user_id,
                    match_id,
                    _normalize_name(item_name),
                )

                row_metadata = {
                    "user_id": ctx.user_id,
                    "source": "receipt_confirm",
                    "merchant_name": req.merchant_name,
                    "currency": req.currency,
                    "receipt_id": receipt_id,
                    "product_id": match_id,
                    "product_name_norm": _normalize_name(item_name),
                }

                if existing_storage:
                    current_qty = float(existing_storage.get("quantity") or 0.0)
                    existing_meta = existing_storage.get("metadata") or {}
                    if isinstance(existing_meta, str):
                        try:
                            existing_meta = json.loads(existing_meta)
                        except Exception:
                            existing_meta = {}
                    merged_meta = dict(existing_meta or {})
                    merged_meta.update(row_metadata)
                    await conn.execute(
                        """
                        UPDATE storage_item
                        SET quantity = $2,
                            unit = $3,
                            metadata = $4,
                            price_paid = $5,
                            receipt_id = $6,
                            updated_at = now()
                        WHERE storage_id = $1
                        """,
                        str(existing_storage.get("storage_id")),
                        current_qty + item_qty,
                        str(existing_storage.get("unit") or item_unit),
                        json.dumps(merged_meta, ensure_ascii=False),
                        item_price,
                        receipt_id,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO storage_item (storage_id, name, quantity, unit, expires_at, metadata, price_paid, receipt_id)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        str(uuid.uuid4()),
                        item_name,
                        item_qty,
                        item_unit,
                        None,
                        json.dumps(row_metadata, ensure_ascii=False),
                        item_price,
                        receipt_id,
                    )

                await conn.execute(
                    """
                    INSERT INTO inventory_ledger_event (
                        event_id, event_type, item_id, lot_id, quantity, source, reference_id
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    str(uuid.uuid4()),
                    "adjust",
                    inventory_item_id,
                    None,
                    item_qty,
                    "receipt",
                    receipt_id,
                )

                items_saved += 1
                if item_price > 0:
                    store_prices_updated += 1
                memory_items.append(
                    {
                        "name": item_name,
                        "canonical_name": item.canonical_name,
                        "quantity": item_qty,
                        "unit": item_unit,
                        "price": item_price,
                        "category": item.category,
                        "match_id": match_id,
                        "receipt_id": receipt_id,
                        "merchant_name": req.merchant_name,
                        "currency": req.currency,
                    }
                )

        memory_allowed = True
        try:
            row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (str(ctx.user_id),))
            memory_allowed = memory_learning_enabled(
                safe_meta_json(row["meta_json"] if row else {}),
                source="receipt_confirm",
            )
        except Exception:
            logger.exception("NeoEats receipt memory control lookup failed")

        if memory_allowed:
            for memory_item in memory_items:
                try:
                    await record_memory_event(
                        neoeats_db,
                        user_id=str(ctx.user_id),
                        event_type="receipt_item_confirmed",
                        source="receipt_confirm",
                        subject=str(memory_item.get("canonical_name") or memory_item.get("name") or ""),
                        payload=memory_item,
                        confidence=0.86,
                        embedding_provider=getattr(request.app.state, "llm_engine", None),
                        embedding_model=str(
                            getattr(getattr(request.app.state, "llm_engine", None), "embedding_model", "text-embedding-004")
                            or "text-embedding-004"
                        ),
                    )
                except Exception:
                    logger.exception("NeoEats receipt memory event recording failed")

        return ReceiptPersistResponse(
            receipt_id=receipt_id,
            items_saved=items_saved,
            store_prices_updated=store_prices_updated,
        )

    @router.get("/receipt/history")
    async def receipt_history(request: Request) -> list[dict]:
        db = request.app.state.seed.db
        ctx = authenticate(request, db)
        neoeats_db = await get_neoeats_db(request.app)

        rows = await neoeats_db.fetch(
            """
            SELECT id, image_url, total_amount, currency, merchant_name,
                   scanned_at, created_at
            FROM receipts
            WHERE user_id = $1
            ORDER BY scanned_at DESC
            LIMIT 50
            """,
            str(ctx.user_id),
        )

        return [
            {
                "id": str(r["id"]),
                "image_url": r.get("image_url"),
                "total_amount": float(r["total_amount"]),
                "currency": r["currency"],
                "merchant_name": r.get("merchant_name"),
                "scanned_at": r["scanned_at"].isoformat() if r.get("scanned_at") else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in (rows or [])
        ]

    return router
