"""Tests for AgentBudget — Phase 7 P7-03.

Validates:
- Token, cost, wall-time limits (mirrors LLMBudget semantics)
- Tool call count limit (global)
- Per-tool call cap
- consume_llm / consume_tool_call bookkeeping
- snapshot() is JSON-serializable and complete
- from_config() round-trip
"""

from __future__ import annotations

import json
import time

import pytest

from app.core.agent.budget import AgentBudget


class TestAgentBudgetPreCheck:
    def test_fresh_budget_passes(self):
        b = AgentBudget()
        assert b.pre_check() is None

    def test_token_limit_exceeded(self):
        b = AgentBudget(max_total_tokens=100, consumed_tokens=100)
        assert b.pre_check() == "budget_exceeded_tokens"

    def test_cost_limit_exceeded(self):
        b = AgentBudget(max_total_cost_units=5.0, consumed_cost_units=5.0)
        assert b.pre_check() == "budget_exceeded_cost"

    def test_tool_call_limit_exceeded(self):
        b = AgentBudget(max_tool_calls=3, consumed_tool_calls=3)
        assert b.pre_check() == "budget_exceeded_tool_calls"

    def test_wall_time_exceeded(self):
        b = AgentBudget(max_wall_time_seconds=0.0, started_at=time.monotonic() - 1)
        result = b.pre_check()
        assert result == "budget_exceeded_time"


class TestAgentBudgetPreCheckTool:
    def test_per_tool_limit_exceeded(self):
        b = AgentBudget(
            per_tool_limits={"inventory_sync": 2},
            consumed_per_tool={"inventory_sync": 2},
        )
        assert b.pre_check_tool("inventory_sync") == "budget_exceeded_per_tool:inventory_sync"

    def test_per_tool_limit_not_exceeded(self):
        b = AgentBudget(
            per_tool_limits={"inventory_sync": 5},
            consumed_per_tool={"inventory_sync": 2},
        )
        assert b.pre_check_tool("inventory_sync") is None

    def test_unlisted_tool_no_per_tool_limit(self):
        b = AgentBudget(per_tool_limits={"inventory_sync": 2})
        assert b.pre_check_tool("recipe_generator") is None

    def test_global_limit_checked_before_per_tool(self):
        b = AgentBudget(max_tool_calls=0, consumed_tool_calls=0)
        # Global limit of 0 means can't call anything
        b.consumed_tool_calls = 0
        b.max_tool_calls = 0
        assert b.pre_check_tool("any_tool") == "budget_exceeded_tool_calls"


class TestAgentBudgetConsume:
    def test_consume_llm(self):
        b = AgentBudget()
        b.consume_llm(tokens=500, cost_units=1.5)
        assert b.consumed_tokens == 500
        assert b.consumed_cost_units == 1.5

        b.consume_llm(tokens=300, cost_units=0.5)
        assert b.consumed_tokens == 800
        assert b.consumed_cost_units == 2.0

    def test_consume_tool_call(self):
        b = AgentBudget()
        b.consume_tool_call("recipe_generator")
        b.consume_tool_call("recipe_generator")
        b.consume_tool_call("inventory_sync")

        assert b.consumed_tool_calls == 3
        assert b.consumed_per_tool["recipe_generator"] == 2
        assert b.consumed_per_tool["inventory_sync"] == 1

    def test_consume_negative_values_ignored(self):
        b = AgentBudget()
        b.consume_llm(tokens=-10, cost_units=-1.0)
        assert b.consumed_tokens == 0
        assert b.consumed_cost_units == 0.0


class TestAgentBudgetSnapshot:
    def test_snapshot_is_json_serializable(self):
        b = AgentBudget(
            max_total_tokens=5000,
            max_tool_calls=10,
            per_tool_limits={"recipe_generator": 3},
        )
        b.consume_llm(tokens=100, cost_units=0.5)
        b.consume_tool_call("recipe_generator")

        snap = b.snapshot()
        # Ensure JSON round-trip works
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["consumed_tokens"] == 100
        assert deserialized["consumed_tool_calls"] == 1
        assert deserialized["consumed_per_tool"]["recipe_generator"] == 1

    def test_snapshot_contains_all_fields(self):
        b = AgentBudget()
        snap = b.snapshot()
        expected_keys = {
            "budget_id",
            "max_total_tokens",
            "max_total_cost_units",
            "max_wall_time_seconds",
            "max_tool_calls",
            "per_tool_limits",
            "consumed_tokens",
            "consumed_cost_units",
            "consumed_tool_calls",
            "consumed_per_tool",
            "elapsed_seconds",
            "parent_budget_id",
            "child_budget_ids",
            "per_user_consumption",
        }
        assert set(snap.keys()) == expected_keys


class TestAgentBudgetFromConfig:
    def test_round_trip(self):
        b = AgentBudget(
            max_total_tokens=8000,
            max_tool_calls=15,
            per_tool_limits={"x": 5},
        )
        b.consume_llm(tokens=200, cost_units=1.0)
        b.consume_tool_call("x")
        b.consume_tool_call("x")

        config = b.to_config()
        b2 = AgentBudget.from_config(config)
        assert b2.max_total_tokens == 8000
        assert b2.max_tool_calls == 15
        assert b2.consumed_tokens == 200
        assert b2.consumed_tool_calls == 2
        assert b2.consumed_per_tool["x"] == 2

    def test_from_empty_config(self):
        b = AgentBudget.from_config({})
        assert b.max_total_tokens == 10_000
        assert b.max_tool_calls == 20
        assert b.consumed_tokens == 0


class TestAgentBudgetWouldExceed:
    def test_would_exceed_tokens_true(self):
        b = AgentBudget(max_total_tokens=1000, consumed_tokens=900)
        assert b.would_exceed_tokens(200) is True

    def test_would_exceed_tokens_false(self):
        b = AgentBudget(max_total_tokens=1000, consumed_tokens=500)
        assert b.would_exceed_tokens(200) is False

    def test_would_exceed_tokens_none_limit(self):
        b = AgentBudget(max_total_tokens=None)
        assert b.would_exceed_tokens(999999) is False
