"""Tests for P0-26 — Multi-user session cost attribution.

Covers:
  • per_user_consumption tracking in AgentBudget
  • consume_llm with user_id
  • consume_tool_call with user_id
  • Cascade to parent budget
  • Snapshot includes per-user breakdown
  • from_config roundtrip preserves per_user_consumption
  • Async variants pass user_id through
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from app.core.agent.budget import AgentBudget


# ===================================================================
# Per-user consumption tracking
# ===================================================================


class TestPerUserConsumption:
    def test_default_empty(self):
        b = AgentBudget()
        assert b.per_user_consumption == {}

    def test_consume_llm_with_user(self):
        b = AgentBudget()
        b.consume_llm(tokens=100, cost_units=1.0, user_id="user-A")
        assert b.per_user_consumption["user-A"]["tokens"] == 100
        assert b.per_user_consumption["user-A"]["cost_units"] == 1.0
        assert b.per_user_consumption["user-A"]["tool_calls"] == 0

    def test_consume_llm_without_user(self):
        b = AgentBudget()
        b.consume_llm(tokens=100, cost_units=1.0)
        assert b.per_user_consumption == {}
        assert b.consumed_tokens == 100

    def test_consume_tool_call_with_user(self):
        b = AgentBudget()
        b.consume_tool_call("search", user_id="user-B")
        assert b.per_user_consumption["user-B"]["tool_calls"] == 1
        assert b.per_user_consumption["user-B"]["tokens"] == 0

    def test_consume_tool_call_without_user(self):
        b = AgentBudget()
        b.consume_tool_call("search")
        assert b.per_user_consumption == {}
        assert b.consumed_tool_calls == 1

    def test_two_users_separate_attribution(self):
        b = AgentBudget()
        b.consume_llm(tokens=100, cost_units=1.0, user_id="alice")
        b.consume_llm(tokens=200, cost_units=2.0, user_id="bob")
        b.consume_tool_call("gen", user_id="alice")
        b.consume_tool_call("gen", user_id="bob")
        b.consume_tool_call("gen", user_id="bob")

        assert b.per_user_consumption["alice"]["tokens"] == 100
        assert b.per_user_consumption["alice"]["cost_units"] == 1.0
        assert b.per_user_consumption["alice"]["tool_calls"] == 1

        assert b.per_user_consumption["bob"]["tokens"] == 200
        assert b.per_user_consumption["bob"]["cost_units"] == 2.0
        assert b.per_user_consumption["bob"]["tool_calls"] == 2

        # Aggregate still correct
        assert b.consumed_tokens == 300
        assert b.consumed_tool_calls == 3

    def test_accumulation_same_user(self):
        b = AgentBudget()
        b.consume_llm(tokens=50, cost_units=0.5, user_id="user-A")
        b.consume_llm(tokens=50, cost_units=0.5, user_id="user-A")
        assert b.per_user_consumption["user-A"]["tokens"] == 100
        assert b.per_user_consumption["user-A"]["cost_units"] == 1.0


# ===================================================================
# Cascade to parent
# ===================================================================


class TestPerUserCascade:
    def test_child_consume_cascades_to_parent(self):
        parent = AgentBudget(max_tool_calls=100)
        child = parent.create_child(max_tool_calls=50)
        child.consume_llm(tokens=100, cost_units=1.0, user_id="user-A")
        child.consume_tool_call("tool_x", user_id="user-A")

        # Child has per-user
        assert child.per_user_consumption["user-A"]["tokens"] == 100
        assert child.per_user_consumption["user-A"]["tool_calls"] == 1
        # Parent also has per-user
        assert parent.per_user_consumption["user-A"]["tokens"] == 100
        assert parent.per_user_consumption["user-A"]["tool_calls"] == 1

    def test_two_children_different_users(self):
        parent = AgentBudget(max_tool_calls=100)
        c1 = parent.create_child(max_tool_calls=50)
        c2 = parent.create_child(max_tool_calls=50)

        c1.consume_llm(tokens=100, cost_units=1.0, user_id="alice")
        c2.consume_llm(tokens=200, cost_units=2.0, user_id="bob")

        assert parent.per_user_consumption["alice"]["tokens"] == 100
        assert parent.per_user_consumption["bob"]["tokens"] == 200
        assert parent.consumed_tokens == 300


# ===================================================================
# Snapshot and roundtrip
# ===================================================================


class TestSnapshotPerUser:
    def test_snapshot_includes_per_user(self):
        b = AgentBudget()
        b.consume_llm(tokens=100, cost_units=1.0, user_id="user-A")
        snap = b.snapshot()
        assert "per_user_consumption" in snap
        assert snap["per_user_consumption"]["user-A"]["tokens"] == 100

    def test_snapshot_empty_per_user(self):
        b = AgentBudget()
        snap = b.snapshot()
        assert snap["per_user_consumption"] == {}

    def test_to_config_roundtrip(self):
        b = AgentBudget()
        b.consume_llm(tokens=100, cost_units=1.0, user_id="user-A")
        b.consume_tool_call("gen", user_id="user-B")
        config = b.to_config()
        restored = AgentBudget.from_config(config)
        assert restored.per_user_consumption["user-A"]["tokens"] == 100
        assert restored.per_user_consumption["user-B"]["tool_calls"] == 1

    def test_from_config_missing_per_user(self):
        """Backward compat: old config without per_user_consumption."""
        config = {
            "max_total_tokens": 10000,
            "max_tool_calls": 20,
        }
        b = AgentBudget.from_config(config)
        assert b.per_user_consumption == {}


# ===================================================================
# Async variants
# ===================================================================


@pytest.mark.asyncio
async def test_async_consume_llm_with_user():
    b = AgentBudget()
    await b.async_consume_llm(tokens=50, cost_units=0.5, user_id="user-A")
    assert b.per_user_consumption["user-A"]["tokens"] == 50


@pytest.mark.asyncio
async def test_async_consume_tool_call_with_user():
    b = AgentBudget()
    await b.async_consume_tool_call("search", user_id="user-B")
    assert b.per_user_consumption["user-B"]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_concurrent_per_user_tracking():
    """Multiple users consuming concurrently — per-user totals correct."""
    parent = AgentBudget(max_tool_calls=200, max_total_tokens=100000)

    async def user_work(uid: str, budget: AgentBudget):
        for _ in range(10):
            await budget.async_consume_llm(tokens=10, cost_units=0.1, user_id=uid)
            await budget.async_consume_tool_call("tool", user_id=uid)

    tasks = [
        user_work("alice", parent),
        user_work("bob", parent),
        user_work("carol", parent),
    ]
    await asyncio.gather(*tasks)

    assert parent.per_user_consumption["alice"]["tokens"] == 100
    assert parent.per_user_consumption["bob"]["tokens"] == 100
    assert parent.per_user_consumption["carol"]["tokens"] == 100
    assert parent.per_user_consumption["alice"]["tool_calls"] == 10
    assert parent.consumed_tokens == 300
    assert parent.consumed_tool_calls == 30
