"""Tests for agent WS binding and streaming (P0-33)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Set
from unittest import mock

import pytest

from app.core.agent.session import AgentEventEmitter


# ---------------------------------------------------------------------------
# Fake Redis for testing (pub/sub + publish)
# ---------------------------------------------------------------------------


class _FakePubSubMessage:
    """Mimics a Redis pub/sub message dict."""

    def __init__(self, channel: str, data: str, msg_type: str = "message"):
        self.channel = channel
        self.data = data
        self.msg_type = msg_type


class FakePubSub:
    """Minimal async pub/sub mock."""

    def __init__(self) -> None:
        self.subscribed_channels: List[str] = []
        self._messages: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed_channels.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        if channel in self.subscribed_channels:
            self.subscribed_channels.remove(channel)

    async def close(self) -> None:
        self.closed = True

    async def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        try:
            return self._messages.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def inject_message(self, data: str, channel: str = "") -> None:
        self._messages.put_nowait({"type": "message", "data": data, "channel": channel})


class FakeRedis:
    """Minimal async Redis mock with pub/sub."""

    def __init__(self) -> None:
        self.published: List[tuple] = []  # [(channel, data), ...]
        self._pubsub = FakePubSub()

    async def publish(self, channel: str, data: str) -> int:
        self.published.append((channel, data))
        # Also inject into pubsub so subscribers see it
        self._pubsub.inject_message(data, channel)
        return 1

    def pubsub(self) -> FakePubSub:
        return self._pubsub


# ---------------------------------------------------------------------------
# AgentEventEmitter tests
# ---------------------------------------------------------------------------


class TestAgentEventEmitter:
    """Base emitter is a no-op (doesn't raise)."""

    @pytest.mark.asyncio
    async def test_emit_noop(self):
        emitter = AgentEventEmitter()
        await emitter.emit("agent.partial", {"content": "hello"})

    @pytest.mark.asyncio
    async def test_emit_partial(self):
        emitter = AgentEventEmitter()
        await emitter.emit_partial("s1", "chunk", 0)

    @pytest.mark.asyncio
    async def test_emit_tool_call_start(self):
        emitter = AgentEventEmitter()
        await emitter.emit_tool_call_start("s1", "read_file", {"path": "x.py"})

    @pytest.mark.asyncio
    async def test_emit_tool_call_result(self):
        emitter = AgentEventEmitter()
        await emitter.emit_tool_call_result("s1", "read_file", "200 lines", 42.0)

    @pytest.mark.asyncio
    async def test_emit_budget_update(self):
        emitter = AgentEventEmitter()
        await emitter.emit_budget_update("s1", {"tokens_used": 100})

    @pytest.mark.asyncio
    async def test_emit_confirmation_request(self):
        emitter = AgentEventEmitter()
        await emitter.emit_confirmation_request("s1", "c1", "edit", {"file": "x.py"})

    @pytest.mark.asyncio
    async def test_emit_final(self):
        emitter = AgentEventEmitter()
        await emitter.emit_final("s1", "Done", [], [], {}, None)

    @pytest.mark.asyncio
    async def test_emit_error(self):
        emitter = AgentEventEmitter()
        await emitter.emit_error("s1", "boom", True)


# ---------------------------------------------------------------------------
# RedisAgentEventEmitter tests
# ---------------------------------------------------------------------------


class TestRedisAgentEventEmitter:
    @pytest.mark.asyncio
    async def test_publishes_to_correct_channel(self):
        from app.api.ws.agent_handler import RedisAgentEventEmitter

        redis = FakeRedis()
        emitter = RedisAgentEventEmitter(redis, "agt_123")
        await emitter.emit("agent.partial", {"content": "hi", "agent_session_id": "agt_123"})

        assert len(redis.published) == 1
        channel, data = redis.published[0]
        assert channel == "agent_session:agt_123:events"
        payload = json.loads(data)
        assert payload["type"] == "agent.partial"
        assert payload["content"] == "hi"
        assert "message_id" in payload

    @pytest.mark.asyncio
    async def test_emit_partial_helper(self):
        from app.api.ws.agent_handler import RedisAgentEventEmitter

        redis = FakeRedis()
        emitter = RedisAgentEventEmitter(redis, "agt_456")
        await emitter.emit_partial("agt_456", "chunk1", 0)

        assert len(redis.published) == 1
        payload = json.loads(redis.published[0][1])
        assert payload["type"] == "agent.partial"
        assert payload["content"] == "chunk1"
        assert payload["index"] == 0

    @pytest.mark.asyncio
    async def test_emit_final_helper(self):
        from app.api.ws.agent_handler import RedisAgentEventEmitter

        redis = FakeRedis()
        emitter = RedisAgentEventEmitter(redis, "agt_789")
        await emitter.emit_final("agt_789", "All done", [{"a": 1}], [], {"tokens": 50}, "completed")

        payload = json.loads(redis.published[0][1])
        assert payload["type"] == "agent.final"
        assert payload["text"] == "All done"
        assert payload["artifacts"] == [{"a": 1}]
        assert payload["stopped_reason"] == "completed"

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_raise(self):
        from app.api.ws.agent_handler import RedisAgentEventEmitter

        broken_redis = mock.AsyncMock()
        broken_redis.publish.side_effect = ConnectionError("lost")
        emitter = RedisAgentEventEmitter(broken_redis, "agt_err")
        # Should not raise
        await emitter.emit("agent.error", {"error": "x", "agent_session_id": "agt_err"})


# ---------------------------------------------------------------------------
# AgentStreamBinding tests
# ---------------------------------------------------------------------------


class TestAgentStreamBinding:
    @pytest.mark.asyncio
    async def test_bind_and_lookup(self):
        from app.api.ws.agent_handler import AgentStreamBinding

        b = AgentStreamBinding()
        await b.bind("ws1", "agt1")

        assert await b.get_ws_for_agent("agt1") == "ws1"
        assert await b.get_agents_for_ws("ws1") == {"agt1"}

    @pytest.mark.asyncio
    async def test_bind_multiple_agents_to_one_ws(self):
        from app.api.ws.agent_handler import AgentStreamBinding

        b = AgentStreamBinding()
        await b.bind("ws1", "agt1")
        await b.bind("ws1", "agt2")

        assert await b.get_agents_for_ws("ws1") == {"agt1", "agt2"}

    @pytest.mark.asyncio
    async def test_unbind_single(self):
        from app.api.ws.agent_handler import AgentStreamBinding

        b = AgentStreamBinding()
        await b.bind("ws1", "agt1")
        await b.bind("ws1", "agt2")
        await b.unbind("ws1", "agt1")

        assert await b.get_agents_for_ws("ws1") == {"agt2"}
        assert await b.get_ws_for_agent("agt1") is None

    @pytest.mark.asyncio
    async def test_unbind_ws(self):
        from app.api.ws.agent_handler import AgentStreamBinding

        b = AgentStreamBinding()
        await b.bind("ws1", "agt1")
        await b.bind("ws1", "agt2")
        removed = await b.unbind_ws("ws1")

        assert removed == {"agt1", "agt2"}
        assert await b.get_agents_for_ws("ws1") == set()
        assert await b.get_ws_for_agent("agt1") is None

    @pytest.mark.asyncio
    async def test_lookup_nonexistent(self):
        from app.api.ws.agent_handler import AgentStreamBinding

        b = AgentStreamBinding()
        assert await b.get_ws_for_agent("nope") is None
        assert await b.get_agents_for_ws("nope") == set()


# ---------------------------------------------------------------------------
# AgentWebSocketHandler tests
# ---------------------------------------------------------------------------


class TestAgentWebSocketHandler:
    @pytest.mark.asyncio
    async def test_handle_stream_start_binds(self):
        from app.api.ws.agent_handler import AgentWebSocketHandler

        redis = FakeRedis()
        handler = AgentWebSocketHandler(redis)
        sent: List[dict] = []

        async def send_fn(payload: dict) -> None:
            sent.append(payload)

        await handler.handle_agent_message(
            "ws_session_1",
            {"type": "agent.stream_start", "agent_session_id": "agt_100"},
            send_fn,
        )

        # Should be bound
        agents = await handler.bindings.get_agents_for_ws("ws_session_1")
        assert "agt_100" in agents

        # Subscriber task should be running
        assert "agt_100" in handler._subscriber_tasks

        # Clean up
        await handler.on_ws_disconnect("ws_session_1")

    @pytest.mark.asyncio
    async def test_stream_start_missing_session_id_sends_error(self):
        from app.api.ws.agent_handler import AgentWebSocketHandler

        redis = FakeRedis()
        handler = AgentWebSocketHandler(redis)
        sent: List[dict] = []

        async def send_fn(payload: dict) -> None:
            sent.append(payload)

        await handler.handle_agent_message(
            "ws_1",
            {"type": "agent.stream_start"},
            send_fn,
        )

        assert len(sent) == 1
        assert sent[0]["type"] == "agent.error"
        assert "Missing agent_session_id" in sent[0]["error"]

    @pytest.mark.asyncio
    async def test_create_emitter(self):
        from app.api.ws.agent_handler import AgentWebSocketHandler, RedisAgentEventEmitter

        redis = FakeRedis()
        handler = AgentWebSocketHandler(redis)
        emitter = handler.create_emitter("agt_200")

        assert isinstance(emitter, RedisAgentEventEmitter)
        assert emitter._agent_session_id == "agt_200"

    @pytest.mark.asyncio
    async def test_on_ws_disconnect_cleans_up(self):
        from app.api.ws.agent_handler import AgentWebSocketHandler

        redis = FakeRedis()
        handler = AgentWebSocketHandler(redis)
        sent: List[dict] = []

        async def send_fn(payload: dict) -> None:
            sent.append(payload)

        await handler.handle_agent_message(
            "ws_2",
            {"type": "agent.stream_start", "agent_session_id": "agt_300"},
            send_fn,
        )

        # Disconnect
        await handler.on_ws_disconnect("ws_2")

        # Bindings cleared
        assert await handler.bindings.get_agents_for_ws("ws_2") == set()
        # Give tasks a moment to cancel
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_unhandled_agent_type_logged(self):
        from app.api.ws.agent_handler import AgentWebSocketHandler

        redis = FakeRedis()
        handler = AgentWebSocketHandler(redis)
        sent: List[dict] = []

        async def send_fn(payload: dict) -> None:
            sent.append(payload)

        # Should not raise for unknown agent.* types
        await handler.handle_agent_message(
            "ws_3",
            {"type": "agent.unknown_type"},
            send_fn,
        )
        assert len(sent) == 0  # No error sent, just logged


# ---------------------------------------------------------------------------
# Gateway integration — agent message delegation
# ---------------------------------------------------------------------------


class TestGatewayAgentDelegation:
    """Test that the gateway delegates agent.* messages."""

    def test_gateway_accepts_agent_handler(self):
        """Gateway __init__ accepts agent_handler kwarg."""
        from app.api.ws.gateway import WebSocketGateway

        # We can't fully instantiate (needs FastAPI), but check the param exists
        import inspect
        sig = inspect.signature(WebSocketGateway.__init__)
        assert "agent_handler" in sig.parameters

    def test_create_gateway_accepts_agent_handler(self):
        """Factory function accepts agent_handler kwarg."""
        from app.api.ws.gateway import create_gateway
        import inspect
        sig = inspect.signature(create_gateway)
        assert "agent_handler" in sig.parameters


# ---------------------------------------------------------------------------
# Event emitter integration with AgentSession
# ---------------------------------------------------------------------------


class TestAgentSessionEventEmitter:
    """Test that AgentSession accepts and uses an event_emitter."""

    def test_session_accepts_event_emitter(self):
        """AgentSession.__init__ accepts event_emitter kwarg."""
        from app.core.agent.session import AgentSession
        import inspect
        sig = inspect.signature(AgentSession.__init__)
        assert "event_emitter" in sig.parameters

    def test_session_default_emitter(self):
        """AgentSession creates a default no-op emitter if none provided."""
        from app.core.agent.session import AgentSession, AgentEventEmitter

        session = AgentSession(
            session_store=mock.MagicMock(),
            tool_registry=mock.MagicMock(),
            action_router=mock.MagicMock(),
            llm_service=mock.MagicMock(),
        )
        assert isinstance(session.event_emitter, AgentEventEmitter)

    def test_session_custom_emitter(self):
        """AgentSession stores provided event_emitter."""
        from app.core.agent.session import AgentSession

        custom = mock.MagicMock(spec=AgentEventEmitter)
        session = AgentSession(
            session_store=mock.MagicMock(),
            tool_registry=mock.MagicMock(),
            action_router=mock.MagicMock(),
            llm_service=mock.MagicMock(),
            event_emitter=custom,
        )
        assert session.event_emitter is custom


# ---------------------------------------------------------------------------
# End-to-end: emitter → Redis → handler forwarding
# ---------------------------------------------------------------------------


class TestEndToEndStreaming:
    @pytest.mark.asyncio
    async def test_emitter_to_handler_round_trip(self):
        """Event emitted → published to Redis → forwarded by handler."""
        from app.api.ws.agent_handler import AgentWebSocketHandler

        redis = FakeRedis()
        handler = AgentWebSocketHandler(redis)
        received: List[dict] = []

        async def send_fn(payload: dict) -> None:
            received.append(payload)

        # Bind WS to agent session
        await handler.handle_agent_message(
            "ws_e2e",
            {"type": "agent.stream_start", "agent_session_id": "agt_e2e"},
            send_fn,
        )

        # Create emitter and emit a partial
        emitter = handler.create_emitter("agt_e2e")
        await emitter.emit_partial("agt_e2e", "Hello ", 0)

        # Give the subscriber task time to pick up the message
        await asyncio.sleep(0.2)

        # Emit final to stop subscriber
        await emitter.emit_final("agt_e2e", "Hello world", [], [], {}, None)
        await asyncio.sleep(0.2)

        # Should have received at least the partial and final
        types_received = [r.get("type") for r in received]
        assert "agent.partial" in types_received
        assert "agent.final" in types_received

        # Clean up
        await handler.on_ws_disconnect("ws_e2e")
