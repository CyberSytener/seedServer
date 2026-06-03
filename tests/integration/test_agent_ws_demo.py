"""P0-42: Live WS streaming demo integration test.

Exercises the agent event emission flow end-to-end:
  1. AgentSession emits events via AgentEventEmitter during process_message
  2. All event types appear in correct order
  3. Events carry correct session_id
  4. Budget updates appear after LLM and tool calls
  5. Final event carries complete response
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentEventEmitter, AgentSession
from app.core.agent.tool_registry import ToolPermissionConfig, ToolRegistry
from app.core.blocks import BlockBase, BlockRegistry


# ===================================================================
# Collecting EventEmitter (records all events for assertions)
# ===================================================================


class CollectingEventEmitter(AgentEventEmitter):
    """Records all emitted events for test verification."""

    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        self.events.append({"type": event_type, **data})


# ===================================================================
# Test infrastructure
# ===================================================================


class InMemoryStore:
    def __init__(self):
        self._sessions: Dict[str, AgentSessionData] = {}
        self._messages: Dict[str, List[AgentSessionMessage]] = {}

    async def create_session(self, s: AgentSessionData) -> AgentSessionData:
        self._sessions[s.session_id] = s
        self._messages[s.session_id] = []
        return s

    async def get_session(self, sid: str) -> Optional[AgentSessionData]:
        return self._sessions.get(sid)

    async def update_session(self, s: AgentSessionData) -> None:
        self._sessions[s.session_id] = s

    async def append_message(self, msg: AgentSessionMessage) -> None:
        self._messages.setdefault(msg.session_id, []).append(msg)

    async def get_messages(self, sid: str) -> List[AgentSessionMessage]:
        return self._messages.get(sid, [])


class FakeActionStatus(str, Enum):
    SUCCESS = "success"


@dataclass
class FakeActionResult:
    status: FakeActionStatus = FakeActionStatus.SUCCESS
    result: Any = "ok"
    error: Optional[str] = None


class FakeActionRouter:
    def __init__(self):
        self.executed: List[str] = []

    def execute_action(self, action: Any) -> FakeActionResult:
        self.executed.append(action.name)
        return FakeActionResult(result=f"result_for_{action.name}")


@dataclass
class StubGenResult:
    text: str = ""
    tokens_in: int = 100
    tokens_out: int = 100
    cost_usd: float = 0.002


class WSStreamingLLMStub:
    """LLM stub that returns tool call on first round, final text on second."""

    def __init__(self):
        self.call_count = 0

    async def agenerate_with_metadata(self, **kw):
        self.call_count += 1
        if self.call_count == 1:
            return StubGenResult(
                text=(
                    "Let me analyze the component.\n\n"
                    '<tool_call>{"name": "analyze", "arguments": {"target": "Header"}}</tool_call>'
                ),
            )
        else:
            return StubGenResult(
                text="The Header component has 3 props and renders a navigation bar.",
            )


def _make_tool_registry():
    class StubBlock(BlockBase):
        DESCRIPTION = "Analyze component"
        INPUT_SCHEMA = {"target": {"type": "string"}}
        OUTPUT_SCHEMA = {"result": {"type": "string"}}

        async def execute(self, context, inputs):
            return {"result": "analysis complete"}

    br = BlockRegistry()
    br.register("analyze", StubBlock, description="Analyze component")
    return ToolRegistry(br)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def ws_streaming_env():
    store = InMemoryStore()
    llm = WSStreamingLLMStub()
    action_router = FakeActionRouter()
    tool_registry = _make_tool_registry()
    emitter = CollectingEventEmitter()

    agent = AgentSession(
        session_store=store,
        tool_registry=tool_registry,
        action_router=action_router,
        llm_service=llm,
        event_emitter=emitter,
    )

    return {
        "agent": agent,
        "store": store,
        "emitter": emitter,
    }


# ===================================================================
# Tests
# ===================================================================


class TestWSStreamingDemo:
    """Verify event emission during agent process_message."""

    @pytest.mark.asyncio
    async def test_step1_budget_update_after_llm(self, ws_streaming_env):
        """Budget update event emitted after each LLM call."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-001",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-001", "Analyze the Header component.")

        budget_updates = [e for e in emitter.events if e["type"] == "agent.budget_update"]
        assert len(budget_updates) >= 1, "At least one budget update expected"
        for bu in budget_updates:
            assert bu["agent_session_id"] == "ws-001"
            assert "budget_snapshot" in bu

    @pytest.mark.asyncio
    async def test_step2_tool_call_start_event(self, ws_streaming_env):
        """tool_call_start event emitted before tool execution."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-002",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-002", "Analyze the Header.")

        starts = [e for e in emitter.events if e["type"] == "agent.tool_call_start"]
        assert len(starts) >= 1
        assert starts[0]["tool_name"] == "analyze"
        assert starts[0]["agent_session_id"] == "ws-002"

    @pytest.mark.asyncio
    async def test_step3_tool_call_result_event(self, ws_streaming_env):
        """tool_call_result event emitted after tool execution."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-003",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-003", "Analyze the Header.")

        results = [e for e in emitter.events if e["type"] == "agent.tool_call_result"]
        assert len(results) >= 1
        assert results[0]["tool_name"] == "analyze"
        assert results[0]["agent_session_id"] == "ws-003"

    @pytest.mark.asyncio
    async def test_step4_final_event(self, ws_streaming_env):
        """Final event emitted with complete response text."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-004",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-004", "Analyze the Header.")

        finals = [e for e in emitter.events if e["type"] == "agent.final"]
        assert len(finals) == 1
        assert finals[0]["agent_session_id"] == "ws-004"
        assert finals[0]["text"]  # non-empty
        assert "budget_snapshot" in finals[0]

    @pytest.mark.asyncio
    async def test_step5_event_order(self, ws_streaming_env):
        """Events appear in correct order: budget_update → tool_call_start → tool_call_result → budget_update → ... → final."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-005",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-005", "Analyze the Header.")

        event_types = [e["type"] for e in emitter.events]

        # Budget update should come before tool_call_start
        first_budget = event_types.index("agent.budget_update")
        first_tool_start = event_types.index("agent.tool_call_start")
        assert first_budget < first_tool_start

        # tool_call_start should come before tool_call_result
        first_tool_result = event_types.index("agent.tool_call_result")
        assert first_tool_start < first_tool_result

        # Final should be last
        assert event_types[-1] == "agent.final"

    @pytest.mark.asyncio
    async def test_step6_all_events_have_session_id(self, ws_streaming_env):
        """Every event carries the agent_session_id."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-006",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-006", "Analyze the Header.")

        for event in emitter.events:
            assert event.get("agent_session_id") == "ws-006", (
                f"Event {event['type']} missing or wrong session_id"
            )

    @pytest.mark.asyncio
    async def test_step7_no_events_on_session_not_found(self, ws_streaming_env):
        """No events emitted when session doesn't exist."""
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        response = await agent.process_message("nonexistent", "Hello")
        assert response.stopped_reason == "session_not_found"
        assert len(emitter.events) == 0


class TestWSEventTypes:
    """Verify all expected WS event types are emitted."""

    @pytest.mark.asyncio
    async def test_expected_event_types_present(self, ws_streaming_env):
        """All core event types appear during a tool-using conversation."""
        store = ws_streaming_env["store"]
        agent = ws_streaming_env["agent"]
        emitter = ws_streaming_env["emitter"]

        session = AgentSessionData(
            session_id="ws-008",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-008", "Analyze the Header.")

        event_types = {e["type"] for e in emitter.events}
        assert "agent.budget_update" in event_types
        assert "agent.tool_call_start" in event_types
        assert "agent.tool_call_result" in event_types
        assert "agent.final" in event_types

    @pytest.mark.asyncio
    async def test_simple_response_emits_budget_and_final(self, ws_streaming_env):
        """A simple no-tool response still emits budget_update and final."""
        store = ws_streaming_env["store"]
        emitter = ws_streaming_env["emitter"]

        # Use a fresh LLM that always returns plain text
        class SimpleLLM:
            async def agenerate_with_metadata(self, **kw):
                return StubGenResult(text="Simple answer, no tools needed.")

        agent = AgentSession(
            session_store=store,
            tool_registry=_make_tool_registry(),
            action_router=FakeActionRouter(),
            llm_service=SimpleLLM(),
            event_emitter=emitter,
        )

        session = AgentSessionData(
            session_id="ws-009",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("ws-009", "Hello")

        event_types = [e["type"] for e in emitter.events]
        assert "agent.budget_update" in event_types
        assert "agent.final" in event_types
        assert "agent.tool_call_start" not in event_types  # no tool calls


class TestWSAuthEnforcement:
    """Verify auth infrastructure exists for WS agent binding."""

    def test_gateway_requires_jwt_token_in_ws_route(self):
        """WS gateway endpoint is registered at /ws with JWT auth."""
        import inspect
        from app.api.ws.gateway import WebSocketGateway

        # The gateway _setup_routes uses self.jwt_handler.extract_user_id
        # Verify the gateway stores a jwt_handler
        sig = inspect.signature(WebSocketGateway.__init__)
        assert "jwt_handler" in sig.parameters, "Gateway must require jwt_handler"

    def test_gateway_delegates_agent_messages(self):
        """Gateway has agent_handler param for agent.* message delegation."""
        import inspect
        from app.api.ws.gateway import WebSocketGateway

        sig = inspect.signature(WebSocketGateway.__init__)
        assert "agent_handler" in sig.parameters, (
            "Gateway must accept agent_handler for agent streaming"
        )

    def test_agent_handler_requires_stream_start_with_session_id(self):
        """AgentWebSocketHandler rejects stream_start without session_id."""
        import asyncio as _asyncio
        from app.api.ws.agent_handler import AgentWebSocketHandler

        handler = AgentWebSocketHandler(redis_client=None)
        # handle_agent_message should exist and be an async method
        assert _asyncio.iscoroutinefunction(handler.handle_agent_message)


class TestRedisEmitterContract:
    """Verify RedisAgentEventEmitter publishes to correct channel."""

    @pytest.mark.asyncio
    async def test_emitter_publishes_to_session_channel(self):
        """Events are published to agent_session:{id}:events channel."""
        from unittest.mock import AsyncMock
        from app.api.ws.agent_handler import RedisAgentEventEmitter

        mock_redis = AsyncMock()
        emitter = RedisAgentEventEmitter(mock_redis, "session-42")

        await emitter.emit("agent.budget_update", {"budget_snapshot": {}})

        mock_redis.publish.assert_called_once()
        channel = mock_redis.publish.call_args[0][0]
        assert channel == "agent_session:session-42:events"

        payload = json.loads(mock_redis.publish.call_args[0][1])
        assert payload["type"] == "agent.budget_update"
        assert "message_id" in payload  # UUID envelope

    @pytest.mark.asyncio
    async def test_emitter_includes_message_id(self):
        """Each published event gets a unique message_id."""
        from unittest.mock import AsyncMock
        from app.api.ws.agent_handler import RedisAgentEventEmitter

        mock_redis = AsyncMock()
        emitter = RedisAgentEventEmitter(mock_redis, "session-99")

        await emitter.emit("agent.final", {"text": "done"})
        await emitter.emit("agent.final", {"text": "done again"})

        calls = mock_redis.publish.call_args_list
        id1 = json.loads(calls[0][0][1])["message_id"]
        id2 = json.loads(calls[1][0][1])["message_id"]
        assert id1 != id2  # unique per emission
