"""
FastAPI WebSocket Gateway - STEP 3.

"Dumb pipe" architecture:
- No business logic validation
- No knowledge of action semantics
- No duplication of confirmation/retry logic

Responsibilities:
- Accept WebSocket connections (JWT auth)
- Manage sessions (Redis store)
- Stream messages (partials → finals)
- Proxy invoke_action → Action Router
- Handle graceful disconnect/reconnect

All business logic stays in ActionRouter (STEP 2).
"""

import json
import asyncio
import logging
from typing import Optional, Dict, Any, Set

try:
    import redis.asyncio as redis
except ImportError:
    import aioredis as redis

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
    from fastapi.encoders import jsonable_encoder
except ImportError:
    FastAPI = WebSocket = WebSocketDisconnect = Query = None
    jsonable_encoder = None

from .types import (
    MessageType,
    ClientMessage,
    ModelPartial,
    ModelFinal,
    ModelInvokeAction,
    ActionResult,
    SagaUpdate,
    SessionConnected,
    SessionReconnected,
    SessionError,
)
from .session import RedisSessionStore
from .auth import JWTHandler


logger = logging.getLogger(__name__)


class WebSocketGateway:
    """
    WebSocket gateway - pure message transport layer.
    
    No business logic. Just:
    1. Auth via JWT
    2. Route messages between client and Action Router
    3. Stream responses
    4. Manage sessions for reconnect/resume
    5. Delegate agent.* messages to AgentWebSocketHandler
    """
    
    def __init__(
        self,
        app: FastAPI,
        redis_client: redis.Redis,
        action_router_queue: asyncio.Queue,  # Queue to send messages to router
        jwt_handler: JWTHandler = None,
        send_timeout_seconds: float = 5.0,
        agent_handler: "AgentWebSocketHandler | None" = None,
    ):
        """
        Initialize gateway.
        
        Args:
            app: FastAPI application
            redis_client: Redis async client (for session store)
            action_router_queue: Queue to pass ClientMessage to router
            jwt_handler: JWT validator (default: create new)
            agent_handler: Optional AgentWebSocketHandler for agent streaming
        """
        self.app = app
        self.redis = redis_client
        self.router_queue = action_router_queue
        self.jwt_handler = jwt_handler or JWTHandler()
        self.session_store = RedisSessionStore(redis_client)
        self.send_timeout_seconds = send_timeout_seconds
        self.agent_handler = agent_handler
        
        # Track active connections: session_id → WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_lock = asyncio.Lock()
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Register WebSocket endpoint."""
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(
            websocket: WebSocket,
            token: str = Query(...),  # JWT token as query param
            session_id: Optional[str] = Query(None),  # Optional for reconnect
        ):
            """
            Main WebSocket endpoint.
            
            Flow:
            1. Validate JWT token
            2. Create/resume session
            3. Listen for client messages
            4. Stream responses from router
            5. Forward actions to router
            """
            
            # STEP 1: Validate JWT
            user_id = self.jwt_handler.extract_user_id(token)
            if not user_id:
                await websocket.close(code=4001, reason="Unauthorized")
                return
            
            # STEP 2: Create or resume session
            if session_id:
                # Reconnect case: resume existing session
                existing_session = await self.session_store.get_session(session_id)
                if not existing_session:
                    await websocket.close(code=4002, reason="Session expired")
                    return
                
                if existing_session.get("user_id") != user_id:
                    await websocket.close(code=4003, reason="Session mismatch")
                    return
            else:
                # New connection: create session
                session_id = await self.session_store.create_session(user_id)
            
            # Store connection
            async with self.connection_lock:
                self.active_connections[session_id] = websocket
            
            try:
                await websocket.accept()
                
                # Notify client: connected
                connected_msg = SessionConnected(
                    session_id=session_id,
                    user_id=user_id,
                )
                await websocket.send_json(self._to_jsonable(connected_msg))
                
                # STEP 3: Send pending messages if reconnect
                if session_id in self.active_connections:  # Already connected
                    pending = await self.session_store.get_pending_messages(session_id)
                    if pending:
                        reconnected_msg = SessionReconnected(
                            session_id=session_id,
                            user_id=user_id,
                            pending_messages=pending,
                        )
                        await websocket.send_json(self._to_jsonable(reconnected_msg))
                
                # STEP 4: Main message loop
                await self._message_loop(websocket, session_id, user_id)
            
            except WebSocketDisconnect:
                logger.info(f"Client disconnected: {session_id}")
                async with self.connection_lock:
                    self.active_connections.pop(session_id, None)
            
            except Exception as e:
                logger.error(f"WebSocket error: {session_id}, {e}")
                error_msg = SessionError(
                    session_id=session_id,
                    error=str(e),
                    recoverable=True,
                )
                try:
                    await websocket.send_json(self._to_jsonable(error_msg))
                except Exception:
                    logger.debug("Failed to send error message to WebSocket client", exc_info=True)
                
                async with self.connection_lock:
                    self.active_connections.pop(session_id, None)
    
    async def _message_loop(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: str,
    ):
        """
        Main loop: listen for client messages, send to router, stream responses.
        """
        
        # Task 1: Receive from client
        async def receive_from_client():
            while True:
                try:
                    data = await websocket.receive_json()
                    yield data
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Receive error: {e}")
                    break
        
        # Task 2: Send client messages to router
        async def forward_to_router(data: Dict[str, Any]):
            """Forward client message to Action Router."""
            try:
                msg = ClientMessage(
                    session_id=session_id,
                    user_id=user_id,
                    content=data.get("content", ""),
                    trace_id=data.get("trace_id"),
                )
                
                # Queue message for router to process
                await self.router_queue.put(msg.model_dump())
                
                # Store trace_id for correlation
                if msg.trace_id:
                    await self.session_store.set_trace_id(session_id, msg.trace_id)
            
            except Exception as e:
                logger.error(f"Forward error: {e}")
        
        # Task 3: Stream responses from router (via queue)
        async def stream_responses():
            """Receive messages from router and stream to client."""
            # In production, this would be connected to router's response queue
            # For now, just listen for any responses meant for this session
            while True:
                try:
                    # This would be populated by router
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    break
        
        # Run receive and forward concurrently
        client_task = asyncio.create_task(
            self._client_receive_handler(websocket, session_id, user_id)
        )
        response_task = asyncio.create_task(stream_responses())

        try:
            done, pending = await asyncio.wait(
                {client_task, response_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        finally:
            client_task.cancel()
            response_task.cancel()
    
    async def _client_receive_handler(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: str,
    ):
        """Handle incoming client messages."""
        while True:
            try:
                data = await websocket.receive_json()
                
                # Update session activity
                await self.session_store.update_activity(session_id)
                
                # Delegate agent.* messages to AgentWebSocketHandler
                msg_type = data.get("type", "") if isinstance(data, dict) else ""
                if isinstance(msg_type, str) and msg_type.startswith("agent.") and self.agent_handler:
                    async def _send_to_ws(payload: dict) -> None:
                        await self.send_to_client(session_id, payload)
                    await self.agent_handler.handle_agent_message(
                        session_id, data, _send_to_ws,
                    )
                    continue
                
                # Forward to router (preserve message type if provided)
                if isinstance(data, dict):
                    payload = dict(data)
                else:
                    payload = {"data": data}

                payload.setdefault("type", "client.message")
                payload.setdefault("session_id", session_id)
                payload.setdefault("user_id", user_id)

                await self.router_queue.put(payload)
            
            except WebSocketDisconnect:
                # Notify agent handler of disconnect
                if self.agent_handler:
                    await self.agent_handler.on_ws_disconnect(session_id)
                break
            except Exception as e:
                logger.error(f"Receive handler error: {e}")
                break
    
    async def send_to_client(
        self,
        session_id: str,
        message: Dict[str, Any],
    ) -> bool:
        """
        Send message to connected client.
        
        If client disconnected, queue message for reconnect.
        
        Returns:
            True if sent, False if queued
        """
        async with self.connection_lock:
            websocket = self.active_connections.get(session_id)
        
        if websocket:
            try:
                payload = self._to_jsonable(message)
                await asyncio.wait_for(
                    websocket.send_json(payload),
                    timeout=self.send_timeout_seconds,
                )
                return True
            except Exception as e:
                logger.error(f"Send failed: {session_id}, {e}")
                # Fall through to queue
        
        # Queue for reconnect
        await self.session_store.queue_message(session_id, self._to_jsonable(message))
        return False

    def _to_jsonable(self, message: Any) -> Any:
        if hasattr(message, "model_dump"):
            payload = message.model_dump(mode="json")
        else:
            payload = message

        if jsonable_encoder is None:
            return json.loads(json.dumps(payload, default=str))

        return jsonable_encoder(payload)
    
    async def broadcast_partial(
        self,
        session_id: str,
        trace_id: str,
        content: str,
        index: int,
    ):
        """Stream response partial to client."""
        msg = ModelPartial(
            session_id=session_id,
            trace_id=trace_id,
            content=content,
            index=index,
        )
        await self.send_to_client(session_id, msg)
    
    async def broadcast_final(
        self,
        session_id: str,
        trace_id: str,
        content: str,
        actions: Optional[list] = None,
    ):
        """Send final response to client."""
        msg = ModelFinal(
            session_id=session_id,
            trace_id=trace_id,
            content=content,
            actions=actions,
        )
        await self.send_to_client(session_id, msg)
    
    async def broadcast_action_invoke(
        self,
        session_id: str,
        trace_id: str,
        action_id: str,
        action_type: str,
        parameters: Dict[str, Any],
        requires_confirmation: bool = False,
    ):
        """Send action invocation to client (for confirmation)."""
        msg = ModelInvokeAction(
            session_id=session_id,
            trace_id=trace_id,
            action_id=action_id,
            action_type=action_type,
            parameters=parameters,
            requires_confirmation=requires_confirmation,
        )
        await self.send_to_client(session_id, msg)
    
    async def broadcast_action_result(
        self,
        session_id: str,
        trace_id: str,
        action_id: str,
        action_type: str,
        status: str,
        result: Any,
        error: Optional[str] = None,
    ):
        """Send action execution result to client."""
        msg = ActionResult(
            session_id=session_id,
            trace_id=trace_id,
            action_id=action_id,
            action_type=action_type,
            status=status,
            result=result,
            error=error,
        )
        await self.send_to_client(session_id, msg)

    async def broadcast_action_deferred(
        self,
        session_id: str,
        action_id: str,
        action_type: str,
        status: str,
        reason: Optional[str] = None,
        expires_at: Optional[str] = None,
    ):
        """Notify client that action confirmation timed out or moved to tray."""
        from .types import ActionDeferred

        msg = ActionDeferred(
            session_id=session_id,
            action_id=action_id,
            action_type=action_type,
            status=status,
            reason=reason,
            expires_at=expires_at,
        )
        await self.send_to_client(session_id, msg)

    async def broadcast_saga_update(
        self,
        session_id: str,
        saga_id: str,
        state: str,
        saga_type: Optional[str] = None,
        steps: Optional[list] = None,
        result: Any = None,
        updated_at: Optional[str] = None,
    ):
        """Send saga update to client."""
        msg = SagaUpdate(
            session_id=session_id,
            saga_id=saga_id,
            saga_type=saga_type,
            state=state,
            steps=steps,
            result=result,
            updated_at=updated_at,
        )
        await self.send_to_client(session_id, msg)
    
    async def disconnect_session(
        self,
        session_id: str,
        reason: str = "disconnected",
    ):
        """Gracefully close session and clean up."""
        async with self.connection_lock:
            websocket = self.active_connections.pop(session_id, None)
        
        if websocket:
            try:
                await websocket.close(code=1000, reason=reason)
            except Exception:
                logger.debug("WebSocket already closed during cleanup", exc_info=True)
        
        # Invalidate session in Redis
        await self.session_store.invalidate_session(session_id)


def create_gateway(
    app: FastAPI,
    redis_client: redis.Redis,
    action_router_queue: asyncio.Queue,
    agent_handler: "AgentWebSocketHandler | None" = None,
) -> WebSocketGateway:
    """Factory function to create and register gateway."""
    return WebSocketGateway(
        app=app,
        redis_client=redis_client,
        action_router_queue=action_router_queue,
        agent_handler=agent_handler,
    )
