"""Tests for agent session telemetry and audit trail — Phase 7 P7-07.

Validates:
- AgentTrace / AgentTraceStep model serialization
- Structured trace produced after process_message
- Audit events emitted for: message_processed, tool_call
- Budget snapshot attached to every trace step
- Artifact stored with agent_trace kind
- Multi-tool session produces correct step count
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentResponse,
    AgentSessionData,
    AgentSessionMessage,
    AgentTrace,
    AgentTraceStep,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentSession, MAX_LOOP_ITERATIONS
from app.core.agent.tool_registry import ToolPermissionConfig, ToolRegistry
from app.core.blocks import BlockBase, BlockMetadata, BlockRegistry
from app.models.realtime.actions import Action, ActionResult, ActionStatus


# ===================================================================
# Stubs (shared across tests)
# ===================================================================

class StubBlockA(BlockBase):
    name = "tool_a"
    description = "Tool A"
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    output_schema = {"type": "object", "properties": {"y": {"type": "string"}}}

    def execute(self, inputs, **kwargs):
        return {"y": inputs.get("x", "")}


class StubBlockB(BlockBase):
    name = "tool_b"
    description = "Tool B"
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    output_schema = {"type": "object", "properties": {"y": {"type": "string"}}}

    def execute(self, inputs, **kwargs):
        return {"y": inputs.get("x", "")}


class StubBlockC(BlockBase):
    name = "tool_c"
    description = "Tool C"
    input_schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    output_schema = {"type": "object", "properties": {"y": {"type": "string"}}}

    def execute(self, inputs, **kwargs):
        return {"y": inputs.get("x", "")}


@dataclass(frozen=True)
class FakeGenerationResult:
    text: str = ""
    provider: str = "stub"
    model: str = "stub-model"
    tokens_in: int = 10
    tokens_out: int = 20
    cost_usd: float = 0.001
    extra: dict = None

    def __post_init__(self):
        if self.extra is None:
            object.__setattr__(self, "extra", {})


class FakeLLMService:
    def __init__(self, responses: List[str]):
        self._responses = list(responses)
        self._idx = 0

    async def agenerate_with_metadata(self, *, prompt, system_instruction="", **kwargs):
        text = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return FakeGenerationResult(text=text)


class FakeActionRouter:
    def __init__(self):
        self.calls = []

    def execute_action(self, action, model_name="unknown", force_reexecute=False):
        self.calls.append(action)
        return ActionResult(
            action_id=action.id,
            action_name=action.name,
            status=ActionStatus.SUCCESS,
            result={"ok": True},
        )


class FakeArtifactStore:
    def __init__(self):
        self.stored: List[Dict[str, Any]] = []

    def store(self, *, saga_id, step, kind, payload):
        ref = {"kind": kind, "saga_id": saga_id, "step": step, "uri": f"mem://{uuid.uuid4()}"}
        self.stored.append({"ref": ref, "payload": payload})
        return ref


class InMemorySessionStore:
    def __init__(self):
        self.sessions: Dict[str, AgentSessionData] = {}
        self.messages: Dict[str, List[AgentSessionMessage]] = {}

    async def create_session(self, session):
        self.sessions[session.session_id] = session
        self.messages.setdefault(session.session_id, [])
        return session

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def update_session(self, session):
        self.sessions[session.session_id] = session

    async def delete_session(self, session_id):
        self.sessions.pop(session_id, None)

    async def append_message(self, message):
        self.messages.setdefault(message.session_id, []).append(message)

    async def get_messages(self, session_id, *, limit=200):
        return self.messages.get(session_id, [])[:limit]


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture()
def block_registry():
    reg = BlockRegistry()
    for name, cls, desc in [
        ("tool_a", StubBlockA, "Tool A"),
        ("tool_b", StubBlockB, "Tool B"),
        ("tool_c", StubBlockC, "Tool C"),
    ]:
        reg.register(name, cls, description=desc,
                     input_schema=cls.input_schema, output_schema=cls.output_schema)
    return reg


@pytest.fixture()
def tool_registry(block_registry):
    perms = ToolPermissionConfig({"defaults": {"requires_confirmation": False}, "tools": {}})
    return ToolRegistry(block_registry, permissions=perms)


@pytest.fixture()
def store():
    return InMemorySessionStore()


@pytest.fixture()
def artifact_store():
    return FakeArtifactStore()


async def _make_session(store, **overrides):
    defaults = {
        "session_id": str(uuid.uuid4()),
        "user_id": "user-telem",
        "tool_scopes": ["tool_a", "tool_b", "tool_c"],
        "budget_config": AgentBudget().to_config(),
    }
    defaults.update(overrides)
    session = AgentSessionData(**defaults)
    await store.create_session(session)
    return session


# ===================================================================
# Tests — Model serialization
# ===================================================================

class TestAgentTraceModels:
    def test_trace_step_to_dict(self):
        step = AgentTraceStep(
            step_index=0,
            step_type="tool_executed",
            tool_name="tool_a",
            duration_ms=12.5,
            budget_snapshot={"consumed_tokens": 30},
            scope_check_result="allowed",
        )
        d = step.to_dict()
        assert d["step_type"] == "tool_executed"
        assert d["tool_name"] == "tool_a"
        assert d["duration_ms"] == 12.5

    def test_trace_to_dict(self):
        trace = AgentTrace(session_id="s1", user_id="u1")
        trace.add_step(step_type="llm_call", duration_ms=100)
        trace.add_step(step_type="tool_executed", tool_name="tool_a")
        trace.finalize({"consumed_tokens": 50})

        d = trace.to_dict()
        assert d["session_id"] == "s1"
        assert d["user_id"] == "u1"
        assert len(d["steps"]) == 2
        assert d["steps"][0]["step_index"] == 0
        assert d["steps"][1]["step_index"] == 1
        assert d["ended_at"] is not None
        assert d["budget_snapshot"]["consumed_tokens"] == 50

    def test_trace_add_step_increments_index(self):
        trace = AgentTrace()
        for i in range(5):
            s = trace.add_step(step_type=f"step_{i}")
            assert s.step_index == i
        assert len(trace.steps) == 5


# ===================================================================
# Tests — Audit emission
# ===================================================================

class TestAuditEmission:
    @pytest.fixture()
    def audit_events(self):
        return []

    @pytest.fixture()
    def make_agent(self, store, tool_registry, artifact_store, audit_events):
        def _factory(llm_responses):
            def _emitter(action, details):
                audit_events.append({"action": action, "details": details})

            llm = FakeLLMService(llm_responses)
            router = FakeActionRouter()
            agent = AgentSession(
                session_store=store,
                tool_registry=tool_registry,
                action_router=router,
                llm_service=llm,
                artifact_store=artifact_store,
                audit_emitter=_emitter,
            )
            return agent, router
        return _factory

    async def test_message_processed_audit_emitted(self, make_agent, store, audit_events):
        agent, _ = make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        # Should have at least message_processed event
        actions = [e["action"] for e in audit_events]
        assert "agent_message_processed" in actions

    async def test_tool_call_audit_emitted(self, make_agent, store, audit_events):
        agent, router = make_agent([
            '<tool_call>{"name": "tool_a", "arguments": {"x": "v"}}</tool_call>',
            "Done.",
        ])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Use tool_a")
        actions = [e["action"] for e in audit_events]
        assert "agent_tool_call" in actions
        assert "agent_message_processed" in actions

    async def test_tool_call_audit_has_details(self, make_agent, store, audit_events):
        agent, _ = make_agent([
            '<tool_call>{"name": "tool_a", "arguments": {"x": "v"}}</tool_call>',
            "Done.",
        ])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Use tool_a")
        tool_events = [e for e in audit_events if e["action"] == "agent_tool_call"]
        assert len(tool_events) == 1
        details = tool_events[0]["details"]
        assert details["tool_name"] == "tool_a"
        assert details["session_id"] == session.session_id
        assert "action_id" in details
        assert "duration_ms" in details

    async def test_no_audit_when_emitter_is_none(self, store, tool_registry, artifact_store):
        """No crash when audit_emitter is None."""
        llm = FakeLLMService(["Hello!"])
        agent = AgentSession(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=llm,
            artifact_store=artifact_store,
            audit_emitter=None,
        )
        session = await _make_session(store)
        resp = await agent.process_message(session.session_id, "Hi")
        assert resp.text == "Hello!"

    async def test_message_processed_audit_has_trace_id(self, make_agent, store, audit_events):
        agent, _ = make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        msg_events = [e for e in audit_events if e["action"] == "agent_message_processed"]
        assert len(msg_events) == 1
        assert "trace_id" in msg_events[0]["details"]


# ===================================================================
# Tests — Structured trace in artifacts
# ===================================================================

class TestStructuredTraceArtifact:
    @pytest.fixture()
    def make_agent(self, store, tool_registry, artifact_store):
        def _factory(llm_responses):
            llm = FakeLLMService(llm_responses)
            router = FakeActionRouter()
            agent = AgentSession(
                session_store=store,
                tool_registry=tool_registry,
                action_router=router,
                llm_service=llm,
                artifact_store=artifact_store,
            )
            return agent, router
        return _factory

    async def test_artifact_contains_structured_trace(self, make_agent, store, artifact_store):
        agent, _ = make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        assert len(artifact_store.stored) == 1
        payload = artifact_store.stored[0]["payload"]
        # Structured trace has trace_id, session_id, steps, etc.
        assert "trace_id" in payload
        assert "session_id" in payload
        assert "steps" in payload
        assert payload["session_id"] == session.session_id

    async def test_trace_has_budget_snapshot(self, make_agent, store, artifact_store):
        agent, _ = make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        payload = artifact_store.stored[0]["payload"]
        assert "budget_snapshot" in payload
        assert "consumed_tokens" in payload["budget_snapshot"]

    async def test_three_tool_call_session_has_three_steps(self, make_agent, store, artifact_store):
        """After 3 tool calls, trace contains at least 3 tool_executed steps + LLM steps."""
        agent, router = make_agent([
            # First LLM call: 3 tools
            (
                '<tool_call>{"name": "tool_a", "arguments": {"x": "1"}}</tool_call>'
                '<tool_call>{"name": "tool_b", "arguments": {"x": "2"}}</tool_call>'
                '<tool_call>{"name": "tool_c", "arguments": {"x": "3"}}</tool_call>'
            ),
            "All three tools completed.",
        ])
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Run all three")
        assert len(router.calls) == 3

        payload = artifact_store.stored[0]["payload"]
        steps = payload["steps"]
        tool_steps = [s for s in steps if s["step_type"] == "tool_executed"]
        assert len(tool_steps) == 3
        # Each has a budget snapshot
        for ts in tool_steps:
            assert "budget_snapshot" in ts

    async def test_trace_ended_at_populated(self, make_agent, store, artifact_store):
        agent, _ = make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        payload = artifact_store.stored[0]["payload"]
        assert payload["ended_at"] is not None

    async def test_llm_call_step_in_trace(self, make_agent, store, artifact_store):
        agent, _ = make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        payload = artifact_store.stored[0]["payload"]
        llm_steps = [s for s in payload["steps"] if s["step_type"] == "llm_call"]
        assert len(llm_steps) >= 1

    async def test_denied_tool_has_scope_denied(self, make_agent, store, artifact_store):
        """Denied tool step has scope_check_result='denied'."""
        agent, _ = make_agent([
            '<tool_call>{"name": "tool_a", "arguments": {"x": "1"}}</tool_call>',
            "Could not use tool.",
        ])
        session = await _make_session(store, tool_scopes=[])  # empty → deny all

        await agent.process_message(session.session_id, "Use tool_a")
        payload = artifact_store.stored[0]["payload"]
        denied_steps = [s for s in payload["steps"] if s["step_type"] == "tool_denied"]
        assert len(denied_steps) == 1
        assert denied_steps[0]["scope_check_result"] == "denied"
