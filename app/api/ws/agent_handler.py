"""Agent session WebSocket binding and streaming (P0-33).

Binds a WebSocket connection to an agent session so that events
emitted by ``AgentSession.process_message()`` are streamed in
real-time to the connected client.

Architecture:
  Client ─WS─► Gateway ──agent.*──► AgentWebSocketHandler
                                        │
                                        ├─ binds WS ↔ agent_session_id
                                        ├─ subscribes Redis channel
                                        │   ``agent_session:{id}:events``
                                        └─ forwards events → WS client

The ``RedisAgentEventEmitter`` is injected into ``AgentSession``
when processing messages for a bound session — it ``PUBLISH``es each
event to the Redis channel.  The handler's subscription task picks
these up and forwards them to the WebSocket client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional, Set

from app.core.agent.session import AgentEventEmitter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis-backed event emitter (injected into AgentSession)
# ---------------------------------------------------------------------------


class RedisAgentEventEmitter(AgentEventEmitter):
    """Publishes agent events to a Redis pub/sub channel.

    Channel name: ``agent_session:{session_id}:events``
    """

    def __init__(self, redis_client: Any, agent_session_id: str) -> None:
        self._redis = redis_client
        self._agent_session_id = agent_session_id
        self._channel = f"agent_session:{agent_session_id}:events"

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        payload = {
            "type": event_type,
            "message_id": str(uuid.uuid4()),
            **data,
        }
        try:
            serialized = json.dumps(payload, default=str)
            await self._redis.publish(self._channel, serialized)
        except Exception:
            logger.warning(
                "Failed to publish agent event %s to %s",
                event_type,
                self._channel,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Agent stream binding tracker
# ---------------------------------------------------------------------------


class AgentStreamBinding:
    """Tracks which WS sessions are bound to which agent sessions."""

    def __init__(self) -> None:
        # ws_session_id → set of agent_session_ids
        self._ws_to_agents: Dict[str, Set[str]] = {}
        # agent_session_id → ws_session_id
        self._agent_to_ws: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def bind(self, ws_session_id: str, agent_session_id: str) -> None:
        async with self._lock:
            self._ws_to_agents.setdefault(ws_session_id, set()).add(agent_session_id)
            self._agent_to_ws[agent_session_id] = ws_session_id

    async def unbind(self, ws_session_id: str, agent_session_id: str) -> None:
        async with self._lock:
            agents = self._ws_to_agents.get(ws_session_id)
            if agents:
                agents.discard(agent_session_id)
                if not agents:
                    del self._ws_to_agents[ws_session_id]
            self._agent_to_ws.pop(agent_session_id, None)

    async def unbind_ws(self, ws_session_id: str) -> Set[str]:
        """Remove all bindings for a WS session. Returns unbound agent IDs."""
        async with self._lock:
            agents = self._ws_to_agents.pop(ws_session_id, set())
            for aid in agents:
                self._agent_to_ws.pop(aid, None)
            return agents

    async def get_ws_for_agent(self, agent_session_id: str) -> Optional[str]:
        async with self._lock:
            return self._agent_to_ws.get(agent_session_id)

    async def get_agents_for_ws(self, ws_session_id: str) -> Set[str]:
        async with self._lock:
            return set(self._ws_to_agents.get(ws_session_id, set()))


# ---------------------------------------------------------------------------
# Agent WebSocket Handler
# ---------------------------------------------------------------------------


class AgentWebSocketHandler:
    """Handles agent stream binding and event forwarding for WebSocket connections.

    Integrates with the existing ``WebSocketGateway`` — the gateway delegates
    ``agent.*`` typed messages to this handler.

    Usage::

        handler = AgentWebSocketHandler(redis_client)
        # In gateway._client_receive_handler, when type starts with "agent.":
        await handler.handle_agent_message(ws_session_id, data, send_fn)
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        self.bindings = AgentStreamBinding()
        # agent_session_id → subscriber asyncio.Task
        self._subscriber_tasks: Dict[str, asyncio.Task] = {}
        self._send_fns: Dict[str, Any] = {}  # ws_session_id → send callable

    async def handle_agent_message(
        self,
        ws_session_id: str,
        data: Dict[str, Any],
        send_fn: Any,
    ) -> None:
        """Route an agent-prefixed WS message.

        *send_fn* is an ``async def send_fn(payload: dict) -> None`` that
        writes to the client WebSocket.
        """
        msg_type = data.get("type", "")

        if msg_type == "agent.stream_start":
            await self._handle_stream_start(ws_session_id, data, send_fn)
        else:
            logger.debug("Unhandled agent message type: %s", msg_type)

    async def _handle_stream_start(
        self,
        ws_session_id: str,
        data: Dict[str, Any],
        send_fn: Any,
    ) -> None:
        """Bind WS to agent session and start streaming events."""
        agent_session_id = data.get("agent_session_id")
        if not agent_session_id:
            await send_fn({
                "type": "agent.error",
                "agent_session_id": "",
                "error": "Missing agent_session_id in stream_start",
                "recoverable": False,
            })
            return

        # Store send function for this WS session
        self._send_fns[ws_session_id] = send_fn

        # Bind
        await self.bindings.bind(ws_session_id, agent_session_id)

        # Start Redis subscriber if not already running
        if agent_session_id not in self._subscriber_tasks:
            task = asyncio.create_task(
                self._subscribe_and_forward(agent_session_id, ws_session_id, send_fn),
            )
            self._subscriber_tasks[agent_session_id] = task

        logger.info(
            "Agent stream bound: ws=%s agent=%s",
            ws_session_id,
            agent_session_id,
        )

    async def _subscribe_and_forward(
        self,
        agent_session_id: str,
        ws_session_id: str,
        send_fn: Any,
    ) -> None:
        """Subscribe to Redis channel and forward events to WS client."""
        channel_name = f"agent_session:{agent_session_id}:events"
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(channel_name)
            logger.debug("Subscribed to %s", channel_name)

            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if msg is None:
                    # Check if binding still active
                    ws_id = await self.bindings.get_ws_for_agent(agent_session_id)
                    if ws_id is None:
                        break
                    await asyncio.sleep(0.05)
                    continue

                if msg["type"] == "message":
                    try:
                        payload = json.loads(msg["data"])
                        await send_fn(payload)
                    except Exception:
                        logger.warning(
                            "Failed to forward agent event to WS",
                            exc_info=True,
                        )

                # If this was a final or error, we can stop
                if msg and msg["type"] == "message":
                    try:
                        p = json.loads(msg["data"])
                        if p.get("type") in ("agent.final", "agent.error"):
                            break
                    except Exception:
                        pass

        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Agent subscriber error for %s", agent_session_id, exc_info=True)
        finally:
            try:
                await pubsub.unsubscribe(channel_name)
                await pubsub.close()
            except Exception:
                pass
            self._subscriber_tasks.pop(agent_session_id, None)

    def create_emitter(self, agent_session_id: str) -> RedisAgentEventEmitter:
        """Create an event emitter for an agent session.

        Inject this into ``AgentSession(event_emitter=...)`` so that
        ``process_message`` publishes events to the Redis channel.
        """
        return RedisAgentEventEmitter(self._redis, agent_session_id)

    async def on_ws_disconnect(self, ws_session_id: str) -> None:
        """Clean up bindings and subscriber tasks when WS disconnects."""
        agent_ids = await self.bindings.unbind_ws(ws_session_id)
        self._send_fns.pop(ws_session_id, None)
        for aid in agent_ids:
            task = self._subscriber_tasks.pop(aid, None)
            if task and not task.done():
                task.cancel()
