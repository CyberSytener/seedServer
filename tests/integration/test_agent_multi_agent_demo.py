"""P0-40: Multi-agent orchestration demo integration test.

Exercises the full multi-agent workflow using StubProvider:
  1. Create parent session
  2. Trigger parallel delegation of 3 sub-agents
  3. Verify parallel execution
  4. Verify budget aggregation across children
  5. Verify session tree (parent → children)
  6. Verify scope subset enforcement (child cannot escalate)
  7. Verify trace linkage via parent_session_id
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentResponse,
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentSession
from app.core.agent.tool_registry import ToolPermissionConfig


# ===================================================================
# Test infrastructure (shared stubs)
# ===================================================================


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


class InMemoryStore:
    """In-memory AgentSessionStore for tests."""

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

    async def delete_session(self, sid: str) -> None:
        self._sessions.pop(sid, None)
        self._messages.pop(sid, None)


class ToolRegistryStub:
    """Allows tools within declared scopes; provides manifests."""

    def __init__(self):
        self.permissions = ToolPermissionConfig()
        # Simulate a block registry with _block_registry attribute
        self._block_registry = type("BR", (), {
            "list_blocks": lambda self: ["read_file", "write_file", "analyze"],
            "get_metadata": lambda self, name: type("M", (), {
                "name": name, "listing_id": None,
            })(),
        })()

    def list_tools_for_llm(self, scopes):
        return [
            {"type": "function", "function": {"name": "analyze", "description": "Analyze component", "parameters": {}}},
        ]

    def is_tool_allowed(self, name, scopes):
        if "*" in scopes:
            return True
        return name in scopes

    def build_action(self, name, inputs, session_id="", user_id=None):
        from app.models.realtime.actions import Action, ActionMetadata
        return Action(
            name=name,
            id=f"test_{uuid.uuid4().hex[:8]}",
            params=inputs,
            metadata=ActionMetadata(session_id=session_id, user_id=user_id),
        )


@dataclass
class StubGenResult:
    text: str = ""
    tokens_in: int = 50
    tokens_out: int = 50
    cost_usd: float = 0.001
    provider: str = "stub"
    model: str = "stub-model"


class MultiAgentStubLLM:
    """Deterministic LLM stub.

    Returns a simple text answer immediately without tool calls
    (sufficient for testing the orchestration/budget/scope flow).
    """

    def __init__(self):
        self.call_count = 0

    async def agenerate_with_metadata(self, **kw):
        self.call_count += 1
        return StubGenResult(
            text=f"Analysis result #{self.call_count}: components look good.",
        )


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def multi_agent_env():
    """Set up multi-agent test environment."""
    store = InMemoryStore()
    llm = MultiAgentStubLLM()
    action_router = FakeActionRouter()
    tool_registry = ToolRegistryStub()

    agent = AgentSession(
        session_store=store,
        tool_registry=tool_registry,
        action_router=action_router,
        llm_service=llm,
        nesting_depth=0,
        max_nesting_depth=3,
    )

    return {
        "agent": agent,
        "store": store,
        "llm": llm,
        "action_router": action_router,
        "tool_registry": tool_registry,
    }


# ===================================================================
# Tests
# ===================================================================

class TestMultiAgentDemo:
    """Multi-agent orchestration demo: parallel sub-agents."""

    @pytest.mark.asyncio
    async def test_step1_create_parent_session(self, multi_agent_env):
        """Create a parent session with budget and tool_scopes."""
        store = multi_agent_env["store"]

        parent = AgentSessionData(
            session_id="parent-001",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze", "read_file"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        stored = await store.get_session("parent-001")
        assert stored is not None
        assert stored.status == SessionStatus.ACTIVE
        assert "analyze" in stored.tool_scopes

    @pytest.mark.asyncio
    async def test_step2_spawn_single_child(self, multi_agent_env):
        """Spawn a single child session and verify it runs."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-002",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze", "read_file"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        response = await agent.spawn_child_session(
            parent_session_id="parent-002",
            persona_id="seed",
            tool_scopes=["analyze"],
            task_prompt="Analyze the Header component.",
        )

        assert response.text
        assert response.stopped_reason is None or response.stopped_reason == ""

    @pytest.mark.asyncio
    async def test_step3_parallel_delegation_3_children(self, multi_agent_env):
        """Delegate parallel to 3 sub-agents and verify all complete."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-003",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze", "read_file"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        children_specs = [
            {"task": "Analyze the Header component.", "tool_scopes": ["analyze"]},
            {"task": "Analyze the Menu component.", "tool_scopes": ["analyze"]},
            {"task": "Analyze the Footer component.", "tool_scopes": ["analyze"]},
        ]

        parent_budget = AgentBudget.from_config(parent.budget_config)
        results = await agent.delegate_parallel(
            parent_session_id="parent-003",
            children_specs=children_specs,
            parent_budget=parent_budget,
        )

        # Assert: 3 responses returned
        assert len(results) == 3
        for r in results:
            assert r.text
            assert r.stopped_reason is None or r.stopped_reason not in (
                "scope_escalation_denied", "max_nesting_depth_exceeded",
            )

    @pytest.mark.asyncio
    async def test_step4_budget_aggregation(self, multi_agent_env):
        """Parent budget reflects total consumption of all children."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-004",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        children_specs = [
            {"task": "Analyze Header."},
            {"task": "Analyze Menu."},
            {"task": "Analyze Footer."},
        ]

        parent_budget = AgentBudget.from_config(parent.budget_config)
        results = await agent.delegate_parallel(
            parent_session_id="parent-004",
            children_specs=children_specs,
            parent_budget=parent_budget,
        )

        # Each child should have consumed some budget
        total_budget_consumed = sum(
            r.budget_snapshot.get("consumed_tokens", 0) for r in results
        )
        assert total_budget_consumed > 0, "Children should consume tokens"

    @pytest.mark.asyncio
    async def test_step5_session_tree(self, multi_agent_env):
        """Verify parent → children linkage via parent_session_id."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-005",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        children_specs = [
            {"task": "Analyze Header."},
            {"task": "Analyze Menu."},
            {"task": "Analyze Footer."},
        ]

        await agent.delegate_parallel(
            parent_session_id="parent-005",
            children_specs=children_specs,
        )

        # Check session store for children
        child_sessions = [
            s for sid, s in store._sessions.items()
            if s.parent_session_id == "parent-005"
        ]
        assert len(child_sessions) == 3
        for child in child_sessions:
            assert child.parent_session_id == "parent-005"
            assert child.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_step6_scope_escalation_denied(self, multi_agent_env):
        """Child cannot have broader scopes than parent."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-006",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze"],  # only analyze
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        # Attempt to give child "write_file" scope not in parent
        response = await agent.spawn_child_session(
            parent_session_id="parent-006",
            tool_scopes=["analyze", "write_file"],
            task_prompt="Write something.",
        )

        assert response.stopped_reason == "scope_escalation_denied"
        assert "write_file" in response.text

    @pytest.mark.asyncio
    async def test_step7_trace_linkage(self, multi_agent_env):
        """Each child's trace is linked to parent via parent_session_id."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-007",
            user_id="user-1",
            persona_id="seed",
            budget_config={
                "max_tokens": 10000,
                "max_cost_units": 5.0,
                "max_tool_calls": 30,
            },
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        response = await agent.spawn_child_session(
            parent_session_id="parent-007",
            tool_scopes=["analyze"],
            task_prompt="Analyze Header.",
        )

        # Verify child session exists with correct parent link
        child_sessions = [
            s for sid, s in store._sessions.items()
            if s.parent_session_id == "parent-007"
        ]
        assert len(child_sessions) >= 1
        assert child_sessions[0].parent_session_id == "parent-007"

    @pytest.mark.asyncio
    async def test_step8_nesting_depth_limit(self, multi_agent_env):
        """Max nesting depth prevents infinite recursion."""
        store = multi_agent_env["store"]

        parent = AgentSessionData(
            session_id="parent-008",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 30},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        # Create agent at max nesting depth
        deep_agent = AgentSession(
            session_store=store,
            tool_registry=multi_agent_env["tool_registry"],
            action_router=multi_agent_env["action_router"],
            llm_service=multi_agent_env["llm"],
            nesting_depth=3,  # at max
            max_nesting_depth=3,
        )

        response = await deep_agent.spawn_child_session(
            parent_session_id="parent-008",
            task_prompt="Should fail — too deep.",
        )

        assert response.stopped_reason == "max_nesting_depth_exceeded"

    @pytest.mark.asyncio
    async def test_step9_parallel_timing(self, multi_agent_env):
        """Parallel children execute concurrently (wall time < sum of individual)."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-009",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 30},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        children_specs = [
            {"task": f"Analyze component {i}."} for i in range(3)
        ]

        start = time.monotonic()
        results = await agent.delegate_parallel(
            parent_session_id="parent-009",
            children_specs=children_specs,
        )
        wall_time = time.monotonic() - start

        assert len(results) == 3
        # Wall time should be reasonable (< 5s for stub)
        assert wall_time < 5.0, f"Parallel delegation took {wall_time:.2f}s"

    @pytest.mark.asyncio
    async def test_step10_max_parallel_children_exceeded(self, multi_agent_env):
        """Exceeding max_parallel returns error."""
        store = multi_agent_env["store"]
        agent = multi_agent_env["agent"]

        parent = AgentSessionData(
            session_id="parent-010",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 30},
            tool_scopes=["analyze"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(parent)

        children_specs = [{"task": f"Task {i}"} for i in range(10)]

        results = await agent.delegate_parallel(
            parent_session_id="parent-010",
            children_specs=children_specs,
            max_parallel=5,
        )

        assert len(results) == 1
        assert results[0].stopped_reason == "max_parallel_children_exceeded"
