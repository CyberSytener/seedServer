"""Tests for Agent HTTP API endpoints — Phase 7 P7-06.

Uses FastAPI TestClient with in-memory stubs for all dependencies.

Validates:
- All 6 endpoints return correct responses
- Scope enforcement (403 on missing scope)
- Session isolation (user A cannot access user B's session)
- 404 on non-existent session
- Create → message → get → delete lifecycle
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.tool_registry import ToolPermissionConfig, ToolRegistry
from app.core.blocks import BlockBase, BlockMetadata, BlockRegistry
from app.api.agent_routes import build_agent_router


# ===================================================================
# Stubs (mirrored from test_agent_session_loop.py)
# ===================================================================

class StubBlock(BlockBase):
    name = "stub_echo"
    description = "Echoes input"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    output_schema = {"type": "object", "properties": {"echo": {"type": "string"}}}

    def execute(self, inputs, **kwargs):
        return {"echo": inputs.get("text", "")}

    @classmethod
    def metadata(cls) -> BlockMetadata:
        return BlockMetadata(name=cls.name, description=cls.description,
                             input_schema=cls.input_schema, output_schema=cls.output_schema)


@dataclass(frozen=True)
class FakeGenerationResult:
    text: str = "Stub response"
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
    def __init__(self, text="Stub response"):
        self._text = text

    async def agenerate_with_metadata(self, *, prompt, system_instruction="", **kwargs):
        return FakeGenerationResult(text=self._text)


class FakeActionRouter:
    def __init__(self):
        self.calls = []

    def execute_action(self, action, model_name="unknown", force_reexecute=False):
        from app.models.realtime.actions import ActionResult, ActionStatus
        self.calls.append(action)
        return ActionResult(
            action_id=action.id,
            action_name=action.name,
            status=ActionStatus.SUCCESS,
            result={"ok": True},
        )


class InMemorySessionStore:
    def __init__(self):
        self.sessions: Dict[str, AgentSessionData] = {}
        self.messages: Dict[str, List[AgentSessionMessage]] = {}
        self.participants: Dict[str, list] = {}  # session_id -> [SessionParticipant]

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

    async def list_child_sessions(self, parent_session_id):
        return [
            s for s in self.sessions.values()
            if s.parent_session_id == parent_session_id
        ]

    async def get_session_tree(self, root_session_id):
        root = await self.get_session(root_session_id)
        if root is None:
            return []
        tree = [root]
        queue = [root_session_id]
        while queue:
            pid = queue.pop(0)
            children = await self.list_child_sessions(pid)
            for c in children:
                tree.append(c)
                queue.append(c.session_id)
        return tree

    async def cancel_session_tree(self, root_session_id):
        tree = await self.get_session_tree(root_session_id)
        cancelled = []
        for s in tree:
            if s.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
                s.status = SessionStatus.COMPLETED
                await self.update_session(s)
                cancelled.append(s.session_id)
        return cancelled

    async def add_participant(self, participant):
        self.participants.setdefault(participant.session_id, [])
        self.participants[participant.session_id] = [
            p for p in self.participants[participant.session_id]
            if p.user_id != participant.user_id
        ]
        self.participants[participant.session_id].append(participant)

    async def remove_participant(self, session_id, user_id):
        parts = self.participants.get(session_id, [])
        for p in parts:
            role_val = p.role.value if hasattr(p.role, 'value') else p.role
            if p.user_id == user_id:
                if role_val == 'owner':
                    return False
                from datetime import datetime, timezone
                p.left_at = datetime.now(timezone.utc).isoformat()
                return True
        return False

    async def get_participant(self, session_id, user_id):
        for p in self.participants.get(session_id, []):
            if p.user_id == user_id and p.left_at is None:
                return p
        return None

    async def list_participants(self, session_id, *, include_left=False):
        parts = self.participants.get(session_id, [])
        if include_left:
            return parts
        return [p for p in parts if p.left_at is None]


# --- Auth stub ---

@dataclass
class FakeAuthContext:
    user_id: str = "user-A"
    scopes: list = None

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []

    def has_scope(self, scope: str) -> bool:
        if "*" in self.scopes:
            return True
        return scope in self.scopes


class AuthDenied(Exception):
    """Raised when scope is missing."""
    pass


def make_auth_provider(user_id: str, granted_scopes: List[str]):
    """Return an auth_provider callable for build_agent_router."""
    def _provider(request, scope):
        ctx = FakeAuthContext(user_id=user_id, scopes=granted_scopes)
        if not ctx.has_scope(scope):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")
        return ctx
    return _provider


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture()
def store():
    return InMemorySessionStore()


@pytest.fixture()
def tool_registry():
    reg = BlockRegistry()
    reg.register(
        "stub_echo", StubBlock,
        description="Echoes input",
        input_schema=StubBlock.input_schema,
        output_schema=StubBlock.output_schema,
    )
    perms = ToolPermissionConfig({"defaults": {"requires_confirmation": False}, "tools": {}})
    return ToolRegistry(reg, permissions=perms)


@pytest.fixture()
def action_router():
    return FakeActionRouter()


@pytest.fixture()
def llm_service():
    return FakeLLMService()


def _build_app(store, tool_registry, action_router, llm_service, user_id="user-A", scopes=None):
    """Helper: build a FastAPI app with the agent router."""
    if scopes is None:
        scopes = ["agent:sessions", "agent:tools:read", "agent:tools:execute", "agent:persona:write"]
    app = FastAPI()
    router = build_agent_router(
        session_store=store,
        tool_registry=tool_registry,
        action_router=action_router,
        llm_service=llm_service,
        auth_provider=make_auth_provider(user_id, scopes),
    )
    app.include_router(router)
    return app


@pytest.fixture()
def client(store, tool_registry, action_router, llm_service):
    app = _build_app(store, tool_registry, action_router, llm_service)
    return TestClient(app)


# ===================================================================
# Tests — Create session
# ===================================================================

class TestCreateSession:
    def test_create_session_success(self, client):
        resp = client.post("/v1/agent/sessions", json={"persona_id": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["status"] == "active"
        assert data["persona_id"] == "test"

    def test_create_session_defaults(self, client):
        resp = client.post("/v1/agent/sessions", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona_id"] == "seed"

    def test_create_session_missing_scope(self, store, tool_registry, action_router, llm_service):
        app = _build_app(store, tool_registry, action_router, llm_service, scopes=[])
        c = TestClient(app)
        resp = c.post("/v1/agent/sessions", json={})
        assert resp.status_code == 403


# ===================================================================
# Tests — Send message
# ===================================================================

class TestSendMessage:
    def test_send_message_success(self, client, store):
        # Create a session first
        create_resp = client.post("/v1/agent/sessions", json={"tool_scopes": ["stub_echo"]})
        sid = create_resp.json()["session_id"]

        resp = client.post(f"/v1/agent/sessions/{sid}/messages", json={"message": "Hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["text"], str)
        assert "budget_snapshot" in data

    def test_send_message_session_not_found(self, client):
        resp = client.post("/v1/agent/sessions/nonexistent/messages", json={"message": "Hello"})
        assert resp.status_code == 404

    def test_send_message_wrong_user(self, store, tool_registry, action_router, llm_service):
        """User B cannot send a message to user A's session."""
        # Create session as user A
        app_a = _build_app(store, tool_registry, action_router, llm_service, user_id="user-A")
        c_a = TestClient(app_a)
        create_resp = c_a.post("/v1/agent/sessions", json={})
        sid = create_resp.json()["session_id"]

        # Try to message as user B
        app_b = _build_app(store, tool_registry, action_router, llm_service, user_id="user-B")
        c_b = TestClient(app_b)
        resp = c_b.post(f"/v1/agent/sessions/{sid}/messages", json={"message": "Hello"})
        assert resp.status_code == 403


# ===================================================================
# Tests — Get session
# ===================================================================

class TestGetSession:
    def test_get_session_success(self, client):
        create_resp = client.post("/v1/agent/sessions", json={})
        sid = create_resp.json()["session_id"]

        resp = client.get(f"/v1/agent/sessions/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == sid
        assert data["status"] == "active"
        assert isinstance(data["messages"], list)

    def test_get_session_not_found(self, client):
        resp = client.get("/v1/agent/sessions/nonexistent")
        assert resp.status_code == 404

    def test_get_session_isolation(self, store, tool_registry, action_router, llm_service):
        """User B cannot read user A's session."""
        app_a = _build_app(store, tool_registry, action_router, llm_service, user_id="user-A")
        c_a = TestClient(app_a)
        create_resp = c_a.post("/v1/agent/sessions", json={})
        sid = create_resp.json()["session_id"]

        app_b = _build_app(store, tool_registry, action_router, llm_service, user_id="user-B")
        c_b = TestClient(app_b)
        resp = c_b.get(f"/v1/agent/sessions/{sid}")
        assert resp.status_code == 403


# ===================================================================
# Tests — Update persona
# ===================================================================

class TestUpdatePersona:
    def test_update_persona_success(self, client):
        create_resp = client.post("/v1/agent/sessions", json={})
        sid = create_resp.json()["session_id"]

        resp = client.post(f"/v1/agent/sessions/{sid}/persona", json={"persona_id": "chef", "system_prompt": "You are a chef."})
        assert resp.status_code == 200
        data = resp.json()
        assert data["persona_id"] == "chef"
        assert data["persona_overrides"]["system_prompt"] == "You are a chef."

    def test_update_persona_wrong_scope(self, store, tool_registry, action_router, llm_service):
        """Agent:persona:write scope required."""
        app = _build_app(store, tool_registry, action_router, llm_service, scopes=["agent:sessions"])
        c = TestClient(app)
        create_resp = c.post("/v1/agent/sessions", json={})
        sid = create_resp.json()["session_id"]

        resp = c.post(f"/v1/agent/sessions/{sid}/persona", json={"persona_id": "chef"})
        assert resp.status_code == 403


# ===================================================================
# Tests — Delete session
# ===================================================================

class TestDeleteSession:
    def test_delete_session_success(self, client):
        create_resp = client.post("/v1/agent/sessions", json={})
        sid = create_resp.json()["session_id"]

        resp = client.delete(f"/v1/agent/sessions/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    def test_delete_session_not_found(self, client):
        resp = client.delete("/v1/agent/sessions/nonexistent")
        assert resp.status_code == 404


# ===================================================================
# Tests — List tools
# ===================================================================

class TestListTools:
    def test_list_tools_success(self, client):
        resp = client.get("/v1/agent/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["tools"], list)
        assert len(data["tools"]) >= 1
        # OpenAI function-calling manifest format
        assert data["tools"][0]["function"]["name"] == "stub_echo"

    def test_list_tools_wrong_scope(self, store, tool_registry, action_router, llm_service):
        app = _build_app(store, tool_registry, action_router, llm_service, scopes=["agent:sessions"])
        c = TestClient(app)
        resp = c.get("/v1/agent/tools")
        assert resp.status_code == 403


# ===================================================================
# Tests — Full lifecycle
# ===================================================================

class TestLifecycle:
    def test_create_message_get_delete(self, client):
        """Full lifecycle: create → message → get → delete."""
        # Create
        r1 = client.post("/v1/agent/sessions", json={"tool_scopes": ["stub_echo"]})
        assert r1.status_code == 200
        sid = r1.json()["session_id"]

        # Message
        r2 = client.post(f"/v1/agent/sessions/{sid}/messages", json={"message": "Hello"})
        assert r2.status_code == 200
        assert r2.json()["text"]

        # Get
        r3 = client.get(f"/v1/agent/sessions/{sid}")
        assert r3.status_code == 200
        assert r3.json()["status"] == "active"
        assert len(r3.json()["messages"]) >= 1

        # Delete
        r4 = client.delete(f"/v1/agent/sessions/{sid}")
        assert r4.status_code == 200
        assert r4.json()["status"] == "completed"
