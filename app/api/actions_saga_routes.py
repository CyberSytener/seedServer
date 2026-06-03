from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

import redis.asyncio as redis
from fastapi import APIRouter, FastAPI, HTTPException, Request

from app.core.auth import authenticate
from app.core.realtime.action_router import ActionRouter
from app.infrastructure.db.postgres import AsyncPGDatabase
from app.infrastructure.db.sqlite import DB
from app.models.neoeats import FridgeItem
from app.models.realtime import Action as RealtimeAction
from app.services.pantry_normalizer import (
    canonicalize_product,
    extract_items_from_message,
    normalize_quantity_unit,
)
from app.services.neoeats_memory_controls import (
    memory_learning_enabled,
    memory_retrieval_enabled,
    safe_meta_json,
)
from app.services.neoeats_rag_memory import (
    memory_context_from_events,
    record_memory_event,
    retrieve_memory_events,
)
from app.services.product_normalize import (
    _coerce_date_safe,
    _upsert_storage_item_for_user,
)
from app.api.inventory_orders_vision_routes import _fridge_item_from_row
from app.settings import get_settings


def build_actions_saga_router(
    *,
    db: DB,
    action_router: ActionRouter,
    r: redis.Redis,
    saga_orchestrator: Any | None = None,
    build_action_from_message: Callable[[Dict[str, Any]], Optional[RealtimeAction]],
    get_neoeats_db: Callable[[FastAPI], Any],
) -> APIRouter:
    router = APIRouter()
    public_mode = get_settings().public_mode

    # ---- handlers --------------------------------------------------------

    if not public_mode:
        @router.post("/api/v1/test/action-echo")
        async def test_action_echo(request: Request):
            """Debug endpoint: echo back payload with parsing diagnostics."""
            ctx = authenticate(request, db)
            try:
                payload = await request.json()
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"JSON parse failed: {str(e)[:200]}",
                    "payload": None,
                }

            action = build_action_from_message(payload)
            return {
                "status": "ok" if action else "missing_required_fields",
                "payload_keys": list(payload.keys()) if isinstance(payload, dict) else None,
                "action_built": bool(action),
                "action_name": action.name if action else None,
                "action_id": action.id if action else None,
                "session_id": action.metadata.session_id if action and action.metadata else None,
            }

    @router.post("/api/v1/actions/invoke")
    async def api_actions_invoke(request: Request):
        app = request.app
        ctx = authenticate(request, db)
        try:
            payload = await request.json()
        except Exception as e:
            logging.error("Failed to parse JSON body: %s", str(e)[:200])
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        if not isinstance(payload, dict):
            logging.error("Payload is not a dict: %s", type(payload).__name__)
            raise HTTPException(status_code=400, detail="Payload must be JSON object")

        payload.setdefault("user_id", ctx.user_id)
        payload.setdefault("session_id", payload.get("session_id") or ctx.user_id)

        action = build_action_from_message(payload)
        if not action:
            logging.warning(
                "Failed to build action from payload. Attempting auto-fix. payload keys=%s",
                list(payload.keys()),
            )
            action_name = (
                payload.get("action", {}).get("name")
                or payload.get("action_type")
                or payload.get("name")
                or "chat"
            )
            if not isinstance(payload.get("action"), dict):
                payload["action"] = {}

            if not payload["action"].get("id"):
                payload["action"]["id"] = f"action_{uuid.uuid4().hex[:12]}"
                logging.warning("Generated action.id: %s", payload["action"]["id"])

            if not payload["action"].get("name"):
                payload["action"]["name"] = action_name
                logging.warning("Set action.name: %s", action_name)

            if not payload.get("session_id"):
                payload["session_id"] = ctx.user_id
                logging.warning("Set session_id: %s", payload["session_id"])

            if not payload["action"].get("metadata"):
                payload["action"]["metadata"] = {}

            if not payload["action"]["metadata"].get("session_id"):
                payload["action"]["metadata"]["session_id"] = payload.get("session_id") or ctx.user_id
                logging.warning("Set metadata.session_id: %s", payload["action"]["metadata"]["session_id"])

            action = build_action_from_message(payload)
            if action:
                logging.info("Auto-fix successful: action built with name=%s, id=%s", action.name, action.id)
            else:
                logging.error("Auto-fix failed. Final payload: action=%s, session_id=%s", payload.get("action"), payload.get("session_id"))

        if not action:
            raise HTTPException(status_code=400, detail="Invalid action.invoke payload")

        def _extract_message() -> str:
            params = action.params or {}
            if isinstance(params, dict):
                msg = str(params.get("message") or params.get("text") or "").strip()
                if msg:
                    return msg
            return str((((payload.get("action") or {}).get("args") or {}).get("message")) or "").strip()

        def _infer_intent(message: str) -> str:
            text = (message or "").lower()
            cook_markers = [
                "what can i cook", "what should i cook", "recipe", "recipes", "meal", "cook", "hybrid",
            ]
            add_markers = [
                "add", "added", "put", "store", "fridge", "inventory", "bought", "receipt", "scan",
                "купил", "купила", "добавь", "добавил", "холодильник", "инвентарь",
                "kjopt", "kjøpt", "legg til", "kjoleskap", "kjøleskap",
            ]
            if any(marker in text for marker in cook_markers):
                return "cook"
            if any(marker in text for marker in add_markers):
                return "add_food"
            return "chat"

        def _extract_structured_items() -> List[Dict[str, Any]]:
            params = action.params or {}
            candidates = []
            if isinstance(params, dict):
                if isinstance(params.get("items"), list):
                    candidates = params.get("items")
                elif isinstance(params.get("item"), dict):
                    candidates = [params.get("item")]

            normalized: List[Dict[str, Any]] = []
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                brand = str(item.get("brand") or "").strip() or None
                canonicalized = canonicalize_product(name, brand=brand, preferred_language="en")
                quantity, unit = normalize_quantity_unit(
                    item.get("quantity"),
                    item.get("unit"),
                    name=name,
                )
                normalized.append(
                    {
                        "name": str(canonicalized.get("display_name") or name).strip(),
                        "canonical_name": str(canonicalized.get("canonical_name") or "").strip(),
                        "display_name": str(canonicalized.get("display_name") or name).strip(),
                        "category": item.get("category") or canonicalized.get("category"),
                        "quantity": quantity,
                        "unit": unit,
                        "confidence": float(item.get("confidence") or 0.9),
                        "expires_at": item.get("expires_at"),
                        "brand": brand,
                        "original_name": name,
                    }
                )
            return normalized

        def _extract_items_from_text(message: str) -> List[Dict[str, Any]]:
            return extract_items_from_message(message)

        async def _persist_detected_items(user_id: str, detected_items: List[Dict[str, Any]], *, source: str) -> List[FridgeItem]:
            if not detected_items:
                return []
            neoeats_db = await get_neoeats_db(app)
            created: List[FridgeItem] = []
            async with neoeats_db.transaction() as conn:
                for item in detected_items:
                    original_name = str(item.get("original_name") or item.get("name") or "").strip()
                    name = str(item.get("canonical_name") or item.get("name") or "").strip()
                    if not name:
                        continue
                    brand = str(item.get("brand") or "").strip() or None
                    canonicalized = canonicalize_product(name, brand=brand, preferred_language="en")
                    display_name = str(canonicalized.get("display_name") or name).strip()
                    canonical_name = str(canonicalized.get("canonical_name") or name).strip().lower()
                    category = str(item.get("category") or canonicalized.get("category") or "").strip() or None
                    quantity, unit = normalize_quantity_unit(
                        item.get("quantity"),
                        item.get("unit"),
                        name=display_name,
                    )
                    try:
                        confidence_raw = float(item.get("confidence") or item.get("confidence_score") or 0.8)
                    except Exception:
                        confidence_raw = 0.8
                    confidence_ratio = confidence_raw / 100.0 if confidence_raw > 1.0 else confidence_raw
                    metadata = {
                        "user_id": user_id,
                        "source": source,
                        "confidence": max(0.0, min(1.0, confidence_ratio)),
                        "brand": brand,
                        "canonical_name": canonical_name,
                        "display_name": display_name,
                        "category": category,
                        "original_name": original_name or display_name,
                        "product_id": str(
                            item.get("product_id")
                            or canonicalized.get("product_id")
                            or hashlib.sha1(f"canon|{canonical_name}".encode("utf-8")).hexdigest()[:20]
                        ),
                    }
                    row = await _upsert_storage_item_for_user(
                        conn,
                        user_id=user_id,
                        name=display_name,
                        quantity=quantity,
                        unit=unit,
                        expires_at=_coerce_date_safe(item.get("expires_at") or item.get("expiry_date")),
                        metadata=metadata,
                    )
                    if row:
                        created.append(_fridge_item_from_row(dict(row)))
            for item in created:
                try:
                    payload = item.model_dump()
                    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                    await record_memory_event(
                        neoeats_db,
                        user_id=user_id,
                        event_type="pantry_item_confirmed",
                        source=source,
                        subject=str(payload.get("display_name") or payload.get("name") or "").strip() or None,
                        payload={
                            "item": payload,
                            "item_id": payload.get("item_id"),
                            "product_id": metadata.get("product_id"),
                            "canonical_name": payload.get("canonical_name") or metadata.get("canonical_name"),
                            "display_name": payload.get("display_name") or payload.get("name"),
                            "category": payload.get("category") or metadata.get("category"),
                        },
                        confidence=float(metadata.get("confidence") or 0.82),
                        embedding_provider=getattr(app.state, "llm_engine", None),
                        embedding_model=str(
                            getattr(getattr(app.state, "llm_engine", None), "embedding_model", "text-embedding-004")
                            or "text-embedding-004"
                        ),
                    )
                except Exception:
                    logging.exception("NeoEats action pantry memory event recording failed")
            return created

        def _load_neoeats_user_memory(user_id: str) -> Dict[str, Any]:
            row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (user_id,))
            if not row:
                return {}
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            if not isinstance(meta, dict):
                return {}
            memory = meta.get("neoeats_memory")
            return memory if isinstance(memory, dict) else {}

        def _save_neoeats_user_memory(user_id: str, memory: Dict[str, Any]) -> None:
            row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (user_id,))
            try:
                meta = json.loads(row["meta_json"] or "{}") if row else {}
            except Exception:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            meta["neoeats_memory"] = memory
            meta_json = json.dumps(meta, ensure_ascii=False)
            if row:
                db.execute("UPDATE users SET meta_json = ? WHERE id = ?", (meta_json, user_id))
            else:
                db.execute(
                    "INSERT INTO users(id, meta_json, is_admin, is_banned) VALUES(?,?,0,0)",
                    (user_id, meta_json),
                )

        async def _load_neoeats_rag_memory_context(user_id: str, message: str) -> Dict[str, Any]:
            try:
                row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (user_id,))
                meta = safe_meta_json(row["meta_json"] if row else {})
                if not memory_retrieval_enabled(meta):
                    return memory_context_from_events([])
                neoeats_db = await get_neoeats_db(app)
                events = await retrieve_memory_events(
                    neoeats_db,
                    user_id=user_id,
                    query=message,
                    limit=10,
                    lookback=160,
                    embedding_provider=getattr(app.state, "llm_engine", None),
                    embedding_model=str(
                        getattr(getattr(app.state, "llm_engine", None), "embedding_model", "text-embedding-004")
                        or "text-embedding-004"
                    ),
                )
                return memory_context_from_events(events)
            except Exception:
                logging.exception("NeoEats RAG memory retrieval failed")
                return memory_context_from_events([])

        async def _record_neoeats_memory_event(
            user_id: str,
            *,
            event_type: str,
            source: str,
            subject: Optional[str] = None,
            payload: Optional[Dict[str, Any]] = None,
            text: Optional[str] = None,
            confidence: float = 0.72,
        ) -> None:
            try:
                row = db.fetchone("SELECT meta_json FROM users WHERE id = ?", (user_id,))
                meta = safe_meta_json(row["meta_json"] if row else {})
                if not memory_learning_enabled(meta, source=source):
                    return
                neoeats_db = await get_neoeats_db(app)
                await record_memory_event(
                    neoeats_db,
                    user_id=user_id,
                    event_type=event_type,
                    source=source,
                    subject=subject,
                    payload=payload or {},
                    text=text,
                    confidence=confidence,
                    embedding_provider=getattr(app.state, "llm_engine", None),
                    embedding_model=str(
                        getattr(getattr(app.state, "llm_engine", None), "embedding_model", "text-embedding-004")
                        or "text-embedding-004"
                    ),
                )
            except Exception:
                logging.exception("NeoEats chat memory event recording failed")

        if str(action.name or "").lower() == "chat":
            from app.api.neoeats_chat import handle_neoeats_chat

            return await handle_neoeats_chat(
                app=app,
                action=action,
                ctx=ctx,
                payload=payload,
                get_neoeats_db=lambda: get_neoeats_db(app),
                persist_detected_items=_persist_detected_items,
                coerce_date_safe=_coerce_date_safe,
                load_user_memory=_load_neoeats_user_memory,
                save_user_memory=_save_neoeats_user_memory,
                load_rag_memory_context=_load_neoeats_rag_memory_context,
                record_user_memory_event=_record_neoeats_memory_event,
            )

        result = action_router.execute_action(action, model_name="client")

        return {
            "type": "action.result",
            "session_id": action.metadata.session_id,
            "action_id": result.action_id,
            "action_type": result.action_name,
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            "result": result.result,
            "error": result.error,
        }

    @router.post("/api/v1/chat")
    async def api_chat_fallback(request: Request):
        ctx = authenticate(request, db)
        payload = await request.json() if request.headers.get("content-length") else {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        msg = str(payload.get("message") or "").strip()
        if not msg:
            msg = str(((payload.get("action") or {}).get("args") or {}).get("message") or "").strip()

        return {
            "persona_message": "How can I help with your NeoEats flow?" if not msg else f"Got it, {ctx.user_id}. {msg}",
            "detected_items": [],
            "inventory_persisted": False,
            "recommendations": [],
            "flavor_architect": [],
        }

    @router.post("/api/v1/actions/{action_id}/confirm")
    async def api_actions_confirm(action_id: str, request: Request):
        ctx = authenticate(request, db)
        payload = await request.json() if request.headers.get("content-length") else {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        from app.models.realtime import ClientActionConfirm

        confirm_request = ClientActionConfirm(
            action_id=action_id,
            confirm=payload.get("confirm", False),
            reason=payload.get("reason"),
        )

        # Idempotency for confirm (Redis)
        try:
            cached = await r.get(f"idempotency:confirm:{action_id}:result")
            if cached:
                return json.loads(cached.decode() if isinstance(cached, (bytes, bytearray)) else cached)
            reserved = await r.set(
                f"idempotency:confirm:{action_id}:status",
                "PENDING",
                ex=3600,
                nx=True,
            )
            if reserved is False:
                return {
                    "type": "action.result",
                    "session_id": payload.get("session_id") or ctx.user_id,
                    "action_id": action_id,
                    "action_type": payload.get("action_type", "unknown"),
                    "status": "pending",
                    "result": {"message": "Confirmation already in progress"},
                }
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        result = await action_router.resume_on_confirmation(confirm_request, model_name="user")

        response_payload = {
            "type": "action.result",
            "session_id": payload.get("session_id") or ctx.user_id,
            "action_id": result.action_id,
            "action_type": result.action_name,
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            "result": result.result,
            "error": result.error,
        }

        try:
            await r.set(
                f"idempotency:confirm:{action_id}:result",
                json.dumps(response_payload),
                ex=3600,
            )
            await r.set(
                f"idempotency:confirm:{action_id}:status",
                "DONE",
                ex=3600,
            )
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        return response_payload

    @router.post("/api/v1/actions/{action_id}/cancel")
    async def api_actions_cancel(action_id: str, request: Request):
        ctx = authenticate(request, db)
        payload = await request.json() if request.headers.get("content-length") else {}
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        from app.models.realtime import ClientActionConfirm

        confirm_request = ClientActionConfirm(
            action_id=action_id,
            confirm=False,
            reason=payload.get("reason") or "cancelled",
        )

        # Idempotency for cancel (Redis)
        try:
            cached = await r.get(f"idempotency:confirm:{action_id}:result")
            if cached:
                return json.loads(cached.decode() if isinstance(cached, (bytes, bytearray)) else cached)
            reserved = await r.set(
                f"idempotency:confirm:{action_id}:status",
                "PENDING",
                ex=3600,
                nx=True,
            )
            if reserved is False:
                return {
                    "type": "action.result",
                    "session_id": payload.get("session_id") or ctx.user_id,
                    "action_id": action_id,
                    "action_type": payload.get("action_type", "unknown"),
                    "status": "pending",
                    "result": {"message": "Cancellation already in progress"},
                }
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        result = await action_router.resume_on_confirmation(confirm_request, model_name="user")

        response_payload = {
            "type": "action.result",
            "session_id": payload.get("session_id") or ctx.user_id,
            "action_id": result.action_id,
            "action_type": result.action_name,
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            "result": result.result,
            "error": result.error,
        }

        try:
            await r.set(
                f"idempotency:confirm:{action_id}:result",
                json.dumps(response_payload),
                ex=3600,
            )
            await r.set(
                f"idempotency:confirm:{action_id}:status",
                "DONE",
                ex=3600,
            )
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        return response_payload

    @router.get("/api/v1/sagas/{saga_id}")
    async def api_get_saga(saga_id: str, request: Request):
        authenticate(request, db)
        if saga_orchestrator is None:
            raise HTTPException(status_code=503, detail="Saga orchestrator not available")

        saga = await saga_orchestrator.get_saga_state(saga_id)
        if not saga:
            raise HTTPException(status_code=404, detail="Saga not found")

        return {
            "saga_id": saga.get("saga_id"),
            "saga_type": saga.get("saga_type"),
            "saga_version": saga.get("saga_version"),
            "state": saga.get("state"),
            "steps": saga.get("steps"),
            "result": saga.get("result"),
            "updated_at": saga.get("updated_at"),
        }

    @router.get("/api/v1/sagas/{saga_id}/audit")
    async def api_get_saga_audit(saga_id: str, request: Request):
        authenticate(request, db)
        if saga_orchestrator is None:
            raise HTTPException(status_code=503, detail="Saga orchestrator not available")

        audit = await saga_orchestrator.get_saga_audit(saga_id)
        if audit.get("error"):
            raise HTTPException(status_code=404, detail=audit.get("error"))

        return audit

    return router
