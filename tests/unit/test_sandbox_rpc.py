"""Tests for P7-15: Sandbox RPC protocol via Redis queue.

Covers:
  - SandboxDispatcher dispatches and receives results
  - Timeout path (no response → error)
  - Token issuance integration
  - Sandbox worker _process_job allowlist enforcement
  - Sandbox worker replay rejection
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.sandbox_dispatcher import (
    DEFAULT_TIMEOUT,
    RESULT_QUEUE_PREFIX,
    RPC_QUEUE,
    SandboxDispatcher,
)
from app.agent_sandbox_worker import _process_job, _track_rpc_id, _seen_rpc_ids, _seen_rpc_order


# ===================================================================
# Fake Redis (in-memory)
# ===================================================================

class FakeRedis:
    """Minimal Redis mock supporting rpush, blpop, delete, expire."""

    def __init__(self):
        self._queues: Dict[str, List[str]] = {}

    def rpush(self, key: str, value: str) -> int:
        self._queues.setdefault(key, []).append(value)
        return len(self._queues[key])

    def blpop(self, key: str, timeout: int = 0):
        items = self._queues.get(key, [])
        if items:
            return (key, items.pop(0))
        return None

    def delete(self, key: str):
        self._queues.pop(key, None)

    def expire(self, key: str, ttl: int):
        pass  # no-op for tests


# ===================================================================
# 1. SandboxDispatcher tests
# ===================================================================

class TestSandboxDispatcher:

    def test_dispatch_success(self):
        """Dispatcher sends job and receives result from result queue."""
        redis = FakeRedis()
        dispatcher = SandboxDispatcher(redis, timeout=5)

        # Simulate: sandbox worker would process and push result
        # We need to pre-populate the result queue
        # Since dispatch creates the rpc_id internally, we monkey-patch
        import app.core.agent.sandbox_dispatcher as mod
        original_uuid = uuid.uuid4

        fixed_id = str(uuid.uuid4())
        call_count = [0]
        def fake_uuid4():
            call_count[0] += 1
            if call_count[0] == 1:
                return type('obj', (object,), {'__str__': lambda s: fixed_id, 'hex': fixed_id.replace('-', '')})()
            return original_uuid()

        # Pre-populate result before dispatch
        result_key = f"{RESULT_QUEUE_PREFIX}{fixed_id}"
        redis.rpush(result_key, json.dumps({
            "rpc_id": fixed_id,
            "status": "success",
            "tool_output": {"result": "done"},
            "duration_ms": 42,
            "error": None,
        }))

        # Patch uuid to return our fixed ID
        import unittest.mock
        with unittest.mock.patch.object(mod.uuid, 'uuid4', return_value=type('U', (), {'__str__': lambda s: fixed_id})()):
            result = dispatcher.dispatch(
                session_id="s1",
                tool_name="inventory_sync",
                tool_input={"param": "value"},
            )

        assert result["status"] == "success"
        assert result["tool_output"] == {"result": "done"}
        assert result["duration_ms"] == 42

    def test_dispatch_timeout(self):
        """No result in queue → timeout error."""
        redis = FakeRedis()
        dispatcher = SandboxDispatcher(redis, timeout=1)

        result = dispatcher.dispatch(
            session_id="s1",
            tool_name="tool_a",
            tool_input={},
            timeout=0,  # instant timeout
        )

        assert result["status"] == "timeout"
        assert "timeout" in result["error"].lower()

    def test_dispatch_includes_token(self):
        """Token issuer is called during dispatch."""
        redis = FakeRedis()
        tokens_issued = []

        def fake_issuer(session_id, tool_name, rpc_id):
            tokens_issued.append((session_id, tool_name, rpc_id))
            return "fake-jwt"

        dispatcher = SandboxDispatcher(redis, token_issuer=fake_issuer, timeout=0)
        dispatcher.dispatch(
            session_id="s1",
            tool_name="tool_x",
            tool_input={},
        )

        # Verify token was requested
        assert len(tokens_issued) == 1
        assert tokens_issued[0][0] == "s1"
        assert tokens_issued[0][1] == "tool_x"

        # Verify RPC queue contains the token
        rpc_items = redis._queues.get(RPC_QUEUE, [])
        assert len(rpc_items) == 1
        job = json.loads(rpc_items[0])
        assert job["session_token"] == "fake-jwt"

    def test_dispatch_request_format(self):
        """Verify the RPC request JSON structure."""
        redis = FakeRedis()
        dispatcher = SandboxDispatcher(redis, timeout=0)

        dispatcher.dispatch(
            session_id="sess123",
            tool_name="recipe_gen",
            tool_input={"query": "pasta"},
        )

        items = redis._queues.get(RPC_QUEUE, [])
        assert len(items) == 1
        job = json.loads(items[0])
        assert "rpc_id" in job
        assert job["session_id"] == "sess123"
        assert job["tool_name"] == "recipe_gen"
        assert job["tool_input"] == {"query": "pasta"}
        assert "timeout_seconds" in job


# ===================================================================
# 2. Sandbox worker _process_job tests
# ===================================================================

class TestSandboxWorkerProcessJob:

    def setup_method(self):
        """Clear replay cache between tests."""
        _seen_rpc_ids.clear()
        _seen_rpc_order.clear()

    def test_tool_not_in_allowlist(self):
        job = {
            "rpc_id": str(uuid.uuid4()),
            "tool_name": "forbidden_tool",
            "tool_input": {},
        }
        result = _process_job(job, sandbox_allowlist={"safe_tool"})
        assert result["status"] == "error"
        assert "not allowed" in result["error"]

    def test_replay_rejection(self):
        rpc_id = str(uuid.uuid4())
        job = {
            "rpc_id": rpc_id,
            "tool_name": "safe_tool",
            "tool_input": {},
        }
        # First call: not replayed (but will fail on missing block)
        result1 = _process_job(job, sandbox_allowlist={"safe_tool"})
        # Second call with same rpc_id: replayed
        result2 = _process_job(job, sandbox_allowlist={"safe_tool"})
        assert result2["status"] == "error"
        assert "replay" in result2["error"].lower()

    def test_empty_allowlist_rejects_all(self):
        job = {
            "rpc_id": str(uuid.uuid4()),
            "tool_name": "any_tool",
            "tool_input": {},
        }
        result = _process_job(job, sandbox_allowlist=set())
        assert result["status"] == "error"
        assert "not allowed" in result["error"]


# ===================================================================
# 3. Replay tracking
# ===================================================================

class TestReplayTracking:

    def setup_method(self):
        _seen_rpc_ids.clear()
        _seen_rpc_order.clear()

    def test_first_seen_returns_false(self):
        assert _track_rpc_id("id1") is False

    def test_second_seen_returns_true(self):
        _track_rpc_id("id1")
        assert _track_rpc_id("id1") is True

    def test_different_ids_not_replayed(self):
        _track_rpc_id("id1")
        assert _track_rpc_id("id2") is False
