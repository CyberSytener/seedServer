"""Tests for P7-08: UI context pack ingest endpoint.

Covers:
  - UIContextPack model validation (happy path, size limits, field constraints)
  - HTTP endpoint round-trip via TestClient
  - Agent loop includes context in LLM prompt
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Model under test
# ---------------------------------------------------------------------------
from app.core.agent.ui_context import (
    MAX_COMPONENTS,
    MAX_PAYLOAD_BYTES,
    MAX_RAW_TREE_BYTES,
    UIComponent,
    UIContextPack,
    UIContract,
    UIRoute,
)
from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import build_prompt


# ===================================================================
# 1. UIContextPack model validation
# ===================================================================

class TestUIContextPackModel:
    """Pydantic model validation tests."""

    def test_valid_minimal_pack(self):
        pack = UIContextPack(source="/app/src")
        assert pack.source == "/app/src"
        assert pack.framework == "unknown"
        assert pack.components == []
        assert pack.routes == []

    def test_valid_full_pack(self):
        pack = UIContextPack(
            source="https://github.com/org/repo",
            framework="react",
            components=[
                UIComponent(name="Header", path="src/Header.tsx"),
                UIComponent(name="Footer", path="src/Footer.tsx", props_schema={"title": "string"}),
            ],
            routes=[
                UIRoute(path="/home", component="HomePage"),
                UIRoute(path="/about", component="AboutPage", layout="MainLayout"),
            ],
            contracts=[
                UIContract(name="UserDTO", contract_schema='{"id": "int"}'),
            ],
            raw_tree="src/\n  Header.tsx\n  Footer.tsx",
        )
        assert pack.framework == "react"
        assert len(pack.components) == 2
        assert len(pack.routes) == 2
        assert len(pack.contracts) == 1
        assert "Header.tsx" in pack.raw_tree

    def test_invalid_framework(self):
        with pytest.raises(ValidationError, match="framework"):
            UIContextPack(source="/app", framework="angular")

    def test_valid_frameworks(self):
        for fw in ("react", "vue", "svelte", "unknown"):
            pack = UIContextPack(source="/app", framework=fw)
            assert pack.framework == fw

    def test_too_many_components(self):
        comps = [UIComponent(name=f"C{i}", path=f"c{i}.tsx") for i in range(MAX_COMPONENTS + 1)]
        with pytest.raises(ValidationError, match="Too many components"):
            UIContextPack(source="/app", components=comps)

    def test_max_components_ok(self):
        comps = [UIComponent(name=f"C{i}", path=f"c{i}.tsx") for i in range(MAX_COMPONENTS)]
        # This may fail on total size, so use minimal names
        # Actually 200 components with short names should be fine
        pack = UIContextPack(source="/app", components=comps)
        assert len(pack.components) == MAX_COMPONENTS

    def test_raw_tree_too_large(self):
        huge_tree = "x" * (MAX_RAW_TREE_BYTES + 1)
        with pytest.raises(ValidationError, match="raw_tree"):
            UIContextPack(source="/app", raw_tree=huge_tree)

    def test_raw_tree_max_ok(self):
        tree = "a" * MAX_RAW_TREE_BYTES
        pack = UIContextPack(source="/app", raw_tree=tree)
        assert len(pack.raw_tree) == MAX_RAW_TREE_BYTES

    def test_total_payload_too_large(self):
        """Total serialized payload must not exceed 100KB."""
        # raw_tree at 50KB + enough contracts to push total over 100KB
        big_tree = "x" * (MAX_RAW_TREE_BYTES - 100)
        big_contracts = [
            UIContract(name=f"Contract{i:04d}", contract_schema="y" * 500)
            for i in range(200)
        ]
        with pytest.raises(ValidationError, match="payload size"):
            UIContextPack(
                source="/app",
                raw_tree=big_tree,
                contracts=big_contracts,
            )


# ===================================================================
# 2. UIContextPack prompt generation
# ===================================================================

class TestContextPromptSection:
    """to_prompt_section() output tests."""

    def test_prompt_includes_framework_and_source(self):
        pack = UIContextPack(source="/my/app", framework="vue")
        section = pack.to_prompt_section()
        assert "vue" in section
        assert "/my/app" in section

    def test_prompt_includes_component_names(self):
        pack = UIContextPack(
            source="/app",
            framework="react",
            components=[
                UIComponent(name="NavBar", path="nav.tsx"),
                UIComponent(name="SidePanel", path="side.tsx"),
            ],
        )
        section = pack.to_prompt_section()
        assert "NavBar" in section
        assert "SidePanel" in section

    def test_prompt_includes_routes(self):
        pack = UIContextPack(
            source="/app",
            routes=[UIRoute(path="/dashboard", component="Dashboard")],
        )
        section = pack.to_prompt_section()
        assert "/dashboard" in section

    def test_prompt_includes_contracts(self):
        pack = UIContextPack(
            source="/app",
            contracts=[UIContract(name="OrderSchema")],
        )
        section = pack.to_prompt_section()
        assert "OrderSchema" in section

    def test_prompt_includes_raw_tree_preview(self):
        pack = UIContextPack(
            source="/app",
            raw_tree="src/\n  index.tsx\n  App.tsx",
        )
        section = pack.to_prompt_section()
        assert "index.tsx" in section


# ===================================================================
# 3. build_prompt() integration with ui_context
# ===================================================================

class TestBuildPromptWithContext:
    """Verify build_prompt includes UI context when provided."""

    def _make_msg(self, role: MessageRole, content: str) -> AgentSessionMessage:
        return AgentSessionMessage(
            session_id="s1",
            role=role,
            content=content,
        )

    def test_prompt_includes_ui_context(self):
        prompt = build_prompt(
            system_prompt="You are helpful.",
            history=[],
            tool_manifests=[],
            user_message="help me build a nav",
            ui_context="[UI Context — react from /app]\nComponents: NavBar, Footer",
        )
        assert "[UI Context — react from /app]" in prompt
        assert "NavBar" in prompt
        assert "help me build a nav" in prompt

    def test_prompt_without_ui_context(self):
        prompt = build_prompt(
            system_prompt="You are helpful.",
            history=[],
            tool_manifests=[],
            user_message="hello",
        )
        assert "[UI Context" not in prompt
        assert "hello" in prompt

    def test_context_role_messages_skipped_in_history(self):
        """Context messages in history are skipped (they're rendered via ui_context param)."""
        history = [
            self._make_msg(MessageRole.USER, "hi"),
            self._make_msg(MessageRole.CONTEXT, '{"source":"/app","framework":"react"}'),
            self._make_msg(MessageRole.AGENT, "hello"),
        ]
        prompt = build_prompt(
            system_prompt="sys",
            history=history,
            tool_manifests=[],
            user_message="next",
        )
        # The raw JSON context should NOT appear in prompt
        assert '"source":"/app"' not in prompt
        # But normal messages should
        assert "[User] hi" in prompt
        assert "[Agent] hello" in prompt


# ===================================================================
# 4. HTTP endpoint test via TestClient
# ===================================================================

class TestContextEndpoint:
    """Test POST /v1/agent/sessions/{id}/context via FastAPI TestClient."""

    @pytest.fixture()
    def store_and_client(self):
        """Build a TestClient with an in-memory session store stub."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.core.agent.tool_registry import ToolRegistry

        # --- In-memory session store ---
        _sessions: Dict[str, AgentSessionData] = {}
        _messages: Dict[str, List[AgentSessionMessage]] = {}

        class FakeStore:
            async def create_session(self, s: AgentSessionData) -> AgentSessionData:
                _sessions[s.session_id] = s
                _messages[s.session_id] = []
                return s
            async def get_session(self, sid: str) -> Optional[AgentSessionData]:
                return _sessions.get(sid)
            async def update_session(self, s: AgentSessionData) -> None:
                _sessions[s.session_id] = s
            async def delete_session(self, sid: str) -> None:
                _sessions.pop(sid, None)
            async def append_message(self, msg: AgentSessionMessage) -> None:
                _messages.setdefault(msg.session_id, []).append(msg)
            async def get_messages(self, sid: str) -> List[AgentSessionMessage]:
                return _messages.get(sid, [])
            async def list_sessions_for_user(self, uid: str) -> List[AgentSessionData]:
                return [s for s in _sessions.values() if s.user_id == uid]

        fake_store = FakeStore()

        # --- Fake auth ---
        @dataclass
        class FakeAuth:
            user_id: str = "user1"
            scopes: List[str] = field(default_factory=lambda: ["agent:*"])
            def has_scope(self, s: str) -> bool:
                return True

        def fake_auth_provider(request, scope):
            return FakeAuth()

        # --- Build router ---
        from app.api.agent_routes import build_agent_router

        tool_registry = ToolRegistry.__new__(ToolRegistry)
        tool_registry._allowed_tools = set()
        tool_registry._block_registry = None

        router = build_agent_router(
            session_store=fake_store,
            tool_registry=tool_registry,
            action_router=None,
            llm_service=None,
            auth_provider=fake_auth_provider,
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # Pre-create a session
        sid = str(uuid.uuid4())
        import asyncio
        asyncio.run(
            fake_store.create_session(
                AgentSessionData(session_id=sid, user_id="user1")
            )
        )

        return fake_store, client, sid

    def test_ingest_context_success(self, store_and_client):
        store, client, sid = store_and_client
        payload = {
            "source": "/my/frontend",
            "framework": "react",
            "components": [
                {"name": "App", "path": "App.tsx"},
                {"name": "Nav", "path": "Nav.tsx"},
            ],
            "routes": [{"path": "/", "component": "App"}],
        }
        resp = client.post(f"/v1/agent/sessions/{sid}/context", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == sid
        assert data["source"] == "/my/frontend"
        assert data["components_count"] == 2
        assert data["routes_count"] == 1

    def test_ingest_context_persists_message(self, store_and_client):
        store, client, sid = store_and_client
        payload = {"source": "/src", "framework": "vue", "components": []}
        client.post(f"/v1/agent/sessions/{sid}/context", json=payload)

        import asyncio
        msgs = asyncio.run(
            store.get_messages(sid)
        )
        assert len(msgs) == 1
        assert msgs[0].role == MessageRole.CONTEXT
        # Content is valid UIContextPack JSON
        pack = UIContextPack.model_validate_json(msgs[0].content)
        assert pack.source == "/src"
        assert pack.framework == "vue"

    def test_ingest_context_session_not_found(self, store_and_client):
        _, client, _ = store_and_client
        resp = client.post(
            f"/v1/agent/sessions/{uuid.uuid4()}/context",
            json={"source": "/x"},
        )
        assert resp.status_code == 404

    def test_ingest_context_invalid_framework(self, store_and_client):
        _, client, sid = store_and_client
        payload = {"source": "/x", "framework": "angular"}
        resp = client.post(f"/v1/agent/sessions/{sid}/context", json=payload)
        assert resp.status_code == 413  # validation error → 413

    def test_ingest_context_too_many_components(self, store_and_client):
        _, client, sid = store_and_client
        payload = {
            "source": "/x",
            "components": [{"name": f"C{i}", "path": f"c{i}"} for i in range(MAX_COMPONENTS + 1)],
        }
        resp = client.post(f"/v1/agent/sessions/{sid}/context", json=payload)
        assert resp.status_code == 413

    def test_ingest_context_raw_tree_too_large(self, store_and_client):
        _, client, sid = store_and_client
        payload = {
            "source": "/x",
            "raw_tree": "z" * (MAX_RAW_TREE_BYTES + 1),
        }
        resp = client.post(f"/v1/agent/sessions/{sid}/context", json=payload)
        assert resp.status_code == 413


# ===================================================================
# 5. Agent loop includes context in prompt (integration)
# ===================================================================

class TestAgentLoopWithContext:
    """Test that AgentSession.process_message includes UI context."""

    @pytest.fixture()
    def agent_parts(self):
        """Set up minimal stubs for AgentSession."""
        _sessions: Dict[str, AgentSessionData] = {}
        _messages: Dict[str, List[AgentSessionMessage]] = {}

        class FakeStore:
            async def create_session(self, s):
                _sessions[s.session_id] = s; _messages[s.session_id] = []; return s
            async def get_session(self, sid):
                return _sessions.get(sid)
            async def update_session(self, s):
                _sessions[s.session_id] = s
            async def append_message(self, msg):
                _messages.setdefault(msg.session_id, []).append(msg)
            async def get_messages(self, sid):
                return _messages.get(sid, [])

        store = FakeStore()

        # Build a ToolRegistry stub that returns no tools
        from app.core.agent.tool_registry import ToolRegistry
        tr = ToolRegistry.__new__(ToolRegistry)
        tr._allowed_tools = set()
        tr._block_registry = None

        # Capture the prompt sent to LLM
        prompts_seen: List[str] = []

        @dataclass
        class FakeGenResult:
            text: str = "I see your components."
            tokens_in: int = 10
            tokens_out: int = 10
            cost_usd: float = 0.001
            provider: str = "test"
            model: str = "test"

        class FakeLLM:
            async def agenerate_with_metadata(self, prompt, system_instruction=None, **kw):
                prompts_seen.append(prompt)
                return FakeGenResult()

        class FakeToolRegistryFull:
            def list_tools_for_llm(self, scopes):
                return []
            def is_tool_allowed(self, name, scopes):
                return False

        return store, FakeToolRegistryFull(), FakeLLM(), prompts_seen

    @pytest.mark.asyncio
    async def test_context_message_appears_in_prompt(self, agent_parts):
        store, tool_reg, llm, prompts_seen = agent_parts

        from app.core.agent.session import AgentSession

        sid = str(uuid.uuid4())
        session = AgentSessionData(session_id=sid, user_id="u1")
        await store.create_session(session)

        # Push a context message into history
        pack = UIContextPack(
            source="/my/app",
            framework="react",
            components=[
                UIComponent(name="Dashboard", path="src/Dashboard.tsx"),
            ],
        )
        await store.append_message(AgentSessionMessage(
            session_id=sid,
            role=MessageRole.CONTEXT,
            content=pack.model_dump_json(),
        ))

        agent = AgentSession(
            session_store=store,
            tool_registry=tool_reg,
            action_router=None,
            llm_service=llm,
        )
        resp = await agent.process_message(sid, "How do I add a sidebar?")

        assert resp.text == "I see your components."
        # Verify the prompt included UI context
        assert len(prompts_seen) == 1
        prompt = prompts_seen[0]
        assert "[UI Context" in prompt
        assert "Dashboard" in prompt
        assert "react" in prompt
        assert "/my/app" in prompt

    @pytest.mark.asyncio
    async def test_no_context_message_no_context_in_prompt(self, agent_parts):
        store, tool_reg, llm, prompts_seen = agent_parts

        from app.core.agent.session import AgentSession

        sid = str(uuid.uuid4())
        session = AgentSessionData(session_id=sid, user_id="u1")
        await store.create_session(session)

        agent = AgentSession(
            session_store=store,
            tool_registry=tool_reg,
            action_router=None,
            llm_service=llm,
        )
        resp = await agent.process_message(sid, "Hello")

        assert len(prompts_seen) == 1
        assert "[UI Context" not in prompts_seen[0]


# ===================================================================
# 6. JSON round-trip (serialize → deserialize)
# ===================================================================

class TestContextRoundTrip:
    """UIContextPack serializes to JSON and deserializes identically."""

    def test_round_trip(self):
        pack = UIContextPack(
            source="/repo",
            framework="svelte",
            components=[UIComponent(name="Card", path="Card.svelte", slots=["header", "body"])],
            routes=[UIRoute(path="/cards", component="CardList")],
            contracts=[UIContract(name="CardDTO", contract_schema='{"id": "string"}')],
            raw_tree="src/\n  Card.svelte\n  CardList.svelte",
        )
        json_str = pack.model_dump_json()
        restored = UIContextPack.model_validate_json(json_str)
        assert restored.source == pack.source
        assert restored.framework == pack.framework
        assert len(restored.components) == 1
        assert restored.components[0].name == "Card"
        assert restored.components[0].slots == ["header", "body"]
        assert len(restored.routes) == 1
        assert restored.routes[0].path == "/cards"
        assert restored.contracts[0].contract_schema == '{"id": "string"}'
        assert restored.raw_tree == pack.raw_tree
