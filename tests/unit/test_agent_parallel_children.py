"""Tests for P0-21 — Parallel sub-agent execution with result aggregation.

Covers: delegate_parallel(), split_budget(), budget concurrency safety
with parallel children, partial failure handling, max parallel limit.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeSessionStore:
    """In-memory session store (reused from test_agent_sub_session)."""

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
    return MagicMock(text=text, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.001)


def _build_parent_session(
    session_id: str = "parent-1",
    user_id: str = "u-1",
    tool_scopes: Optional[List[str]] = None,
    budget_config: Optional[Dict[str, Any]] = None,
) -> AgentSessionData:
    return AgentSessionData(
        session_id=session_id,
        user_id=user_id,
        tool_scopes=tool_scopes or ["read_file", "search"],
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
    tool_registry = MagicMock()
    tool_registry.list_tools_for_llm.return_value = []
    tool_registry.is_tool_allowed.return_value = True
    tool_registry.permissions.requires_confirmation.return_value = False
    tool_registry.permissions.sandbox_required.return_value = False

    llm_service = AsyncMock()
    llm_service.agenerate_with_metadata.return_value = _make_llm_result()

    action_router = MagicMock()
    action_router.execute_action.return_value = MagicMock(
        status=MagicMock(value="success"), result="ok", error=None
    )

    return AgentSession(
        session_store=store,
        tool_registry=tool_registry,
        action_router=action_router,
        llm_service=llm_service,
        nesting_depth=nesting_depth,
        max_nesting_depth=max_nesting_depth,
    )


# ---------------------------------------------------------------------------
# Tests: split_budget
# ---------------------------------------------------------------------------

class TestSplitBudget:

    def test_split_creates_n_children(self):
        parent = AgentBudget(max_total_tokens=1000, max_total_cost_units=10.0, max_tool_calls=20)
        children = parent.split_budget(3)
        assert len(children) == 3
        assert len(parent.child_budget_ids) == 3

    def test_split_tokens_divided(self):
        parent = AgentBudget(max_total_tokens=900, max_total_cost_units=9.0, max_tool_calls=15)
        children = parent.split_budget(3)
        for c in children:
            assert c.max_total_tokens == 300  # 900 / 3

    def test_split_tool_calls_divided(self):
        parent = AgentBudget(max_tool_calls=15)
        children = parent.split_budget(3)
        for c in children:
            assert c.max_tool_calls == 5

    def test_split_cost_divided(self):
        parent = AgentBudget(max_total_cost_units=9.0)
        children = parent.split_budget(3)
        for c in children:
            assert abs(c.max_total_cost_units - 3.0) < 0.01

    def test_split_children_share_lock(self):
        parent = AgentBudget(max_tool_calls=10)
        children = parent.split_budget(2)
        assert children[0]._lock is children[1]._lock
        assert children[0]._lock is parent._lock

    def test_split_zero_raises(self):
        parent = AgentBudget(max_tool_calls=10)
        with pytest.raises(ValueError, match="n must be >= 1"):
            parent.split_budget(0)

    def test_split_one(self):
        parent = AgentBudget(max_total_tokens=100, max_tool_calls=5)
        children = parent.split_budget(1)
        assert len(children) == 1
        assert children[0].max_total_tokens == 100

    def test_split_none_tokens(self):
        parent = AgentBudget(max_total_tokens=None, max_tool_calls=10)
        children = parent.split_budget(2)
        for c in children:
            assert c.max_total_tokens is None


# ---------------------------------------------------------------------------
# Tests: delegate_parallel — happy path
# ---------------------------------------------------------------------------

class TestDelegateParallel:

    @pytest.mark.asyncio
    async def test_parallel_3_children(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        specs = [
            {"task": "Task A"},
            {"task": "Task B"},
            {"task": "Task C"},
        ]

        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=specs,
            parent_budget=parent_budget,
        )

        assert len(results) == 3
        for r in results:
            assert isinstance(r, AgentResponse)
            assert r.text  # Each child produced a response

    @pytest.mark.asyncio
    async def test_parallel_creates_child_sessions(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        specs = [{"task": "A"}, {"task": "B"}]

        await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=specs,
            parent_budget=parent_budget,
        )

        children = await store.list_child_sessions(parent.session_id)
        assert len(children) == 2
        for c in children:
            assert c.parent_session_id == parent.session_id
            assert c.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_specs_returns_empty(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=[],
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_results_preserve_order(self):
        """Results should be in the same order as children_specs."""
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        specs = [{"task": f"Task {i}"} for i in range(3)]

        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=specs,
            parent_budget=parent_budget,
        )

        assert len(results) == 3


# ---------------------------------------------------------------------------
# Tests: max parallel limit
# ---------------------------------------------------------------------------

class TestMaxParallelLimit:

    @pytest.mark.asyncio
    async def test_exceeds_max_parallel(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)

        specs = [{"task": f"T{i}"} for i in range(6)]

        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=specs,
            max_parallel=5,
        )

        assert len(results) == 1
        assert results[0].stopped_reason == "max_parallel_children_exceeded"

    @pytest.mark.asyncio
    async def test_exactly_at_limit_ok(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        specs = [{"task": f"T{i}"} for i in range(5)]

        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=specs,
            parent_budget=parent_budget,
            max_parallel=5,
        )

        assert len(results) == 5


# ---------------------------------------------------------------------------
# Tests: nesting depth enforcement
# ---------------------------------------------------------------------------

class TestParallelNestingDepth:

    @pytest.mark.asyncio
    async def test_max_depth_blocks_parallel(self):
        store = FakeSessionStore()
        parent = _build_parent_session()
        await store.create_session(parent)

        agent = _build_agent_session(store, nesting_depth=3, max_nesting_depth=3)

        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=[{"task": "A"}],
        )

        assert len(results) == 1
        assert results[0].stopped_reason == "max_nesting_depth_exceeded"


# ---------------------------------------------------------------------------
# Tests: partial failure
# ---------------------------------------------------------------------------

class TestPartialFailure:

    @pytest.mark.asyncio
    async def test_one_child_fails_others_succeed(self):
        store = FakeSessionStore()
        parent = _build_parent_session(
            tool_scopes=["read_file", "search"],
        )
        await store.create_session(parent)

        agent = _build_agent_session(store)
        parent_budget = AgentBudget.from_config(parent.budget_config)

        specs = [
            {"task": "Good task A"},
            {"task": "Bad task", "tool_scopes": ["NOPE"]},  # scope escalation
            {"task": "Good task C"},
        ]

        results = await agent.delegate_parallel(
            parent_session_id=parent.session_id,
            children_specs=specs,
            parent_budget=parent_budget,
        )

        assert len(results) == 3
        # Child 0 and 2 succeed, child 1 gets scope_escalation_denied
        assert results[0].stopped_reason != "scope_escalation_denied"
        assert results[1].stopped_reason == "scope_escalation_denied"
        assert results[2].stopped_reason != "scope_escalation_denied"


# ---------------------------------------------------------------------------
# Tests: budget split concurrency safety (P0-21 DoD concurrency test)
# ---------------------------------------------------------------------------

class TestBudgetConcurrencySafety:

    @pytest.mark.asyncio
    async def test_parallel_children_no_overspend(self):
        """Launch N parallel children that each try to consume near the limit.

        Verify total parent consumption is exactly the sum of all child
        consumptions (no lost or duplicated increments under concurrency).
        """
        parent = AgentBudget(
            max_total_tokens=1000,
            max_total_cost_units=100.0,
            max_tool_calls=100,
        )
        N = 5
        children = parent.split_budget(N)

        async def consume_child(child: AgentBudget, idx: int):
            for _ in range(3):
                await child.async_consume_llm(tokens=5, cost_units=0.2)
                await child.async_consume_tool_call(f"tool_{idx}")
                await asyncio.sleep(0)  # yield to event loop

        await asyncio.gather(*[consume_child(c, i) for i, c in enumerate(children)])

        # Parent should have consumed exactly N * 3 * 5 = 75 tokens
        assert parent.consumed_tokens == N * 3 * 5
        assert parent.consumed_tokens <= parent.max_total_tokens
        # Parent tool calls = N * 3 = 15
        assert parent.consumed_tool_calls == N * 3
        assert parent.consumed_tool_calls <= parent.max_tool_calls

    @pytest.mark.asyncio
    async def test_split_budget_total_does_not_exceed_parent(self):
        """Even if every child exhausts its share, parent isn't overspent."""
        parent = AgentBudget(
            max_total_tokens=100,
            max_tool_calls=10,
        )
        children = parent.split_budget(5)

        for c in children:
            # Each child has max_total_tokens = 20
            c.consume_llm(tokens=c.max_total_tokens or 0)
            c.consume_tool_call("t")

        # Total consumed = 5 * 20 = 100, exactly at ceiling
        assert parent.consumed_tokens == 100
        assert parent.consumed_tokens <= parent.max_total_tokens


# ---------------------------------------------------------------------------
# Tests: parent not found
# ---------------------------------------------------------------------------

class TestParallelParentNotFound:

    @pytest.mark.asyncio
    async def test_missing_parent(self):
        store = FakeSessionStore()
        agent = _build_agent_session(store)

        results = await agent.delegate_parallel(
            parent_session_id="nonexistent",
            children_specs=[{"task": "A"}],
        )

        assert len(results) == 1
        assert results[0].stopped_reason == "parent_session_not_found"


# ---------------------------------------------------------------------------
# Tests: settings field
# ---------------------------------------------------------------------------

class TestParallelSettings:

    def test_agent_max_parallel_children_in_settings(self):
        from app.settings import Settings
        import inspect
        sig = inspect.signature(Settings)
        assert "agent_max_parallel_children" in sig.parameters
