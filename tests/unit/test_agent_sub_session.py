"""Tests for P0-20 — Sub-agent session spawning in AgentSession.

Covers: spawn_child_session(), parent_session_id propagation, scope
escalation rejection, nesting depth enforcement, cross-session trace linkage,
and child budget cascade to parent.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentResponse,
    AgentSessionData,
    AgentSessionMessage,
    AgentTrace,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentSession
from app.core.agent.session_store import AgentSessionStore


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

class FakeSessionStore:
    """In-memory session store for testing (no DB required)."""

    def __init__(self) -> None:
        self._sessions: Dict[str, AgentSessionData] = {}
        self._messages: Dict[str, List[AgentSessionMessage]] = {}

    async def create_session(self, session: AgentSessionData) -> AgentSessionData:
        self._sessions[session.session_id] = session
        self._messages.setdefault(session.session_id, [])
        return session

    async def get_session(self, session_id: str) -> Optional[AgentSessionData]:
        return self._sessions.get(session_id)

    async def update_session(self, session: AgentSessionData) -> None:
        self._sessions[session.session_id] = session

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def list_sessions_for_user(self, user_id, **kw):
        return [s for s in self._sessions.values() if s.user_id == user_id]

    async def list_child_sessions(self, parent_session_id: str):
        return [
            s for s in self._sessions.values()
            if s.parent_session_id == parent_session_id
        ]

    async def append_message(self, message: AgentSessionMessage) -> None:
        self._messages.setdefault(message.session_id, []).append(message)

    async def get_messages(self, session_id: str, *, limit: int = 200):
        return self._messages.get(session_id, [])[:limit]


def _make_llm_result(text: str = "Done.", tokens_in: int = 10, tokens_out: int = 5):
    """Return a duck-typed LLM generation result."""
    return MagicMock(
        text=text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=0.001,
    )


def _make_action_result():
    return MagicMock(
        status=MagicMock(value="success"),
        result="ok",
        error=None,
    )


def _build_parent_session(
    session_id: str = "parent-1",
    user_id: str = "u-1",
    tool_scopes: Optional[List[str]] = None,
    budget_config: Optional[Dict[str, Any]] = None,
) -> AgentSessionData:
    return AgentSessionData(
        session_id=session_id,
        user_id=user_id,
        tool_scopes=tool_scopes or ["read_file", "write_file", "search"],
        budget_config=budget_config or {
            "max_total_tokens": 5000,
            "max_total_cost_units": 10.0,
            "max_tool_calls": 20,
            "max_wall_time_seconds": 60.0,
        },
    )


def _build_agent_session(
    store: FakeSessionStore,
    nesting_depth: int = 0,
    max_nesting_depth: int = 3,
) -> AgentSession:
    """Build an AgentSession wired to the fake store + mock services."""
    tool_registry = MagicMock()
    tool_registry.list_tools_for_llm.return_value = []
    tool_registry.is_tool_allowed.return_value = True
    tool_registry.permissions.requires_confirmation.return_value = False
    tool_registry.permissions.sandbox_required.return_value = False

    llm_service = AsyncMock()
    llm_service.agenerate_with_metadata.return_value = _make_llm_result()

    action_router = MagicMock()
    action_router.execute_action.return_value = _make_action_result()

    return AgentSession(
        session_store=store,
        tool_registry=tool_registry,
        action_router=action_router,
        llm_service=llm_service,
        nesting_depth=nesting_depth,
        max_nesting_depth=max_nesting_depth,
    )


# ---------------------------------------------------------------------------
# Tests: AgentSessionData.parent_session_id field
# ---------------------------------------------------------------------------

class TestParentSessionIdField:
    """Verify the new ``parent_session_id`` field on AgentSessionData."""

    def test_default_is_none(self):
        sd = AgentSessionData()
        assert sd.parent_session_id is None

    def test_set_via_constructor(self):
        sd = AgentSessionData(parent_session_id="parent-xyz")
        assert sd.parent_session_id == "parent-xyz"

    def test_to_row_includes_parent(self):
        sd = AgentSessionData(parent_session_id="p-1")
        row = sd.to_row()
        assert len(row) == 13
        assert row[-3] == "p-1"  # parent_session_id is third from end (before tenant_id, project_id)

    def test_to_row_none_parent(self):
        sd = AgentSessionData()
        row = sd.to_row()
        assert row[-3] is None  # parent_session_id is third from end

    def test_from_row_dict(self):
        sd = AgentSessionData(
            session_id="s1", user_id="u1", parent_session_id="p-1"
        )
        row = sd.to_row()
        # Tuple fallback (positional)
        restored = AgentSessionData.from_row(row)
        assert restored.parent_session_id == "p-1"
        assert restored.session_id == "s1"

    def test_from_row_tuple_backward_compat(self):
        """Old 10-element tuples should still work (parent_session_id=None)."""
        old_row = ("s1", "u1", "seed", "{}", "{}", "[]", "[]", "active", "t1", "t2")
        restored = AgentSessionData.from_row(old_row)
        assert restored.parent_session_id is None


# ---------------------------------------------------------------------------
# Tests: AgentTrace cross-session fields
# ---------------------------------------------------------------------------

class TestAgentTraceParentFields:
    def test_default_none(self):
        t = AgentTrace()
        assert t.parent_session_id is None
        assert t.parent_trace_id is None

    def test_set_fields(self):
        t = AgentTrace(parent_session_id="ps-1", parent_trace_id="pt-1")
        assert t.parent_session_id == "ps-1"
        assert t.parent_trace_id == "pt-1"

    def test_to_dict_includes_parent(self):
        t = AgentTrace(parent_session_id="ps-1", parent_trace_id="pt-1")
        d = t.to_dict()
        assert d["parent_session_id"] == "ps-1"
        assert d["parent_trace_id"] == "pt-1"

    def test_to_dict_none_parents(self):
        t = AgentTrace()
        d = t.to_dict()
        assert d["parent_session_id"] is None
        assert d["parent_trace_id"] is None


# ---------------------------------------------------------------------------
# Tests: spawn_child_session — happy path
# ---------------------------------------------------------------------------

class TestSpawnChildSession:

    @pytest.mark.asyncio
    async def test_spawn_creates_child_session(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            persona_id="coder",
            tool_scopes=["read_file", "search"],
            budget_limits={"max_tool_calls": 5},
            task_prompt="Analyze the file.",
            parent_budget=parent_budget,
        )

        # Child session should exist in the store
        children = await store.list_child_sessions(parent.session_id)
        assert len(children) == 1
        child = children[0]
        assert child.parent_session_id == parent.session_id
        assert child.persona_id == "coder"
        assert set(child.tool_scopes) == {"read_file", "search"}
        assert child.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_spawn_returns_agent_response(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Say hello.",
            parent_budget=parent_budget,
        )

        assert isinstance(resp, AgentResponse)
        assert resp.text  # LLM reply

    @pytest.mark.asyncio
    async def test_child_inherits_parent_user_id(self):
        store = FakeSessionStore()
        parent = _build_parent_session(user_id="user-42")
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Do work.",
            parent_budget=parent_budget,
        )

        children = await store.list_child_sessions(parent.session_id)
        assert children[0].user_id == "user-42"

    @pytest.mark.asyncio
    async def test_child_defaults_to_parent_scopes(self):
        store = FakeSessionStore()
        parent = _build_parent_session(tool_scopes=["a", "b", "c"])
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Work.",
            parent_budget=parent_budget,
            # no tool_scopes → should inherit parent's
        )

        children = await store.list_child_sessions(parent.session_id)
        assert set(children[0].tool_scopes) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Tests: spawn_child_session — scope escalation rejection
# ---------------------------------------------------------------------------

class TestScopeEscalation:

    @pytest.mark.asyncio
    async def test_escalation_denied(self):
        store = FakeSessionStore()
        parent = _build_parent_session(tool_scopes=["read_file", "search"])
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            tool_scopes=["read_file", "delete_all"],  # delete_all not in parent
            task_prompt="Escalate!",
            parent_budget=parent_budget,
        )

        assert resp.stopped_reason == "scope_escalation_denied"
        assert "delete_all" in resp.text
        # No child session created
        children = await store.list_child_sessions(parent.session_id)
        assert len(children) == 0

    @pytest.mark.asyncio
    async def test_exact_parent_scopes_allowed(self):
        store = FakeSessionStore()
        parent = _build_parent_session(tool_scopes=["a", "b"])
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            tool_scopes=["a", "b"],
            task_prompt="ok.",
            parent_budget=parent_budget,
        )

        assert resp.stopped_reason != "scope_escalation_denied"


# ---------------------------------------------------------------------------
# Tests: nesting depth enforcement
# ---------------------------------------------------------------------------

class TestNestingDepth:

    @pytest.mark.asyncio
    async def test_max_depth_rejected(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store, nesting_depth=3, max_nesting_depth=3)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Nest!",
        )

        assert resp.stopped_reason == "max_nesting_depth_exceeded"
        children = await store.list_child_sessions(parent.session_id)
        assert len(children) == 0

    @pytest.mark.asyncio
    async def test_depth_zero_allowed(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store, nesting_depth=0, max_nesting_depth=3)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Work.",
            parent_budget=parent_budget,
        )

        assert resp.stopped_reason != "max_nesting_depth_exceeded"

    @pytest.mark.asyncio
    async def test_depth_exactly_at_limit_rejected(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store, nesting_depth=2, max_nesting_depth=2)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Nest!",
        )

        assert resp.stopped_reason == "max_nesting_depth_exceeded"


# ---------------------------------------------------------------------------
# Tests: child budget cascade
# ---------------------------------------------------------------------------

class TestChildBudgetCascade:

    @pytest.mark.asyncio
    async def test_child_budget_capped_by_parent(self):
        store = FakeSessionStore()
        parent = _build_parent_session(budget_config={
            "max_total_tokens": 1000,
            "max_total_cost_units": 5.0,
            "max_tool_calls": 10,
            "max_wall_time_seconds": 60.0,
        })
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        resp = await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            budget_limits={"max_tool_calls": 5, "max_total_tokens": 500},
            task_prompt="Work.",
            parent_budget=parent_budget,
        )

        # Child was created with child budget from parent.create_child
        assert len(parent_budget.child_budget_ids) == 1

    @pytest.mark.asyncio
    async def test_child_consumption_reflected_in_parent(self):
        store = FakeSessionStore()
        parent = _build_parent_session(budget_config={
            "max_total_tokens": 5000,
            "max_total_cost_units": 10.0,
            "max_tool_calls": 20,
            "max_wall_time_seconds": 60.0,
        })
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        # Create child budget directly (in-memory cascade)
        child_budget = parent_budget.create_child(max_tool_calls=5)
        child_budget.consume_llm(tokens=100, cost_units=0.5)

        # Verify the cascade happened in-memory
        assert parent_budget.consumed_tokens == 100
        assert parent_budget.consumed_cost_units == 0.5
        # Also verify child budget is registered
        assert child_budget.budget_id in parent_budget.child_budget_ids


# ---------------------------------------------------------------------------
# Tests: parent not found
# ---------------------------------------------------------------------------

class TestParentNotFound:

    @pytest.mark.asyncio
    async def test_missing_parent_returns_error(self):
        store = FakeSessionStore()
        agent = _build_agent_session(store)

        resp = await agent.spawn_child_session(
            parent_session_id="nonexistent",
            task_prompt="Work.",
        )

        assert resp.stopped_reason == "parent_session_not_found"


# ---------------------------------------------------------------------------
# Tests: cross-session trace linkage
# ---------------------------------------------------------------------------

class TestCrossSessionTrace:

    @pytest.mark.asyncio
    async def test_child_session_has_parent_id_in_store(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        await agent.spawn_child_session(
            parent_session_id=parent.session_id,
            task_prompt="Work.",
            parent_budget=parent_budget,
        )

        children = await store.list_child_sessions(parent.session_id)
        assert children[0].parent_session_id == parent.session_id


# ---------------------------------------------------------------------------
# Tests: nesting_depth / max_nesting_depth on __init__
# ---------------------------------------------------------------------------

class TestAgentSessionInit:

    def test_default_nesting_depth(self):
        store = FakeSessionStore()
        agent = _build_agent_session(store)
        assert agent.nesting_depth == 0
        assert agent.max_nesting_depth == 3

    def test_custom_nesting_depth(self):
        store = FakeSessionStore()
        agent = _build_agent_session(store, nesting_depth=2, max_nesting_depth=5)
        assert agent.nesting_depth == 2
        assert agent.max_nesting_depth == 5


# ---------------------------------------------------------------------------
# Tests: settings field
# ---------------------------------------------------------------------------

class TestSettingsField:

    def test_agent_max_nesting_depth_in_settings(self):
        from app.settings import Settings
        import inspect
        sig = inspect.signature(Settings)
        param_names = list(sig.parameters.keys())
        assert "agent_max_nesting_depth" in param_names
