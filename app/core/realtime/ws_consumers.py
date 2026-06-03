"""WebSocket consumer functions for realtime message routing."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

import redis.asyncio as redis

from app.api.ws.gateway import WebSocketGateway
from app.core.realtime.action_router import ActionRouter
from app.models.realtime import Action as RealtimeAction, Action, ActionMetadata, ClientActionConfirm


async def forward_router_responses(
    gateway: WebSocketGateway,
    response_queue: asyncio.Queue,
):
    """Forward router/saga responses to WebSocket clients."""
    while True:
        try:
            response = await response_queue.get()
            session_id = response.get("session_id")
            msg_type = response.get("type")

            if msg_type == "model.partial":
                await gateway.broadcast_partial(
                    session_id=session_id,
                    trace_id=response.get("trace_id", ""),
                    content=response.get("content", ""),
                    index=response.get("index", 0),
                )
            elif msg_type == "model.final":
                await gateway.broadcast_final(
                    session_id=session_id,
                    trace_id=response.get("trace_id", ""),
                    content=response.get("content", ""),
                    actions=response.get("actions"),
                )
            elif msg_type == "model.invoke_action":
                await gateway.broadcast_action_invoke(
                    session_id=session_id,
                    trace_id=response.get("trace_id", ""),
                    action_id=response.get("action_id", ""),
                    action_type=response.get("action_type", ""),
                    parameters=response.get("parameters", {}),
                    requires_confirmation=response.get("requires_confirmation", False),
                )
            elif msg_type == "action.result":
                await gateway.broadcast_action_result(
                    session_id=session_id,
                    trace_id=response.get("trace_id", ""),
                    action_id=response.get("action_id", ""),
                    action_type=response.get("action_type", ""),
                    status=response.get("status", ""),
                    result=response.get("result"),
                    error=response.get("error"),
                )
            elif msg_type == "saga.update":
                await gateway.broadcast_saga_update(
                    session_id=session_id,
                    saga_id=response.get("saga_id", ""),
                    saga_type=response.get("saga_type"),
                    state=response.get("state", ""),
                    steps=response.get("steps"),
                    result=response.get("result"),
                    updated_at=response.get("updated_at"),
                )
            elif msg_type in ("action.deferred", "action.timeout"):
                await gateway.broadcast_action_deferred(
                    session_id=session_id,
                    action_id=response.get("action_id", ""),
                    action_type=response.get("action_type", ""),
                    status=response.get("status", "pending_user"),
                    reason=response.get("reason"),
                    expires_at=response.get("expires_at"),
                )
            elif msg_type == "saga.status":
                await gateway.send_to_client(session_id=session_id, message=response)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Realtime forwarder error: {e}")
            await asyncio.sleep(0.1)


def _build_action_from_message(msg: Dict[str, Any]) -> Optional[RealtimeAction]:
    action_payload = msg.get("action") or {}

    action_name = (
        action_payload.get("name")
        or msg.get("action_type")
        or msg.get("name")
    )
    action_id = (
        action_payload.get("id")
        or msg.get("action_id")
        or msg.get("id")
    )
    
    if not action_id:
        action_id = f"action_{uuid.uuid4().hex[:12]}"

    action_params = (
        action_payload.get("params")
        or action_payload.get("args")
        or msg.get("params")
        or msg.get("parameters")
        or msg.get("args")
    )

    if action_params is None:
        reserved = {
            "type",
            "action",
            "action_type",
            "action_id",
            "id",
            "session_id",
            "user_id",
            "trace_id",
            "metadata",
            "confirm",
            "reason",
        }
        action_params = {k: v for k, v in msg.items() if k not in reserved}

    metadata_payload = action_payload.get("metadata") or msg.get("metadata") or {}
    metadata_payload = dict(metadata_payload) if isinstance(metadata_payload, dict) else {}

    if msg.get("session_id") and not metadata_payload.get("session_id"):
        metadata_payload["session_id"] = msg.get("session_id")
    if msg.get("user_id") and not metadata_payload.get("user_id"):
        metadata_payload["user_id"] = msg.get("user_id")

    if not action_name or not metadata_payload.get("session_id"):
        return None

    return Action(
        name=action_name,
        id=action_id,
        params=action_params or {},
        metadata=ActionMetadata(**metadata_payload),
    )


async def consume_action_router_messages(
    action_router: ActionRouter,
    action_router_queue: asyncio.Queue,
    response_queue: asyncio.Queue,
    redis_client: Optional[redis.Redis] = None,
    confirm_ttl_seconds: int = 3600,
):
    """Consume client messages from WebSocket and invoke ActionRouter."""

    async def _confirm_idempotency_get(action_id: str) -> Optional[Dict[str, Any]]:
        if not redis_client:
            return None
        key = f"idempotency:confirm:{action_id}:result"
        cached = await redis_client.get(key)
        if not cached:
            return None
        try:
            return json.loads(cached.decode() if isinstance(cached, (bytes, bytearray)) else cached)
        except Exception:
            return None

    async def _confirm_idempotency_reserve(action_id: str) -> bool:
        if not redis_client:
            return True
        key = f"idempotency:confirm:{action_id}:status"
        try:
            return await redis_client.set(key, "PENDING", ex=confirm_ttl_seconds, nx=True)
        except Exception:
            return True

    async def _confirm_idempotency_store(action_id: str, payload: Dict[str, Any]) -> None:
        if not redis_client:
            return
        try:
            result_key = f"idempotency:confirm:{action_id}:result"
            status_key = f"idempotency:confirm:{action_id}:status"
            await redis_client.set(result_key, json.dumps(payload), ex=confirm_ttl_seconds)
            await redis_client.set(status_key, "DONE", ex=confirm_ttl_seconds)
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
    while True:
        try:
            msg = await action_router_queue.get()
            session_id = msg.get("session_id")
            msg_type = msg.get("type")
            
            try:
                # Route to appropriate ActionRouter method based on message type
                if msg_type in ("client.action.confirm", "action.confirm"):
                    cached = await _confirm_idempotency_get(msg.get("action_id", ""))
                    if cached:
                        await response_queue.put(cached)
                        continue

                    reserved = await _confirm_idempotency_reserve(msg.get("action_id", ""))
                    if reserved is False:
                        await response_queue.put({
                            "type": "action.result",
                            "session_id": session_id,
                            "action_id": msg.get("action_id", "unknown"),
                            "action_type": msg.get("action_type", "unknown"),
                            "status": "pending",
                            "result": {"message": "Confirmation already in progress"},
                        })
                        continue

                    confirm_request = ClientActionConfirm(
                        action_id=msg.get("action_id"),
                        confirm=msg.get("confirm", False),
                        reason=msg.get("reason"),
                    )
                    result = await action_router.resume_on_confirmation(confirm_request, model_name="user")

                    response_payload = {
                        "type": "action.result",
                        "session_id": session_id,
                        "action_id": result.action_id,
                        "action_type": result.action_name,
                        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                        "result": result.result,
                        "error": result.error,
                    }
                    await _confirm_idempotency_store(result.action_id, response_payload)
                    await response_queue.put(response_payload)

                elif msg_type == "action.cancel":
                    cached = await _confirm_idempotency_get(msg.get("action_id", ""))
                    if cached:
                        await response_queue.put(cached)
                        continue

                    reserved = await _confirm_idempotency_reserve(msg.get("action_id", ""))
                    if reserved is False:
                        await response_queue.put({
                            "type": "action.result",
                            "session_id": session_id,
                            "action_id": msg.get("action_id", "unknown"),
                            "action_type": msg.get("action_type", "unknown"),
                            "status": "pending",
                            "result": {"message": "Cancellation already in progress"},
                        })
                        continue

                    confirm_request = ClientActionConfirm(
                        action_id=msg.get("action_id"),
                        confirm=False,
                        reason=msg.get("reason") or "cancelled",
                    )
                    result = await action_router.resume_on_confirmation(confirm_request, model_name="user")

                    response_payload = {
                        "type": "action.result",
                        "session_id": session_id,
                        "action_id": result.action_id,
                        "action_type": result.action_name,
                        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                        "result": result.result,
                        "error": result.error,
                    }
                    await _confirm_idempotency_store(result.action_id, response_payload)
                    await response_queue.put(response_payload)

                elif msg_type in ("action.invoke", "model.invoke_action"):
                    action = _build_action_from_message(msg)
                    if not action:
                        await response_queue.put({
                            "type": "action.result",
                            "session_id": session_id,
                            "action_id": msg.get("action_id", "unknown"),
                            "action_type": msg.get("action_type", "unknown"),
                            "status": "failed",
                            "error": "Invalid action.invoke payload",
                        })
                        continue

                    result = action_router.execute_action(action, model_name="client")

                    await response_queue.put({
                        "type": "action.result",
                        "session_id": session_id,
                        "action_id": result.action_id,
                        "action_type": result.action_name,
                        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                        "result": result.result,
                        "error": result.error,
                    })

                elif msg_type == "saga.status":
                    saga_id = msg.get("saga_id") or msg.get("id")
                    if not saga_id:
                        await response_queue.put({
                            "type": "saga.status",
                            "session_id": session_id,
                            "error": "Missing saga_id",
                        })
                        continue

                    if action_router.saga_orchestrator is None:
                        await response_queue.put({
                            "type": "saga.status",
                            "session_id": session_id,
                            "saga_id": saga_id,
                            "error": "Saga orchestrator not available",
                        })
                        continue

                    saga = await action_router.saga_orchestrator.get_saga_state(saga_id)
                    if not saga:
                        await response_queue.put({
                            "type": "saga.status",
                            "session_id": session_id,
                            "saga_id": saga_id,
                            "error": "Saga not found",
                        })
                        continue

                    await response_queue.put({
                        "type": "saga.status",
                        "session_id": session_id,
                        "saga_id": saga_id,
                        "saga_type": saga.get("saga_type"),
                        "state": saga.get("state"),
                        "steps": saga.get("steps"),
                        "result": saga.get("result"),
                        "updated_at": saga.get("updated_at"),
                    })

                else:
                    logging.debug(f"Unhandled message type in action router: {msg_type}")

            except Exception as e:
                logging.error(f"Error processing action router message: {e}")
                await response_queue.put({
                    "type": "action.result",
                    "session_id": session_id,
                    "action_id": msg.get("action_id", "unknown"),
                    "action_type": msg.get("action_type", "unknown"),
                    "status": "failed",
                    "error": str(e),
                })
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Action router consumer error: {e}")
            await asyncio.sleep(0.1)
