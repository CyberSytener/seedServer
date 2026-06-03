"""Tests for P7-16: Sandbox routing in AgentSession._execute_tool().

Covers:
  1. sandbox_required tool + sandbox enabled → dispatched via SandboxDispatcher
  2. sandbox_required tool + sandbox disabled → rejected with clear error
  3. sandbox_required + allowed_in_sandbox=false → rejected (config contradiction)
  4. non-sandbox tool → normal ActionRouter execution (unchanged)
  5. sandbox dispatch timeout → error returned
  6. sandbox_enabled flag in Settings
  7. trace entries for sandbox-routed tools
  8. audit events for sandbox routing
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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
from app.core.agent.tool_registry import ToolPermissionConfig


# ===================================================================
# Shared helpers
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
        self.calls: List[str] = []

    def execute_action(self, action: Any) -> FakeActionResult:
        self.calls.append(action.name)
        return FakeActionResult(result=f"local_result_{action.name}")


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


class SandboxToolRegistry:
    """Tool registry with sandbox permissions configured."""

    def __init__(self, *, sandbox_tools: Optional[Dict[str, Dict[str, Any]]] = None):
        config = {
            "defaults": {
                "require_scope": "agent:tools:execute",
                "sandbox_required": False,
                "requires_confirmation": False,
                "allowed_in_sandbox": False,
            },
            "tools": sandbox_tools or {},
        }
        self.permissions = ToolPermissionConfig(config)

    def list_tools_for_llm(self, scopes):
        return [
            {"type": "function", "function": {"name": "inventory_sync", "description": "", "parameters": {}}},
            {"type": "function", "function": {"name": "menu_lookup", "description": "", "parameters": {}}},
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


class FakeSandboxDispatcher:
    """Records dispatched calls and returns configurable results."""

    def __init__(self, *, result: Optional[Dict[str, Any]] = None):
        self.calls: List[Dict[str, Any]] = []
        self._result = result or {
            "rpc_id": "rpc-fake",
            "status": "success",
            "tool_output": "sandbox_result",
            "duration_ms": 42,
            "error": None,
        }

    def dispatch(self, *, session_id: str, tool_name: str, tool_input: Dict[str, Any], **kw) -> Dict[str, Any]:
        self.calls.append({
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
        })
        return self._result


async def _make_session_and_agent(
    *,
    sandbox_tools: Optional[Dict[str, Dict[str, Any]]] = None,
    sandbox_enabled: bool = False,
    sandbox_dispatcher: Any = None,
    action_router: Optional[FakeActionRouter] = None,
    tool_scopes: Optional[List[str]] = None,
    budget_kwargs: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Helper to create store, session, and AgentSession."""
    store = InMemoryStore()
    sid = str(uuid.uuid4())
    budget_cfg = AgentBudget(**(budget_kwargs or {"max_tool_calls": 10})).to_config()
    await store.create_session(AgentSessionData(
        session_id=sid,
        user_id="u1",
        budget_config=budget_cfg,
        tool_scopes=tool_scopes or ["*"],
    ))

    router = action_router or FakeActionRouter()
    registry = SandboxToolRegistry(sandbox_tools=sandbox_tools)

    agent = AgentSession(
        session_store=store,
        tool_registry=registry,
        action_router=router,
        llm_service=None,  # Not needed for _execute_tool tests
        sandbox_dispatcher=sandbox_dispatcher,
        sandbox_enabled=sandbox_enabled,
    )
    return store, sid, agent, router


# ===================================================================
# 1. Sandbox-required tool + sandbox enabled → dispatched to sandbox
# ===================================================================

class TestSandboxRouting:

    @pytest.mark.asyncio
    async def test_sandbox_tool_dispatched(self):
        """Tool with sandbox_required=true routes through SandboxDispatcher when enabled."""
        dispatcher = FakeSandboxDispatcher()
        store, sid, agent, router = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=True,
            sandbox_dispatcher=dispatcher,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        result = await agent._execute_tool(
            "inventory_sync", {"items": [1, 2]},
            session=session, budget=budget, trace=trace,
        )

        assert result["status"] == "success"
        assert result["result"] == "sandbox_result"
        assert len(dispatcher.calls) == 1
        assert dispatcher.calls[0]["tool_name"] == "inventory_sync"
        assert len(router.calls) == 0  # NOT routed locally
        assert any(t["step"] == "tool_executed_sandbox" for t in trace)


# ===================================================================
# 2. Sandbox-required tool + sandbox disabled → rejected
# ===================================================================

class TestSandboxDisabled:

    @pytest.mark.asyncio
    async def test_sandbox_required_but_disabled(self):
        """Tool with sandbox_required=true returns error when sandbox is disabled."""
        store, sid, agent, router = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=False,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        result = await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert result["status"] == "error"
        assert "sandbox" in result["error"].lower()
        assert "not enabled" in result["error"].lower()
        assert len(router.calls) == 0
        assert any(t.get("reason") == "sandbox_required_but_unavailable" for t in trace)

    @pytest.mark.asyncio
    async def test_sandbox_required_no_dispatcher(self):
        """sandbox_enabled=True but no dispatcher object → still rejected."""
        store, sid, agent, router = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=True,
            sandbox_dispatcher=None,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        result = await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert result["status"] == "error"
        assert "not enabled" in result["error"].lower()


# ===================================================================
# 3. Config contradiction: sandbox_required=true, allowed_in_sandbox=false
# ===================================================================

class TestConfigContradiction:

    @pytest.mark.asyncio
    async def test_sandbox_required_but_not_allowed(self):
        """sandbox_required=true + allowed_in_sandbox=false → config contradiction error."""
        dispatcher = FakeSandboxDispatcher()
        store, sid, agent, router = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": False,  # contradiction
                },
            },
            sandbox_enabled=True,
            sandbox_dispatcher=dispatcher,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        result = await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert result["status"] == "error"
        assert "contradiction" in result["error"].lower()
        assert len(dispatcher.calls) == 0


# ===================================================================
# 4. Non-sandbox tool → local ActionRouter (unchanged behavior)
# ===================================================================

class TestLocalRouting:

    @pytest.mark.asyncio
    async def test_non_sandbox_tool_uses_action_router(self):
        """Tool without sandbox_required goes through local ActionRouter as before."""
        dispatcher = FakeSandboxDispatcher()
        store, sid, agent, router = await _make_session_and_agent(
            sandbox_tools={},  # no sandbox tools configured
            sandbox_enabled=True,
            sandbox_dispatcher=dispatcher,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        result = await agent._execute_tool(
            "menu_lookup", {"query": "pasta"},
            session=session, budget=budget, trace=trace,
        )

        assert result["status"] == "success"
        assert "local_result" in result["result"]
        assert len(router.calls) == 1
        assert len(dispatcher.calls) == 0  # NOT sent to sandbox
        assert any(t["step"] == "tool_executed" for t in trace)


# ===================================================================
# 5. Sandbox dispatch timeout → error returned
# ===================================================================

class TestSandboxTimeout:

    @pytest.mark.asyncio
    async def test_sandbox_timeout_returns_error(self):
        """Sandbox timeout result is properly surfaced."""
        timeout_dispatcher = FakeSandboxDispatcher(result={
            "rpc_id": "rpc-timeout",
            "status": "timeout",
            "tool_output": None,
            "duration_ms": 30000,
            "error": "Sandbox timeout after 30s",
        })
        store, sid, agent, router = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=True,
            sandbox_dispatcher=timeout_dispatcher,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        result = await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert result["status"] == "timeout"
        assert result["result"] is None
        assert "timeout" in result["error"].lower()


# ===================================================================
# 6. Settings.sandbox_enabled default
# ===================================================================

class TestSettingsSandboxEnabled:

    def test_default_false(self):
        """SEED_SANDBOX_ENABLED defaults to False."""
        import os
        os.environ.pop("SEED_SANDBOX_ENABLED", None)
        from app.settings import get_settings
        s = get_settings()
        assert s.sandbox_enabled is False

    def test_env_true(self, monkeypatch):
        """SEED_SANDBOX_ENABLED=true → sandbox_enabled=True."""
        monkeypatch.setenv("SEED_SANDBOX_ENABLED", "true")
        from app.settings import get_settings
        s = get_settings()
        assert s.sandbox_enabled is True


# ===================================================================
# 7. Trace entries for sandbox-routed tools
# ===================================================================

class TestSandboxTraceEntries:

    @pytest.mark.asyncio
    async def test_trace_contains_sandbox_step(self):
        """Sandbox execution produces 'tool_executed_sandbox' trace entries."""
        dispatcher = FakeSandboxDispatcher()
        store, sid, agent, _ = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=True,
            sandbox_dispatcher=dispatcher,
        )
        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert len(trace) == 1
        entry = trace[0]
        assert entry["step"] == "tool_executed_sandbox"
        assert entry["tool_name"] == "inventory_sync"
        assert entry["rpc_id"] == "rpc-fake"
        assert "budget_snapshot" in entry
        assert "duration_ms" in entry


# ===================================================================
# 8. Audit events for sandbox routing
# ===================================================================

class TestSandboxAuditEvents:

    @pytest.mark.asyncio
    async def test_audit_emitted_for_sandbox_call(self):
        """Audit event emitted with 'agent_tool_call_sandbox' action."""
        dispatcher = FakeSandboxDispatcher()
        audit_events = []

        store, sid, agent, _ = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=True,
            sandbox_dispatcher=dispatcher,
        )
        agent.audit_emitter = lambda action, details: audit_events.append((action, details))

        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert len(audit_events) == 1
        action, details = audit_events[0]
        assert action == "agent_tool_call_sandbox"
        assert details["tool_name"] == "inventory_sync"
        assert details["rpc_id"] == "rpc-fake"

    @pytest.mark.asyncio
    async def test_audit_emitted_for_rejection(self):
        """Audit event emitted when sandbox tool is rejected."""
        audit_events = []

        store, sid, agent, _ = await _make_session_and_agent(
            sandbox_tools={
                "inventory_sync": {
                    "sandbox_required": True,
                    "allowed_in_sandbox": True,
                },
            },
            sandbox_enabled=False,
        )
        agent.audit_emitter = lambda action, details: audit_events.append((action, details))

        session = await store.get_session(sid)
        budget = AgentBudget.from_config(session.budget_config)
        trace: List[Dict[str, Any]] = []

        await agent._execute_tool(
            "inventory_sync", {},
            session=session, budget=budget, trace=trace,
        )

        assert len(audit_events) == 1
        action, details = audit_events[0]
        assert action == "agent_tool_rejected"
        assert details["reason"] == "sandbox_required_but_unavailable"
