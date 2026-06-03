import asyncio
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import httpx
import uvicorn
from asgi_lifespan import LifespanManager
from httpx_ws import aconnect_ws

pytest.importorskip("jwt")
pytest.importorskip("httpx_ws")

from fastapi import FastAPI

from app.api.ws.auth import JWTHandler
from app.api.ws.gateway import WebSocketGateway
from app.core.realtime.action_router import ActionRouter
from app.models.realtime import Action, ActionMetadata, ClientActionConfirm


def _build_app():
    app = FastAPI()
    mock_redis = AsyncMock()
    action_router_queue: asyncio.Queue = asyncio.Queue()
    response_queue: asyncio.Queue = asyncio.Queue()

    action_router = ActionRouter()
    jwt_handler = JWTHandler(secret_key="test-secret-key-change-this-32-bytes")

    gateway = WebSocketGateway(
        app=app,
        redis_client=mock_redis,
        action_router_queue=action_router_queue,
        jwt_handler=jwt_handler,
    )

    app.state.gateway = gateway
    app.state.action_router = action_router
    app.state.action_router_queue = action_router_queue
    app.state.response_queue = response_queue

    async def _forwarder():
        while True:
            try:
                response = await response_queue.get()
                if response is None:
                    break
                typ = response.get("type")
                sid = response.get("session_id")
                if typ == "model.invoke_action":
                    await gateway.broadcast_action_invoke(
                        session_id=sid,
                        trace_id=response.get("trace_id", ""),
                        action_id=response.get("action_id", ""),
                        action_type=response.get("action_type", ""),
                        parameters=response.get("parameters", {}),
                        requires_confirmation=response.get("requires_confirmation", False),
                    )
                elif typ == "action.result":
                    await gateway.broadcast_action_result(
                        session_id=sid,
                        trace_id=response.get("trace_id", ""),
                        action_id=response.get("action_id", ""),
                        action_type=response.get("action_type", ""),
                        status=response.get("status", ""),
                        result=response.get("result"),
                        error=response.get("error"),
                    )
                elif typ == "saga.update":
                    await gateway.broadcast_saga_update(
                        session_id=sid,
                        saga_id=response.get("saga_id", ""),
                        state=response.get("state", ""),
                        saga_type=response.get("saga_type"),
                        steps=response.get("steps"),
                        result=response.get("result"),
                        updated_at=response.get("updated_at"),
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.01)

    async def _consumer():
        while True:
            try:
                msg = await action_router_queue.get()
                if msg is None:
                    break
                session_id = msg.get("session_id")
                msg_type = msg.get("type")

                try:
                    if msg_type == "client.action.confirm":
                        confirm_request = ClientActionConfirm(
                            action_id=msg.get("action_id"),
                            confirm=msg.get("confirm", False),
                            reason=msg.get("reason"),
                        )
                        result = action_router.confirm_action(confirm_request, model_name="user")

                        await response_queue.put({
                            "type": "action.result",
                            "session_id": session_id,
                            "action_id": result.action_id,
                            "action_type": result.action_name,
                            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                            "result": result.result,
                            "error": result.error,
                        })

                except Exception:
                    await response_queue.put({
                        "type": "action.result",
                        "session_id": session_id,
                        "action_id": msg.get("action_id", "unknown"),
                        "action_type": msg.get("action_type", "unknown"),
                        "status": "failed",
                        "error": "consumer error",
                    })
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.01)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state._forward_task = asyncio.create_task(_forwarder())
        app.state._consumer_task = asyncio.create_task(_consumer())
        yield
        await response_queue.put(None)
        await action_router_queue.put(None)
        for tname in ("_forward_task", "_consumer_task"):
            t = getattr(app.state, tname, None)
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    app.router.lifespan_context = lifespan
    return app, jwt_handler, action_router, action_router_queue, response_queue


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@asynccontextmanager
async def _serve_app(app: FastAPI):
    port = _get_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
        ws="wsproto",
    )
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()

    def _run_server():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.serve())
        finally:
            if not loop.is_closed():
                loop.close()

    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.05)

    try:
        yield port, loop
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=5)


@pytest.mark.asyncio
async def test_ws_invoke_action_and_confirm_flow():
    app, jwt_handler, action_router, action_router_queue, response_queue = _build_app()

    async with LifespanManager(app):
        async with _serve_app(app) as (port, _loop):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                token = jwt_handler.create_token("user-xyz")

                async with aconnect_ws(f"ws://127.0.0.1:{port}/ws?token={token}", client=client) as ws:
                    conn = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    assert conn["type"] == "session.connected"
                    session_id = conn["session_id"]

                    action = Action(
                        id="act_test_001",
                        name="book_viewing",
                        params={"listing_id": "lst-1", "preferred_windows": ["2026-02-15T10:00:00"]},
                        metadata=ActionMetadata(session_id=session_id, user_id="user-xyz", requires_user_confirmation=True),
                    )
                    action_router._pending_confirmations[action.id] = {
                        "action": action,
                        "model_name": "model-x",
                        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
                    }

                    model_invoke = {
                        "type": "model.invoke_action",
                        "session_id": session_id,
                        "trace_id": "trace-1",
                        "action_id": action.id,
                        "action_type": "book_viewing",
                        "parameters": action.params,
                        "requires_confirmation": True,
                    }

                    await response_queue.put(model_invoke)

                    invoked = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    assert invoked["type"] == "model.invoke_action"
                    assert invoked["action_id"] == action.id

                    confirm_msg = {
                        "session_id": session_id,
                        "type": "client.action.confirm",
                        "action_id": action.id,
                        "confirm": True,
                        "reason": "Please proceed",
                    }

                    await action_router_queue.put(confirm_msg)

                    final = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    assert final["type"] == "action.result"
                    assert final["action_id"] == action.id
                    assert final["status"] in ("success", "failed")

                    assert action.id not in action_router._pending_confirmations

                    await ws.close()
                    if hasattr(ws, "_send_event"):
                        await ws._send_event.aclose()
                    if hasattr(ws, "_receive_event"):
                        await ws._receive_event.aclose()
