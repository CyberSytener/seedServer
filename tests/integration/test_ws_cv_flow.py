"""
WebSocket-level integration test: CV generation end-to-end.

Simulates:
1. Client connects via WS (JWT auth)
2. Model requests CV generation (model.invoke_action)
3. Client receives action preview on WS
4. (Optional: Client confirms if requires_confirmation=True)
5. ActionRouter executes CV creation
6. Server broadcasts result back to client over WS
7. Client receives CV ID and download URL

This is close to real client/server flow through the WebSocket gateway.
"""

import asyncio
import socket
import threading
import time
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
from app.core.realtime.executors import CreateOrUpdateCVExecutor
from app.models.realtime import Action, ActionMetadata


def _build_app():
    app = FastAPI()
    mock_redis = AsyncMock()
    action_router_queue: asyncio.Queue = asyncio.Queue()
    response_queue: asyncio.Queue = asyncio.Queue()

    action_router = ActionRouter()
    jwt_handler = JWTHandler(secret_key="test-secret-cv-change-this-32-bytes")

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

                if msg_type == "model.invoke_action":
                    import uuid

                    action_name = msg.get("action_name")
                    action_params = msg.get("params", {})
                    action_id = msg.get("action_id", f"act_{uuid.uuid4().hex[:12]}")

                    action = Action(
                        id=action_id,
                        name=action_name,
                        params=action_params,
                        metadata=ActionMetadata(
                            session_id=session_id,
                            user_id=msg.get("user_id", "user-cv"),
                            requires_user_confirmation=False,
                        ),
                    )

                    result = action_router.execute_action(action, model_name="model-cv")

                    result_data = result.result or {}
                    exec_data = result_data.get("data") if "data" in result_data else result_data

                    await response_queue.put({
                        "type": "action.result",
                        "session_id": session_id,
                        "trace_id": msg.get("trace_id", ""),
                        "action_id": result.action_id,
                        "action_type": result.action_name,
                        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                        "result": exec_data,
                        "error": result.error,
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
    return app, jwt_handler, action_router_queue, response_queue


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
async def test_ws_cv_generation_end_to_end():
    app, jwt_handler, action_router_queue, response_queue = _build_app()

    CreateOrUpdateCVExecutor.USER_CVS.clear()

    async with LifespanManager(app):
        async with _serve_app(app) as (port, _loop):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                token = jwt_handler.create_token("user-cv-ws")

                async with aconnect_ws(f"ws://127.0.0.1:{port}/ws?token={token}", client=client) as ws:
                    conn_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    assert conn_msg["type"] == "session.connected"
                    session_id = conn_msg["session_id"]

                    cv_action = {
                        "type": "model.invoke_action",
                        "session_id": session_id,
                        "trace_id": "trace-cv-1",
                        "action_id": "act_cv_001",
                        "action_name": "create_or_update_cv",
                        "action_type": "create_or_update_cv",
                        "user_id": "user-cv-ws",
                        "params": {
                            "user_id": "user-cv-ws",
                            "cv_payload": {
                                "personal": {"name": "Charlie Developer"},
                                "summary": "5 years backend experience",
                            },
                            "full_name": "Charlie Developer",
                            "sections": {
                                "summary": "5 years backend experience",
                                "experience": ["TechCorp - Senior Backend (2021-2026)"],
                            },
                            "format": ["pdf"],
                        },
                        "requires_confirmation": False,
                    }

                    await response_queue.put(cv_action)
                    await action_router_queue.put(cv_action)

                    first_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    second_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    message_types = {first_msg["type"], second_msg["type"]}

                    assert "model.invoke_action" in message_types
                    assert "action.result" in message_types

                    preview = first_msg if first_msg["type"] == "model.invoke_action" else second_msg
                    result_msg = first_msg if first_msg["type"] == "action.result" else second_msg

                    assert preview["action_id"] == "act_cv_001"
                    assert preview["action_type"] == "create_or_update_cv"
                    assert preview["requires_confirmation"] is False

                    assert result_msg["type"] == "action.result"
                    assert result_msg["action_id"] == "act_cv_001"
                    assert result_msg["action_type"] == "create_or_update_cv"
                    assert result_msg["status"] == "success"

                    result_data = result_msg["result"]
                    assert "cv_id" in result_data
                    assert "full_name" in result_data
                    assert "download_url" in result_data
                    assert "preview" in result_data

                    cv_id = result_data["cv_id"]
                    assert "/api/cv/" in result_data["download_url"]
                    assert cv_id in result_data["download_url"]

                    stored_cv = CreateOrUpdateCVExecutor.USER_CVS.get(cv_id)
                    assert stored_cv is not None
                    assert stored_cv["full_name"] == "Charlie Developer"
                    assert stored_cv["user_id"] == session_id

                    await ws.close()
                    if hasattr(ws, "_send_event"):
                        await ws._send_event.aclose()
                    if hasattr(ws, "_receive_event"):
                        await ws._receive_event.aclose()


@pytest.mark.asyncio
async def test_ws_cv_generation_with_validation_error():
    app, jwt_handler, action_router_queue, response_queue = _build_app()

    async with LifespanManager(app):
        async with _serve_app(app) as (port, _loop):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                token = jwt_handler.create_token("user-invalid-cv")

                async with aconnect_ws(f"ws://127.0.0.1:{port}/ws?token={token}", client=client) as ws:
                    conn_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    session_id = conn_msg["session_id"]

                    bad_action = {
                        "type": "model.invoke_action",
                        "session_id": session_id,
                        "trace_id": "trace-bad",
                        "action_id": "act_bad_cv",
                        "action_name": "create_or_update_cv",
                        "action_type": "create_or_update_cv",
                        "user_id": "user-invalid-cv",
                        "params": {
                            "sections": {"summary": "incomplete"},
                            "format": ["pdf"],
                        },
                        "requires_confirmation": False,
                    }

                    await response_queue.put(bad_action)
                    await action_router_queue.put(bad_action)

                    first_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    second_msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                    message_types = {first_msg["type"], second_msg["type"]}

                    assert "model.invoke_action" in message_types
                    assert "action.result" in message_types

                    result_msg = first_msg if first_msg["type"] == "action.result" else second_msg

                    assert result_msg["type"] == "action.result"
                    assert result_msg["action_id"] == "act_bad_cv"
                    assert result_msg["status"] == "failed"
                    assert result_msg["error"] is not None
                    assert "full_name" in result_msg["error"] or "user_id" in result_msg["error"]

                    await ws.close()
                    if hasattr(ws, "_send_event"):
                        await ws._send_event.aclose()
                    if hasattr(ws, "_receive_event"):
                        await ws._receive_event.aclose()
