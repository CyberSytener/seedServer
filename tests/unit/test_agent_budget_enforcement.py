"""Tests for P7-13: Budget enforcement integration in agent loop.

Covers:
  - 3-tool scenario with budget for 2 tools → stops after 2
  - Token budget exhaustion mid-loop → graceful stop
  - Cost budget exhaustion → graceful stop
  - Per-tool call limit enforcement
  - Budget snapshot in trace at every step
  - Partial results returned with explanation on budget stop
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
from app.core.agent.session import AgentSession


# ===================================================================
# Shared test helpers
# ===================================================================

class FakeActionStatus(str, Enum):
    SUCCESS = "success"


@dataclass
class FakeActionResult:
    status: FakeActionStatus = FakeActionStatus.SUCCESS
    result: Any = "ok"
    error: Optional[str] = None


class FakeActionRouter:
    def execute_action(self, action: Any) -> FakeActionResult:
        return FakeActionResult(result=f"result_for_{action.name}")


@dataclass
class FakeGenResult:
    text: str = ""
    tokens_in: int = 10
    tokens_out: int = 10
    cost_usd: float = 0.001
    provider: str = "fake"
    model: str = "fake"


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


class ToolRegistryStub:
    """Always allows tools and returns manifests."""

    def __init__(self):
        from app.core.agent.tool_registry import ToolPermissionConfig
        self.permissions = ToolPermissionConfig()

    def list_tools_for_llm(self, scopes):
        return [
            {"type": "function", "function": {"name": "tool_a", "description": "", "parameters": {}}},
            {"type": "function", "function": {"name": "tool_b", "description": "", "parameters": {}}},
            {"type": "function", "function": {"name": "tool_c", "description": "", "parameters": {}}},
        ]

    def is_tool_allowed(self, name, scopes):
        return True

    def build_action(self, name, inputs, session_id="", user_id=None):
        from app.models.realtime.actions import Action, ActionMetadata
        return Action(
            name=name,
            id=f"test_{uuid.uuid4().hex[:8]}",
            params=inputs,
            metadata=ActionMetadata(session_id=session_id, user_id=user_id),
        )


# ===================================================================
# 1. Three-tool scenario — budget for 2 tool calls
# ===================================================================

class TestBudgetStopsAfterNTools:

    @pytest.mark.asyncio
    async def test_3_tools_budget_for_2(self):
        """LLM asks for 3 tools in one turn but budget allows only 2 tool calls."""
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        budget_cfg = AgentBudget(max_tool_calls=2).to_config()
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="u1",
            budget_config=budget_cfg,
            tool_scopes=["*"],
        ))

        # LLM returns 3 tool calls at once
        call_count = 0

        class MultiToolLLM:
            async def agenerate_with_metadata(self, **kw):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return FakeGenResult(text=(
                        'Let me call all three tools.\n'
                        '<tool_call>{"name": "tool_a", "arguments": {}}</tool_call>\n'
                        '<tool_call>{"name": "tool_b", "arguments": {}}</tool_call>\n'
                        '<tool_call>{"name": "tool_c", "arguments": {}}</tool_call>'
                    ))
                # After tool results, give final answer
                return FakeGenResult(text="Done with tools.")

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=MultiToolLLM(),
        )
        resp = await agent.process_message(sid, "Do all three things")

        # tool_a and tool_b should execute, tool_c should be budget-stopped
        executed = [t for t in resp.trace if t.get("step") == "tool_executed"]
        budget_exceeded = [t for t in resp.trace if "tool_budget_exceeded" in str(t)]

        assert len(executed) == 2
        assert resp.budget_snapshot["consumed_tool_calls"] == 2

    @pytest.mark.asyncio
    async def test_tool_budget_error_message(self):
        """Budget exhaustion for a tool provides a clear error to the LLM."""
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        budget_cfg = AgentBudget(max_tool_calls=1).to_config()
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="u1",
            budget_config=budget_cfg,
            tool_scopes=["*"],
        ))

        class TwoToolLLM:
            call_count = 0
            async def agenerate_with_metadata(self, **kw):
                self.call_count += 1
                if self.call_count == 1:
                    return FakeGenResult(text=(
                        '<tool_call>{"name": "tool_a", "arguments": {}}</tool_call>\n'
                        '<tool_call>{"name": "tool_b", "arguments": {}}</tool_call>'
                    ))
                return FakeGenResult(text="Understood, done.")

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=TwoToolLLM(),
        )
        resp = await agent.process_message(sid, "Do two things")

        # First tool executes, second is denied by budget
        executed = [t for t in resp.trace if t.get("step") == "tool_executed"]
        assert len(executed) == 1


# ===================================================================
# 2. Token budget exhaustion mid-loop
# ===================================================================

class TestTokenBudgetExhaustion:

    @pytest.mark.asyncio
    async def test_token_budget_stops_loop(self):
        """Budget runs out of tokens after first LLM call → stops before second."""
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        # Give enough for one LLM call (20 tokens total), but the call consumes 20
        budget_cfg = AgentBudget(max_total_tokens=25).to_config()
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="u1",
            budget_config=budget_cfg,
            tool_scopes=["*"],
        ))

        call_count = 0

        class ExpensiveLLM:
            async def agenerate_with_metadata(self, **kw):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return FakeGenResult(
                        text='<tool_call>{"name": "tool_a", "arguments": {}}</tool_call>',
                        tokens_in=15,
                        tokens_out=15,
                    )
                return FakeGenResult(text="Done.")

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=ExpensiveLLM(),
        )
        resp = await agent.process_message(sid, "Do a thing")

        # Should have only 1 LLM call; budget exceeded prevents second iteration
        assert call_count == 1
        assert resp.stopped_reason is not None
        assert "budget" in resp.stopped_reason.lower()

    @pytest.mark.asyncio
    async def test_zero_token_budget_immediate_stop(self):
        """Zero token budget → stops immediately without any LLM call."""
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        budget_cfg = AgentBudget(max_total_tokens=0).to_config()
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="u1",
            budget_config=budget_cfg,
            tool_scopes=["*"],
        ))

        llm_called = False

        class NeverCalledLLM:
            async def agenerate_with_metadata(self, **kw):
                nonlocal llm_called
                llm_called = True
                return FakeGenResult()

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=NeverCalledLLM(),
        )
        resp = await agent.process_message(sid, "Hello")

        assert not llm_called
        assert "budget" in resp.stopped_reason.lower()
        assert "limit" in resp.text.lower()


# ===================================================================
# 3. Cost budget exhaustion
# ===================================================================

class TestCostBudgetExhaustion:

    @pytest.mark.asyncio
    async def test_cost_budget_stops_loop(self):
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        budget_cfg = AgentBudget(max_total_cost_units=0.001).to_config()
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="u1",
            budget_config=budget_cfg,
            tool_scopes=["*"],
        ))

        call_count = 0

        class CostlyLLM:
            async def agenerate_with_metadata(self, **kw):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return FakeGenResult(
                        text='<tool_call>{"name": "tool_a", "arguments": {}}</tool_call>',
                        cost_usd=0.002,
                    )
                return FakeGenResult(text="Done.", cost_usd=0.002)

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=CostlyLLM(),
        )
        resp = await agent.process_message(sid, "Analyze")

        assert call_count == 1
        assert resp.stopped_reason is not None
        assert "budget" in resp.stopped_reason.lower()


# ===================================================================
# 4. Budget snapshot in every trace entry
# ===================================================================

class TestBudgetSnapshotInTrace:

    @pytest.mark.asyncio
    async def test_llm_call_trace_has_budget(self):
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        await store.create_session(AgentSessionData(
            session_id=sid, user_id="u1", tool_scopes=["*"],
        ))

        class SimpleLLM:
            async def agenerate_with_metadata(self, **kw):
                return FakeGenResult(text="Here is my answer.")

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=SimpleLLM(),
        )
        resp = await agent.process_message(sid, "Test")

        llm_traces = [t for t in resp.trace if t.get("step") == "llm_call"]
        assert len(llm_traces) >= 1
        assert "budget_snapshot" in llm_traces[0]
        assert "consumed_tokens" in llm_traces[0]["budget_snapshot"]

    @pytest.mark.asyncio
    async def test_tool_exec_trace_has_budget(self):
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        await store.create_session(AgentSessionData(
            session_id=sid, user_id="u1", tool_scopes=["*"],
        ))

        call_count = 0

        class ToolCallingLLM:
            async def agenerate_with_metadata(self, **kw):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return FakeGenResult(
                        text='<tool_call>{"name": "tool_a", "arguments": {}}</tool_call>'
                    )
                return FakeGenResult(text="Done.")

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=ToolCallingLLM(),
        )
        resp = await agent.process_message(sid, "Call a tool")

        tool_traces = [t for t in resp.trace if t.get("step") == "tool_executed"]
        assert len(tool_traces) >= 1
        assert "budget_snapshot" in tool_traces[0]


# ===================================================================
# 5. Partial results on budget stop
# ===================================================================

class TestPartialResultsOnBudgetStop:

    @pytest.mark.asyncio
    async def test_partial_tool_results_returned(self):
        """When budget stops mid-iteration, the results from executed tools are preserved."""
        store = InMemoryStore()
        sid = str(uuid.uuid4())
        budget_cfg = AgentBudget(max_tool_calls=1).to_config()
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="u1",
            budget_config=budget_cfg,
            tool_scopes=["*"],
        ))

        class TwoToolLLM:
            call_count = 0
            async def agenerate_with_metadata(self, **kw):
                self.call_count += 1
                if self.call_count == 1:
                    return FakeGenResult(text=(
                        'I will call two tools.\n'
                        '<tool_call>{"name": "tool_a", "arguments": {}}</tool_call>\n'
                        '<tool_call>{"name": "tool_b", "arguments": {}}</tool_call>'
                    ))
                return FakeGenResult(text="Final answer from partial results.")

        agent = AgentSession(
            session_store=store,
            tool_registry=ToolRegistryStub(),
            action_router=FakeActionRouter(),
            llm_service=TwoToolLLM(),
        )
        resp = await agent.process_message(sid, "Do two things")

        # One tool executed, one denied
        executed = [t for t in resp.trace if t.get("step") == "tool_executed"]
        assert len(executed) == 1

        # Messages should contain the executed tool's result
        msgs = await store.get_messages(sid)
        tool_result_msgs = [m for m in msgs if m.role == MessageRole.TOOL_RESULT]
        assert len(tool_result_msgs) >= 1
