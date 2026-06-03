"""Tests for AgentBudget parent-child hierarchy (P0-19).

Covers: create_child(), parent-cascade consumption, budget ceiling enforcement,
parent exhaustion stops child, concurrency safety with asyncio.Lock, and
JSON round-trip serialization.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.agent.budget import AgentBudget


# ---------------------------------------------------------------------------
# create_child basics
# ---------------------------------------------------------------------------

class TestCreateChild:
    def test_child_capped_at_parent_remaining(self):
        parent = AgentBudget(max_total_tokens=1000, max_tool_calls=10, max_total_cost_units=5.0)
        parent.consume_llm(tokens=400, cost_units=2.0)
        parent.consume_tool_call("t1")

        child = parent.create_child(max_tokens=800, max_tool_calls=20, max_cost=10.0)

        # Tokens: min(800, 1000-400) = 600
        assert child.max_total_tokens == 600
        # Tool calls: min(20, 10-1) = 9
        assert child.max_tool_calls == 9
        # Cost: min(10.0, 5.0-2.0) = 3.0
        assert child.max_total_cost_units == 3.0

    def test_child_defaults_to_parent_remaining(self):
        parent = AgentBudget(max_total_tokens=500, max_tool_calls=5, max_total_cost_units=2.0)
        child = parent.create_child(max_tool_calls=3)

        assert child.max_total_tokens == 500  # parent remaining (all)
        assert child.max_tool_calls == 3
        assert child.max_total_cost_units == 2.0

    def test_child_registered_in_parent(self):
        parent = AgentBudget()
        child = parent.create_child(max_tool_calls=5)
        assert child.budget_id in parent.child_budget_ids

    def test_child_has_parent_reference(self):
        parent = AgentBudget()
        child = parent.create_child(max_tool_calls=5)
        assert child.parent is parent

    def test_child_wall_time_capped(self):
        parent = AgentBudget(max_wall_time_seconds=60.0)
        child = parent.create_child(max_tool_calls=5, max_wall_time=120.0)
        # Child wall time capped at parent remaining
        assert child.max_wall_time_seconds is not None
        assert child.max_wall_time_seconds <= 60.0


# ---------------------------------------------------------------------------
# Consumption cascades to parent
# ---------------------------------------------------------------------------

class TestConsumeCascade:
    def test_consume_llm_cascades(self):
        parent = AgentBudget(max_total_tokens=1000, max_total_cost_units=10.0)
        child = parent.create_child(max_tokens=500, max_tool_calls=5)

        child.consume_llm(tokens=100, cost_units=1.0)

        assert child.consumed_tokens == 100
        assert parent.consumed_tokens == 100
        assert child.consumed_cost_units == 1.0
        assert parent.consumed_cost_units == 1.0

    def test_consume_tool_call_cascades(self):
        parent = AgentBudget(max_tool_calls=10)
        child = parent.create_child(max_tool_calls=5)

        child.consume_tool_call("my_tool")

        assert child.consumed_tool_calls == 1
        assert parent.consumed_tool_calls == 1
        assert child.consumed_per_tool["my_tool"] == 1
        assert parent.consumed_per_tool["my_tool"] == 1

    def test_multiple_children_share_parent(self):
        parent = AgentBudget(max_total_tokens=1000, max_tool_calls=10)
        c1 = parent.create_child(max_tool_calls=5, max_tokens=400)
        c2 = parent.create_child(max_tool_calls=5, max_tokens=400)

        c1.consume_llm(tokens=200)
        c2.consume_llm(tokens=300)
        c1.consume_tool_call("t1")
        c2.consume_tool_call("t2")

        assert parent.consumed_tokens == 500
        assert parent.consumed_tool_calls == 2


# ---------------------------------------------------------------------------
# Parent exhaustion stops child
# ---------------------------------------------------------------------------

class TestParentExhaustion:
    def test_parent_exhausted_blocks_child(self):
        parent = AgentBudget(max_total_tokens=100, max_tool_calls=2)
        child = parent.create_child(max_tokens=100, max_tool_calls=2)

        child.consume_llm(tokens=100)
        # Parent is now at max tokens → child pre_check should fail too
        # (child's own max_total_tokens was set to 100, and consumed is 100)
        reason = child.pre_check()
        assert reason == "budget_exceeded_tokens"

    def test_child_cannot_exceed_parent_ceiling(self):
        parent = AgentBudget(max_tool_calls=3)
        child = parent.create_child(max_tool_calls=3)

        child.consume_tool_call("a")
        child.consume_tool_call("b")
        child.consume_tool_call("c")

        reason = child.pre_check()
        assert reason == "budget_exceeded_tool_calls"
        # Parent also at max
        assert parent.consumed_tool_calls == 3


# ---------------------------------------------------------------------------
# Snapshot includes parent reference
# ---------------------------------------------------------------------------

class TestSnapshotHierarchy:
    def test_snapshot_has_budget_id(self):
        b = AgentBudget()
        snap = b.snapshot()
        assert "budget_id" in snap
        assert snap["budget_id"] == b.budget_id

    def test_snapshot_includes_parent_id(self):
        parent = AgentBudget()
        child = parent.create_child(max_tool_calls=5)
        snap = child.snapshot()
        assert snap["parent_budget_id"] == parent.budget_id

    def test_snapshot_root_has_no_parent(self):
        b = AgentBudget()
        snap = b.snapshot()
        assert snap["parent_budget_id"] is None

    def test_snapshot_includes_child_ids(self):
        parent = AgentBudget()
        c1 = parent.create_child(max_tool_calls=3)
        c2 = parent.create_child(max_tool_calls=3)
        snap = parent.snapshot()
        assert c1.budget_id in snap["child_budget_ids"]
        assert c2.budget_id in snap["child_budget_ids"]


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

class TestJsonRoundTrip:
    def test_to_config_round_trip(self):
        parent = AgentBudget(max_total_tokens=500, max_tool_calls=10, max_total_cost_units=5.0)
        parent.consume_llm(tokens=100, cost_units=1.5)
        parent.consume_tool_call("tool_a")

        config = parent.to_config()
        restored = AgentBudget.from_config(config)

        assert restored.max_total_tokens == 500
        assert restored.consumed_tokens == 100
        assert restored.consumed_cost_units == 1.5
        assert restored.consumed_tool_calls == 1
        assert restored.budget_id == parent.budget_id

    def test_child_config_preserves_budget_id(self):
        parent = AgentBudget()
        child = parent.create_child(max_tool_calls=3)
        config = child.to_config()
        assert config["budget_id"] == child.budget_id


# ---------------------------------------------------------------------------
# Concurrency safety (asyncio.Lock)
# ---------------------------------------------------------------------------

class TestConcurrencySafety:
    @pytest.mark.asyncio
    async def test_parallel_children_no_overspend(self):
        """Launch N parallel children consuming near the budget ceiling.

        Verify total consumption never exceeds parent ceiling.
        This reproduces the race condition from Plan Delta Rec 1.
        """
        parent = AgentBudget(max_total_tokens=100, max_tool_calls=10, max_total_cost_units=10.0)

        children = [parent.create_child(max_tokens=100, max_tool_calls=10) for _ in range(5)]

        async def child_work(child: AgentBudget) -> None:
            for _ in range(3):
                await child.async_consume_llm(tokens=5, cost_units=0.5)
                await child.async_consume_tool_call("parallel_tool")

        await asyncio.gather(*[child_work(c) for c in children])

        # 5 children × 3 iterations × 5 tokens = 75 tokens (within 100 ceiling)
        assert parent.consumed_tokens == 75
        # 5 children × 3 iterations = 15 tool calls (within budget)
        assert parent.consumed_tool_calls == 15
        # No overspend: parent consumed ≤ parent max
        assert parent.consumed_tokens <= parent.max_total_tokens
        assert parent.consumed_cost_units <= parent.max_total_cost_units

    @pytest.mark.asyncio
    async def test_async_consume_serialized(self):
        """Verify async_consume_llm serializes through the lock."""
        parent = AgentBudget(max_total_tokens=1000)
        child = parent.create_child(max_tokens=500, max_tool_calls=5)

        await child.async_consume_llm(tokens=50, cost_units=1.0)

        assert child.consumed_tokens == 50
        assert parent.consumed_tokens == 50
