"""Tests for AgentSession runtime loop — Phase 7 P7-05.

All external dependencies (LLM, ActionRouter, store, persona, artifact)
are replaced with lightweight stubs / async mocks to keep tests fast
and deterministic.

Validates:
- Happy path: user message → LLM → tool call → ActionRouter → final response
- Multi-tool iteration loop
- Budget enforcement stops the loop
- Confirmation gate pauses execution
- Confirm message resumes and executes
- Cancel message discards pending tool
- Max iteration guard
- Session-not-found and inactive session
- Tool denied by allowlist
- History and messages persisted correctly
- Artifact store called with trace
"""

from __future__ import annotations

import asyncio
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
    MessageRole,
    PendingConfirmation,
    SessionStatus,
)
from app.core.agent.session import (
    AgentSession,
    MAX_LOOP_ITERATIONS,
    build_prompt,
    parse_tool_calls,
    strip_tool_calls,
)
from app.core.agent.tool_registry import ToolPermissionConfig, ToolRegistry
from app.core.blocks import BlockBase, BlockMetadata, BlockRegistry
from app.models.realtime.actions import Action, ActionResult, ActionStatus


# ===================================================================
# Stubs
# ===================================================================

class StubBlock(BlockBase):
    """A minimal block for testing."""

    name = "stub_echo"
    description = "Echoes input"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    output_schema = {"type": "object", "properties": {"echo": {"type": "string"}}}

    def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return {"echo": inputs.get("text", "")}

    @classmethod
    def metadata(cls) -> BlockMetadata:
        return BlockMetadata(
            name=cls.name,
            description=cls.description,
            input_schema=cls.input_schema,
            output_schema=cls.output_schema,
        )


class DangerousBlock(BlockBase):
    """Block that requires confirmation."""

    name = "dangerous_action"
    description = "Does something dangerous"
    input_schema = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}
    output_schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    def execute(self, inputs: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return {"ok": True}

    @classmethod
    def metadata(cls) -> BlockMetadata:
        return BlockMetadata(
            name=cls.name,
            description=cls.description,
            input_schema=cls.input_schema,
            output_schema=cls.output_schema,
        )


# --- Fake generation result ---

@dataclass(frozen=True)
class FakeGenerationResult:
    text: str = ""
    provider: str = "stub"
    model: str = "stub-model"
    tokens_in: int = 10
    tokens_out: int = 20
    cost_usd: float = 0.001
    extra: Dict[str, Any] = field(default_factory=dict)


class FakeLLMService:
    """Stub LLM that returns pre-configured responses in sequence."""

    def __init__(self, responses: List[str]):
        self._responses = list(responses)
        self._call_index = 0
        self.calls: List[Dict[str, Any]] = []

    async def agenerate_with_metadata(self, *, prompt: str, system_instruction: str = "", **kwargs):
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction})
        text = self._responses[min(self._call_index, len(self._responses) - 1)]
        self._call_index += 1
        return FakeGenerationResult(text=text)


class FakeActionRouter:
    """Stub ActionRouter that records calls and returns success."""

    def __init__(self, results: Optional[Dict[str, Any]] = None):
        self._results = results or {}
        self.calls: List[Action] = []

    def execute_action(self, action: Action, model_name: str = "unknown", force_reexecute: bool = False) -> ActionResult:
        self.calls.append(action)
        custom = self._results.get(action.name, {"status": "success", "result": {"ok": True}})
        return ActionResult(
            action_id=action.id,
            action_name=action.name,
            status=ActionStatus(custom.get("status", "success")),
            result=custom.get("result"),
            error=custom.get("error"),
        )


class FakeArtifactStore:
    """Stub artifact store that records calls."""

    def __init__(self):
        self.stored: List[Dict[str, Any]] = []

    def store(self, *, saga_id: str, step: str, kind: str, payload: Any) -> Dict[str, Any]:
        ref = {"kind": kind, "saga_id": saga_id, "step": step, "uri": f"mem://{uuid.uuid4()}"}
        self.stored.append({"ref": ref, "payload": payload})
        return ref


class FakePersonaLoader:
    """Stub persona loader."""

    def __init__(self, prompt: str = "You are a test assistant."):
        self._prompt = prompt

    def get_persona_prompt(self, persona_id_requested):
        @dataclass(frozen=True)
        class _Res:
            persona_id_used: str = persona_id_requested or "default"
            prompt_text: str = self._prompt
            fallback_reason: Optional[str] = None
        return _Res()


# --- In-memory session store ---

class InMemorySessionStore:
    """Async-compatible in-memory session store for tests."""

    def __init__(self):
        self.sessions: Dict[str, AgentSessionData] = {}
        self.messages: Dict[str, List[AgentSessionMessage]] = {}

    async def create_session(self, session: AgentSessionData) -> AgentSessionData:
        self.sessions[session.session_id] = session
        self.messages.setdefault(session.session_id, [])
        return session

    async def get_session(self, session_id: str) -> Optional[AgentSessionData]:
        return self.sessions.get(session_id)

    async def update_session(self, session: AgentSessionData) -> None:
        self.sessions[session.session_id] = session

    async def delete_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def append_message(self, message: AgentSessionMessage) -> None:
        self.messages.setdefault(message.session_id, []).append(message)

    async def get_messages(self, session_id: str, *, limit: int = 200) -> List[AgentSessionMessage]:
        return self.messages.get(session_id, [])[:limit]


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture()
def block_registry():
    reg = BlockRegistry()
    reg.register(
        "stub_echo", StubBlock,
        description="Echoes input",
        input_schema=StubBlock.input_schema,
        output_schema=StubBlock.output_schema,
    )
    reg.register(
        "dangerous_action", DangerousBlock,
        description="Does something dangerous",
        input_schema=DangerousBlock.input_schema,
        output_schema=DangerousBlock.output_schema,
    )
    return reg


@pytest.fixture()
def tool_registry(block_registry):
    perms = ToolPermissionConfig({
        "defaults": {"requires_confirmation": False},
        "tools": {
            "dangerous_action": {"requires_confirmation": True},
        },
    })
    return ToolRegistry(block_registry, permissions=perms)


@pytest.fixture()
def store():
    return InMemorySessionStore()


@pytest.fixture()
def artifact_store():
    return FakeArtifactStore()


@pytest.fixture()
def persona_loader():
    return FakePersonaLoader()


async def _make_session(store, **overrides):
    """Helper to create and persist a session."""
    defaults = {
        "session_id": str(uuid.uuid4()),
        "user_id": "user-test",
        "tool_scopes": ["stub_echo", "dangerous_action"],
        "budget_config": AgentBudget().to_config(),
    }
    defaults.update(overrides)
    session = AgentSessionData(**defaults)
    await store.create_session(session)
    return session


# ===================================================================
# Tests — parse helpers
# ===================================================================

class TestParseHelpers:
    def test_parse_tool_calls_basic(self):
        text = 'Let me check. <tool_call>{"name": "stub_echo", "arguments": {"text": "hi"}}</tool_call>'
        calls = parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "stub_echo"
        assert calls[0]["arguments"]["text"] == "hi"

    def test_parse_tool_calls_multiple(self):
        text = (
            '<tool_call>{"name": "a", "arguments": {}}</tool_call> '
            'then <tool_call>{"name": "b", "arguments": {}}</tool_call>'
        )
        assert len(parse_tool_calls(text)) == 2

    def test_parse_tool_calls_no_calls(self):
        assert parse_tool_calls("Just some text.") == []

    def test_parse_tool_calls_invalid_json(self):
        assert parse_tool_calls("<tool_call>not json</tool_call>") == []

    def test_strip_tool_calls(self):
        text = 'Hello <tool_call>{"name": "x", "arguments": {}}</tool_call> world'
        assert strip_tool_calls(text) == "Hello  world"

    def test_build_prompt_includes_user_message(self):
        prompt = build_prompt(
            system_prompt="sys",
            history=[],
            tool_manifests=[],
            user_message="Help me",
        )
        assert "Help me" in prompt


# ===================================================================
# Tests — session loop
# ===================================================================

class TestAgentSessionLoop:
    @pytest.fixture()
    def _make_agent(self, store, tool_registry, artifact_store, persona_loader):
        """Factory returning (agent, router, llm) for flexible LLM response config."""
        def _factory(llm_responses: List[str], router_results=None):
            llm = FakeLLMService(llm_responses)
            router = FakeActionRouter(router_results)
            agent = AgentSession(
                session_store=store,
                tool_registry=tool_registry,
                action_router=router,
                llm_service=llm,
                artifact_store=artifact_store,
                persona_loader=persona_loader,
            )
            return agent, router, llm
        return _factory

    # ----- Happy path -----

    async def test_simple_text_response(self, _make_agent, store):
        """LLM returns plain text — no tool calls."""
        agent, router, llm = _make_agent(["Hello! How can I help?"])
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Hi there")
        assert resp.text == "Hello! How can I help?"
        assert resp.stopped_reason is None
        assert len(router.calls) == 0
        assert len(llm.calls) == 1

    async def test_tool_call_and_final_response(self, _make_agent, store):
        """LLM requests one tool, gets result, produces final answer."""
        llm_responses = [
            '<tool_call>{"name": "stub_echo", "arguments": {"text": "ping"}}</tool_call>',
            "The echo said: ping",
        ]
        agent, router, llm = _make_agent(llm_responses)
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Echo ping for me")
        assert "ping" in resp.text or "echo" in resp.text.lower()
        assert len(router.calls) == 1
        assert router.calls[0].name == "stub_echo"
        # LLM called twice: once for planning, once for final answer
        assert len(llm.calls) == 2

    # ----- Budget enforcement -----

    async def test_budget_stops_loop(self, _make_agent, store):
        """Budget exceeded → loop stops gracefully."""
        agent, router, llm = _make_agent(["text"])
        session = await _make_session(
            store,
            budget_config={"max_total_tokens": 0},  # Already exhausted
        )

        resp = await agent.process_message(session.session_id, "Do something")
        assert resp.stopped_reason is not None
        assert "budget" in resp.stopped_reason

    async def test_tool_budget_exceeded(self, _make_agent, store):
        """Per-tool budget exhausted → error reported for that tool."""
        agent, router, llm = _make_agent([
            '<tool_call>{"name": "stub_echo", "arguments": {"text": "hi"}}</tool_call>',
            "Done.",
        ])
        session = await _make_session(
            store,
            budget_config={"max_tool_calls": 0},  # No tool calls allowed
        )

        resp = await agent.process_message(session.session_id, "Echo")
        # Tool should have been rejected by budget
        assert len(router.calls) == 0

    # ----- Confirmation gate -----

    async def test_confirmation_gate_pauses(self, _make_agent, store):
        """Tool requiring confirmation → pending confirmation returned, not executed."""
        agent, router, llm = _make_agent([
            '<tool_call>{"name": "dangerous_action", "arguments": {"target": "x"}}</tool_call>',
        ])
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Do the dangerous thing")
        assert len(resp.pending_confirmations) == 1
        assert resp.pending_confirmations[0]["tool_name"] == "dangerous_action"
        # ActionRouter should NOT have been called
        assert len(router.calls) == 0

    async def test_confirm_resumes_execution(self, _make_agent, store):
        """After user confirms, the tool is executed via ActionRouter."""
        agent, router, llm = _make_agent([
            '<tool_call>{"name": "dangerous_action", "arguments": {"target": "x"}}</tool_call>',
            "Done safely.",
        ])
        session = await _make_session(store)

        # First: gate pauses
        resp1 = await agent.process_message(session.session_id, "Do the dangerous thing")
        conf_id = resp1.pending_confirmations[0]["confirmation_id"]
        assert len(router.calls) == 0

        # Second: user confirms
        resp2 = await agent.process_message(session.session_id, f"confirm {conf_id}")
        # ActionRouter should have been called now
        assert len(router.calls) == 1
        assert router.calls[0].name == "dangerous_action"

    async def test_cancel_discards_tool(self, _make_agent, store):
        """After user cancels, the tool is NOT executed."""
        agent, router, llm = _make_agent([
            '<tool_call>{"name": "dangerous_action", "arguments": {"target": "x"}}</tool_call>',
            "Understood, cancelled.",
        ])
        session = await _make_session(store)

        resp1 = await agent.process_message(session.session_id, "Do the dangerous thing")
        conf_id = resp1.pending_confirmations[0]["confirmation_id"]

        resp2 = await agent.process_message(session.session_id, f"cancel {conf_id}")
        assert len(router.calls) == 0
        # Trace should record cancellation
        assert any(t.get("step") == "confirmation_cancelled" for t in resp2.trace)

    # ----- Tool denied -----

    async def test_tool_not_in_allowlist(self, _make_agent, store):
        """Tool not in session's tool_scopes → denied."""
        agent, router, llm = _make_agent([
            '<tool_call>{"name": "stub_echo", "arguments": {"text": "hi"}}</tool_call>',
            "Could not use that tool.",
        ])
        session = await _make_session(store, tool_scopes=[])  # Empty allowlist

        resp = await agent.process_message(session.session_id, "Echo for me")
        assert len(router.calls) == 0
        assert any(t.get("step") == "tool_denied" for t in resp.trace)

    # ----- Max iterations -----

    async def test_max_iterations_guard(self, _make_agent, store):
        """Loop terminates after MAX_LOOP_ITERATIONS."""
        # LLM keeps requesting tools forever
        endless_tool = '<tool_call>{"name": "stub_echo", "arguments": {"text": "loop"}}</tool_call>'
        agent, router, llm = _make_agent([endless_tool] * (MAX_LOOP_ITERATIONS + 2))
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Loop forever")
        assert resp.stopped_reason == "max_iterations_reached"
        assert len(router.calls) <= MAX_LOOP_ITERATIONS

    # ----- Session state -----

    async def test_session_not_found(self, _make_agent, store):
        agent, _, _ = _make_agent(["x"])
        resp = await agent.process_message("nonexistent-id", "Hello")
        assert resp.stopped_reason == "session_not_found"

    async def test_inactive_session(self, _make_agent, store):
        agent, _, _ = _make_agent(["x"])
        session = await _make_session(store, status=SessionStatus.COMPLETED)
        resp = await agent.process_message(session.session_id, "Hello")
        assert resp.stopped_reason == "session_inactive"

    # ----- Persistence -----

    async def test_messages_persisted(self, _make_agent, store):
        """All messages from the exchange are persisted."""
        agent, _, _ = _make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        msgs = await store.get_messages(session.session_id)
        roles = [m.role for m in msgs]
        assert MessageRole.USER in roles
        assert MessageRole.AGENT in roles

    async def test_budget_persisted_after_message(self, _make_agent, store):
        """Budget config is updated on session after processing."""
        agent, _, _ = _make_agent(["Hello!"])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hello")
        updated = await store.get_session(session.session_id)
        # Budget should reflect consumed tokens
        assert updated.budget_config.get("consumed_tokens", 0) > 0

    # ----- Artifact store -----

    async def test_artifact_store_called(self, _make_agent, store, artifact_store):
        agent, _, _ = _make_agent(["Done."])
        session = await _make_session(store)

        await agent.process_message(session.session_id, "Hi")
        assert len(artifact_store.stored) == 1
        assert artifact_store.stored[0]["ref"]["kind"] == "agent_trace"

    # ----- Trace -----

    async def test_trace_contains_llm_call(self, _make_agent, store):
        agent, _, _ = _make_agent(["Response."])
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Trace test")
        assert any(t.get("step") == "llm_call" for t in resp.trace)

    async def test_trace_contains_tool_execution(self, _make_agent, store):
        agent, router, _ = _make_agent([
            '<tool_call>{"name": "stub_echo", "arguments": {"text": "t"}}</tool_call>',
            "Final.",
        ])
        session = await _make_session(store)

        resp = await agent.process_message(session.session_id, "Run tool")
        assert any(t.get("step") == "tool_executed" for t in resp.trace)


# ===================================================================
# Tests — AgentResponse model
# ===================================================================

class TestAgentResponse:
    def test_to_dict(self):
        resp = AgentResponse(text="Hello", stopped_reason=None)
        d = resp.to_dict()
        assert d["text"] == "Hello"
        assert d["stopped_reason"] is None

    def test_default_values(self):
        resp = AgentResponse()
        assert resp.text == ""
        assert resp.artifacts == []
        assert resp.trace == []
