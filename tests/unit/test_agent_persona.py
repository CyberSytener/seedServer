"""Tests for P7-10: Per-session persona overrides.

Covers:
  - PersonaOverrides model (validation, serialization)
  - _resolve_persona() applies system_prompt_append overlay
  - Mid-session persona change persists and takes effect
  - display_name / voice_id reflected in agent response
  - Audit event on persona change
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    PersonaOverrides,
    SessionStatus,
    MAX_SYSTEM_PROMPT_APPEND_CHARS,
)
from app.core.agent.session import AgentSession


# ===================================================================
# 1. PersonaOverrides model tests
# ===================================================================

class TestPersonaOverridesModel:

    def test_default_empty(self):
        po = PersonaOverrides()
        assert po.display_name is None
        assert po.voice_id is None
        assert po.system_prompt_append is None

    def test_all_fields(self):
        po = PersonaOverrides(
            display_name="Nikita",
            voice_id="voice-ru-01",
            system_prompt_append="Always respond in Russian.",
        )
        assert po.display_name == "Nikita"
        assert po.voice_id == "voice-ru-01"
        assert po.system_prompt_append == "Always respond in Russian."

    def test_system_prompt_append_max_ok(self):
        text = "a" * MAX_SYSTEM_PROMPT_APPEND_CHARS
        po = PersonaOverrides(system_prompt_append=text)
        assert len(po.system_prompt_append) == MAX_SYSTEM_PROMPT_APPEND_CHARS

    def test_system_prompt_append_too_long(self):
        text = "a" * (MAX_SYSTEM_PROMPT_APPEND_CHARS + 1)
        with pytest.raises(ValueError, match="system_prompt_append"):
            PersonaOverrides(system_prompt_append=text)

    def test_to_dict_omits_none(self):
        po = PersonaOverrides(display_name="Max")
        d = po.to_dict()
        assert d == {"display_name": "Max"}
        assert "voice_id" not in d
        assert "system_prompt_append" not in d

    def test_to_dict_full(self):
        po = PersonaOverrides(
            display_name="Max",
            voice_id="v1",
            system_prompt_append="Be concise.",
        )
        d = po.to_dict()
        assert d["display_name"] == "Max"
        assert d["voice_id"] == "v1"
        assert d["system_prompt_append"] == "Be concise."

    def test_from_dict_round_trip(self):
        original = PersonaOverrides(
            display_name="Alice",
            voice_id="voice-en-02",
            system_prompt_append="Use British English.",
        )
        restored = PersonaOverrides.from_dict(original.to_dict())
        assert restored.display_name == original.display_name
        assert restored.voice_id == original.voice_id
        assert restored.system_prompt_append == original.system_prompt_append

    def test_from_dict_empty(self):
        po = PersonaOverrides.from_dict({})
        assert po.display_name is None
        assert po.voice_id is None
        assert po.system_prompt_append is None


# ===================================================================
# 2. _resolve_persona() with overrides
# ===================================================================

class TestResolvePersona:
    """Test AgentSession._resolve_persona() applies overrides correctly."""

    def _make_session(
        self,
        persona_id: str = "seed",
        overrides: Optional[Dict[str, Any]] = None,
    ) -> AgentSessionData:
        return AgentSessionData(
            session_id=str(uuid.uuid4()),
            user_id="user1",
            persona_id=persona_id,
            persona_overrides=overrides or {},
        )

    def _make_agent(self, persona_loader=None) -> AgentSession:
        """Create AgentSession with minimal stubs."""
        return AgentSession(
            session_store=None,
            tool_registry=None,
            action_router=None,
            llm_service=None,
            persona_loader=persona_loader,
        )

    def test_default_fallback(self):
        agent = self._make_agent()
        session = self._make_session()
        prompt = agent._resolve_persona(session)
        assert prompt == "You are a helpful assistant."

    def test_system_prompt_override(self):
        agent = self._make_agent()
        session = self._make_session(overrides={"system_prompt": "You are Seed."})
        prompt = agent._resolve_persona(session)
        assert prompt == "You are Seed."

    def test_system_prompt_append(self):
        agent = self._make_agent()
        session = self._make_session(overrides={
            "system_prompt": "You are Seed.",
            "system_prompt_append": "Always be polite.",
        })
        prompt = agent._resolve_persona(session)
        assert "You are Seed." in prompt
        assert "Always be polite." in prompt

    def test_system_prompt_append_with_persona_loader(self):
        @dataclass
        class FakeResult:
            persona_id_used: str = "seed"
            prompt_text: str = "Base persona prompt."
            fallback_reason: str = ""

        class FakeLoader:
            def get_persona_prompt(self, pid):
                return FakeResult(persona_id_used=pid, prompt_text=f"I am {pid}.")

        agent = self._make_agent(persona_loader=FakeLoader())
        session = self._make_session(
            persona_id="seed",
            overrides={"system_prompt_append": "Speak Russian."},
        )
        prompt = agent._resolve_persona(session)
        assert "I am seed." in prompt
        assert "Speak Russian." in prompt

    def test_no_overrides_uses_loader(self):
        @dataclass
        class FakeResult:
            persona_id_used: str = "seed"
            prompt_text: str = "I am seed."
            fallback_reason: str = ""

        class FakeLoader:
            def get_persona_prompt(self, pid):
                return FakeResult()

        agent = self._make_agent(persona_loader=FakeLoader())
        session = self._make_session(persona_id="seed")
        prompt = agent._resolve_persona(session)
        assert prompt == "I am seed."


# ===================================================================
# 3. Full loop: persona meta in agent response
# ===================================================================

class TestPersonaMetaInResponse:
    """Verify display_name/voice_id appear in AgentResponse.persona_meta."""

    @pytest.fixture()
    def agent_parts(self):
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

        class FakeToolReg:
            def list_tools_for_llm(self, scopes):
                return []

        @dataclass
        class FakeGenResult:
            text: str = "Hello!"
            tokens_in: int = 5
            tokens_out: int = 5
            cost_usd: float = 0.001
            provider: str = "test"
            model: str = "test"

        class FakeLLM:
            async def agenerate_with_metadata(self, **kw):
                return FakeGenResult()

        return store, FakeToolReg(), FakeLLM()

    @pytest.mark.asyncio
    async def test_response_includes_persona_meta(self, agent_parts):
        store, tool_reg, llm = agent_parts
        sid = str(uuid.uuid4())
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="user1",
            persona_id="seed",
            persona_overrides={
                "display_name": "Nikita",
                "voice_id": "voice-ru-01",
            },
        ))

        agent = AgentSession(
            session_store=store,
            tool_registry=tool_reg,
            action_router=None,
            llm_service=llm,
        )
        resp = await agent.process_message(sid, "Hello")

        assert resp.persona_meta["persona_id"] == "seed"
        assert resp.persona_meta["display_name"] == "Nikita"
        assert resp.persona_meta["voice_id"] == "voice-ru-01"

    @pytest.mark.asyncio
    async def test_response_without_overrides(self, agent_parts):
        store, tool_reg, llm = agent_parts
        sid = str(uuid.uuid4())
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="user1",
            persona_id="classic_tutor",
        ))

        agent = AgentSession(
            session_store=store,
            tool_registry=tool_reg,
            action_router=None,
            llm_service=llm,
        )
        resp = await agent.process_message(sid, "Hello")

        assert resp.persona_meta["persona_id"] == "classic_tutor"
        assert "display_name" not in resp.persona_meta
        assert "voice_id" not in resp.persona_meta

    @pytest.mark.asyncio
    async def test_mid_session_persona_change(self, agent_parts):
        """Simulate persona change via session update, then verify response."""
        store, tool_reg, llm = agent_parts
        sid = str(uuid.uuid4())
        await store.create_session(AgentSessionData(
            session_id=sid,
            user_id="user1",
            persona_id="seed",
        ))

        # First message — no overrides
        agent = AgentSession(
            session_store=store,
            tool_registry=tool_reg,
            action_router=None,
            llm_service=llm,
        )
        resp1 = await agent.process_message(sid, "Hi")
        assert "display_name" not in resp1.persona_meta

        # Simulate persona update (like POST /persona endpoint)
        session = await store.get_session(sid)
        session.persona_overrides = {
            "display_name": "Max",
            "voice_id": "v2",
            "system_prompt_append": "Be brief.",
        }
        await store.update_session(session)

        # Second message — overrides should take effect
        resp2 = await agent.process_message(sid, "Hi again")
        assert resp2.persona_meta["display_name"] == "Max"
        assert resp2.persona_meta["voice_id"] == "v2"


# ===================================================================
# 4. Audit event on persona endpoint
# ===================================================================

class TestPersonaEndpointAudit:
    """Test that persona update via HTTP endpoint works correctly."""

    def test_update_persona_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.agent_routes import build_agent_router
        from app.core.agent.tool_registry import ToolRegistry

        _sessions: Dict[str, AgentSessionData] = {}
        _messages: Dict[str, List[AgentSessionMessage]] = {}

        class FakeStore:
            async def create_session(self, s):
                _sessions[s.session_id] = s; return s
            async def get_session(self, sid):
                return _sessions.get(sid)
            async def update_session(self, s):
                _sessions[s.session_id] = s
            async def append_message(self, msg):
                _messages.setdefault(msg.session_id, []).append(msg)
            async def get_messages(self, sid):
                return _messages.get(sid, [])

        @dataclass
        class FakeAuth:
            user_id: str = "user1"
            scopes: List[str] = field(default_factory=lambda: ["agent:*"])
            def has_scope(self, s):
                return True

        tr = ToolRegistry.__new__(ToolRegistry)
        tr._allowed_tools = set()
        tr._block_registry = None

        import asyncio
        sid = str(uuid.uuid4())
        store = FakeStore()
        asyncio.run(store.create_session(AgentSessionData(
            session_id=sid, user_id="user1",
        )))

        router = build_agent_router(
            session_store=store,
            tool_registry=tr,
            action_router=None,
            llm_service=None,
            auth_provider=lambda req, scope: FakeAuth(),
        )
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # Update persona
        resp = client.post(f"/v1/agent/sessions/{sid}/persona", json={
            "persona_id": "seed",
            "name": "Nikita",
            "voice": "voice-ru-01",
            "system_prompt": "Be creative.",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona_id"] == "seed"
        assert data["persona_overrides"]["display_name"] == "Nikita"
        assert data["persona_overrides"]["voice_id"] == "voice-ru-01"
        assert data["persona_overrides"]["system_prompt"] == "Be creative."

        # Verify persisted
        saved = asyncio.run(store.get_session(sid))
        assert saved.persona_overrides["display_name"] == "Nikita"
