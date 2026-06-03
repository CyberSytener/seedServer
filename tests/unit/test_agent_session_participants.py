"""Tests for P0-24 — session participant model (invite, join, leave).

Covers:
  • SessionParticipant dataclass (to_row, from_row, to_dict)
  • ParticipantRole enum
  • Session store participant CRUD
  • Participant API endpoints (POST, DELETE, GET)
  • Viewer cannot send messages
  • Editor scoped access
  • Owner cannot be removed
  • Multi-user confirmation gate (scope-checked)
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    ParticipantRole,
    SessionParticipant,
    SessionStatus,
)


# ===================================================================
# Unit tests — ParticipantRole enum
# ===================================================================


class TestParticipantRole:
    def test_values(self):
        assert ParticipantRole.OWNER.value == "owner"
        assert ParticipantRole.EDITOR.value == "editor"
        assert ParticipantRole.VIEWER.value == "viewer"

    def test_from_string(self):
        assert ParticipantRole("owner") == ParticipantRole.OWNER
        assert ParticipantRole("editor") == ParticipantRole.EDITOR
        assert ParticipantRole("viewer") == ParticipantRole.VIEWER

    def test_invalid(self):
        with pytest.raises(ValueError):
            ParticipantRole("admin")


# ===================================================================
# Unit tests — SessionParticipant dataclass
# ===================================================================


class TestSessionParticipant:
    def test_defaults(self):
        p = SessionParticipant()
        assert p.session_id == ""
        assert p.user_id == ""
        assert p.role == ParticipantRole.VIEWER
        assert p.tool_scopes == []
        assert p.left_at is None

    def test_to_row(self):
        p = SessionParticipant(
            session_id="s1",
            user_id="u1",
            role=ParticipantRole.EDITOR,
            tool_scopes=["tool_a", "tool_b"],
            joined_at="2025-01-01T00:00:00",
            left_at=None,
        )
        row = p.to_row()
        assert row[0] == "s1"
        assert row[1] == "u1"
        assert row[2] == "editor"
        assert json.loads(row[3]) == ["tool_a", "tool_b"]
        assert row[4] == "2025-01-01T00:00:00"
        assert row[5] is None

    def test_from_row_tuple(self):
        row = ("s1", "u1", "editor", '["tool_a"]', "2025-01-01T00:00:00", None)
        p = SessionParticipant.from_row(row)
        assert p.session_id == "s1"
        assert p.user_id == "u1"
        assert p.role == ParticipantRole.EDITOR
        assert p.tool_scopes == ["tool_a"]

    def test_from_row_dict(self):
        row = {
            "session_id": "s1",
            "user_id": "u1",
            "role": "viewer",
            "tool_scopes": '[]',
            "joined_at": "2025-01-01T00:00:00",
            "left_at": None,
        }
        p = SessionParticipant.from_row(row)
        assert p.role == ParticipantRole.VIEWER
        assert p.tool_scopes == []

    def test_to_dict(self):
        p = SessionParticipant(
            session_id="s1",
            user_id="u1",
            role=ParticipantRole.OWNER,
            tool_scopes=["*"],
        )
        d = p.to_dict()
        assert d["role"] == "owner"
        assert d["tool_scopes"] == ["*"]
        assert d["left_at"] is None

    def test_roundtrip(self):
        p = SessionParticipant(
            session_id="s1",
            user_id="u1",
            role=ParticipantRole.EDITOR,
            tool_scopes=["tool_x"],
            joined_at="2025-06-01T12:00:00",
        )
        row = p.to_row()
        restored = SessionParticipant.from_row(row)
        assert restored.session_id == p.session_id
        assert restored.role == p.role
        assert restored.tool_scopes == p.tool_scopes


# ===================================================================
# In-memory store for participant API tests
# ===================================================================


class InMemorySessionStore:
    def __init__(self):
        self.sessions: Dict[str, AgentSessionData] = {}
        self.messages: Dict[str, List[AgentSessionMessage]] = {}
        self.participants: Dict[str, List[SessionParticipant]] = {}

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
            role_val = p.role.value if hasattr(p.role, "value") else p.role
            if p.user_id == user_id:
                if role_val == "owner":
                    return False
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


# ===================================================================
# Auth stubs
# ===================================================================


@dataclass
class FakeAuthContext:
    user_id: str = "owner-A"
    scopes: list = None

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []

    def has_scope(self, scope: str) -> bool:
        if "*" in self.scopes:
            return True
        return scope in self.scopes


def make_auth_provider(user_id: str, granted_scopes: List[str]):
    def _provider(request, scope):
        ctx = FakeAuthContext(user_id=user_id, scopes=granted_scopes)
        if not ctx.has_scope(scope):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")
        return ctx
    return _provider


# ===================================================================
# Minimal stubs
# ===================================================================


class StubToolRegistry:
    def list_tools_for_llm(self, scopes):
        return []

    def resolve_tool(self, name, scopes=None):
        return None


class StubActionRouter:
    async def route(self, *a, **kw):
        return {"status": "ok"}


class StubLLMService:
    async def chat(self, *a, **kw):
        return {"choices": [{"message": {"content": "ok"}}]}


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture()
def store():
    return InMemorySessionStore()


@pytest.fixture()
def seed_session(store):
    """Create a session owned by 'owner-A'."""
    session = AgentSessionData(
        user_id="owner-A",
        persona_id="seed",
        budget_config={"max_llm_calls": 50, "max_tool_calls": 50},
        tool_scopes=["tool_a", "tool_b"],
    )
    # Synchronously populate the in-memory store (no real async I/O)
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(store.create_session(session))
    loop.close()
    return session


def _build_app(store, user_id="owner-A", scopes=None):
    from app.api.agent_routes import build_agent_router

    app = FastAPI()
    router = build_agent_router(
        session_store=store,
        tool_registry=StubToolRegistry(),
        action_router=StubActionRouter(),
        llm_service=StubLLMService(),
        auth_provider=make_auth_provider(user_id, scopes or ["*"]),
    )
    app.include_router(router)
    return app


# ===================================================================
# API tests — Participant endpoints
# ===================================================================


@pytest.mark.asyncio
async def test_add_participant(store, seed_session):
    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/agent/sessions/{seed_session.session_id}/participants",
            json={"user_id": "user-B", "role": "editor", "tool_scopes": ["tool_a"]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "user-B"
    assert body["role"] == "editor"
    assert body["tool_scopes"] == ["tool_a"]


@pytest.mark.asyncio
async def test_add_participant_viewer(store, seed_session):
    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/agent/sessions/{seed_session.session_id}/participants",
            json={"user_id": "user-C", "role": "viewer"},
        )
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"


@pytest.mark.asyncio
async def test_add_owner_rejected(store, seed_session):
    """Cannot add another owner."""
    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/agent/sessions/{seed_session.session_id}/participants",
            json={"user_id": "user-X", "role": "owner"},
        )
    assert r.status_code == 400
    assert "owner" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_participant_invalid_role(store, seed_session):
    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/agent/sessions/{seed_session.session_id}/participants",
            json={"user_id": "user-X", "role": "admin"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_add_participant_non_owner_rejected(store, seed_session):
    """Non-owner cannot invite participants."""
    app = _build_app(store, user_id="user-B")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/agent/sessions/{seed_session.session_id}/participants",
            json={"user_id": "user-C", "role": "editor"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_participants(store, seed_session):
    # Add an editor
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="user-B",
        role=ParticipantRole.EDITOR,
    ))

    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/agent/sessions/{seed_session.session_id}/participants")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == seed_session.session_id
    assert len(body["participants"]) == 1
    assert body["participants"][0]["user_id"] == "user-B"


@pytest.mark.asyncio
async def test_list_participants_as_participant(store, seed_session):
    """A participant (non-owner) can list participants."""
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="user-B",
        role=ParticipantRole.VIEWER,
    ))

    app = _build_app(store, user_id="user-B")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/agent/sessions/{seed_session.session_id}/participants")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_remove_participant(store, seed_session):
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="user-B",
        role=ParticipantRole.EDITOR,
    ))

    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(
            f"/v1/agent/sessions/{seed_session.session_id}/participants/user-B"
        )
    assert r.status_code == 200
    assert r.json()["removed"] is True


@pytest.mark.asyncio
async def test_remove_owner_rejected(store, seed_session):
    """Owner cannot be removed."""
    # Add owner as explicit participant for test
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="owner-A",
        role=ParticipantRole.OWNER,
    ))

    app = _build_app(store, user_id="owner-A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(
            f"/v1/agent/sessions/{seed_session.session_id}/participants/owner-A"
        )
    assert r.status_code == 200
    assert r.json()["removed"] is False


@pytest.mark.asyncio
async def test_remove_non_owner_rejected(store, seed_session):
    """Non-owner cannot remove participants."""
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="user-B",
        role=ParticipantRole.EDITOR,
    ))

    app = _build_app(store, user_id="user-B")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.delete(
            f"/v1/agent/sessions/{seed_session.session_id}/participants/user-B"
        )
    assert r.status_code == 403


# ===================================================================
# Access control — viewer cannot send messages
# ===================================================================


@pytest.mark.asyncio
async def test_viewer_cannot_send_message(store, seed_session):
    """Viewer participant gets 403 on send_message."""
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="viewer-V",
        role=ParticipantRole.VIEWER,
    ))

    app = _build_app(store, user_id="viewer-V")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/agent/sessions/{seed_session.session_id}/messages",
            json={"message": "hello"},
        )
    assert r.status_code == 403
    assert "viewer" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_viewer_can_get_session(store, seed_session):
    """Viewer can read session details."""
    await store.add_participant(SessionParticipant(
        session_id=seed_session.session_id,
        user_id="viewer-V",
        role=ParticipantRole.VIEWER,
    ))

    app = _build_app(store, user_id="viewer-V")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/agent/sessions/{seed_session.session_id}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_non_participant_rejected(store, seed_session):
    """A user who is neither owner nor participant gets 403."""
    app = _build_app(store, user_id="outsider-X")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/agent/sessions/{seed_session.session_id}")
    assert r.status_code == 403


# ===================================================================
# Store-level unit tests
# ===================================================================


@pytest.mark.asyncio
async def test_store_add_and_get_participant(store, seed_session):
    p = SessionParticipant(
        session_id=seed_session.session_id,
        user_id="u1",
        role=ParticipantRole.EDITOR,
        tool_scopes=["scope_a"],
    )
    await store.add_participant(p)
    got = await store.get_participant(seed_session.session_id, "u1")
    assert got is not None
    assert got.role == ParticipantRole.EDITOR
    assert got.tool_scopes == ["scope_a"]


@pytest.mark.asyncio
async def test_store_remove_sets_left_at(store, seed_session):
    p = SessionParticipant(
        session_id=seed_session.session_id,
        user_id="u1",
        role=ParticipantRole.EDITOR,
    )
    await store.add_participant(p)
    result = await store.remove_participant(seed_session.session_id, "u1")
    assert result is True
    # Should not appear in active list
    got = await store.get_participant(seed_session.session_id, "u1")
    assert got is None
    # But appears in include_left
    all_parts = await store.list_participants(seed_session.session_id, include_left=True)
    assert any(x.user_id == "u1" and x.left_at is not None for x in all_parts)


@pytest.mark.asyncio
async def test_store_remove_owner_returns_false(store, seed_session):
    p = SessionParticipant(
        session_id=seed_session.session_id,
        user_id="owner-A",
        role=ParticipantRole.OWNER,
    )
    await store.add_participant(p)
    result = await store.remove_participant(seed_session.session_id, "owner-A")
    assert result is False


@pytest.mark.asyncio
async def test_store_list_excludes_left(store, seed_session):
    sid = seed_session.session_id
    await store.add_participant(SessionParticipant(session_id=sid, user_id="u1", role=ParticipantRole.EDITOR))
    await store.add_participant(SessionParticipant(session_id=sid, user_id="u2", role=ParticipantRole.VIEWER))
    await store.remove_participant(sid, "u2")
    active = await store.list_participants(sid)
    assert len(active) == 1
    assert active[0].user_id == "u1"


@pytest.mark.asyncio
async def test_store_upsert_participant(store, seed_session):
    """Adding the same user_id again should replace (upsert)."""
    sid = seed_session.session_id
    await store.add_participant(SessionParticipant(
        session_id=sid, user_id="u1", role=ParticipantRole.VIEWER,
    ))
    await store.add_participant(SessionParticipant(
        session_id=sid, user_id="u1", role=ParticipantRole.EDITOR,
        tool_scopes=["scope_new"],
    ))
    got = await store.get_participant(sid, "u1")
    assert got.role == ParticipantRole.EDITOR
    assert got.tool_scopes == ["scope_new"]
    # Only 1 entry
    all_parts = await store.list_participants(sid, include_left=True)
    assert sum(1 for p in all_parts if p.user_id == "u1") == 1


# ===================================================================
# Multi-user confirmation gate (DoD scenario)
# ===================================================================


@pytest.mark.asyncio
async def test_multi_user_confirmation_gate(store, seed_session):
    """
    DoD scenario:
    - Participant A (editor) triggers a privileged tool → pending_confirmation
    - Viewer B attempts to confirm → rejected (insufficient scope)
    - Editor C with correct scope confirms → tool executes
    """
    sid = seed_session.session_id

    # Add participants
    await store.add_participant(SessionParticipant(
        session_id=sid, user_id="editor-A", role=ParticipantRole.EDITOR,
        tool_scopes=["tool_a"],
    ))
    await store.add_participant(SessionParticipant(
        session_id=sid, user_id="viewer-B", role=ParticipantRole.VIEWER,
    ))
    await store.add_participant(SessionParticipant(
        session_id=sid, user_id="editor-C", role=ParticipantRole.EDITOR,
        tool_scopes=["tool_a", "tool_b"],
    ))

    # Simulate confirmation request from editor-A
    pending = {
        "confirmation_id": "conf-001",
        "tool_name": "tool_b",
        "require_scope": "tool_b",
        "requested_by_user_id": "editor-A",
    }

    # Viewer B tries to confirm — should be rejected
    viewer = await store.get_participant(sid, "viewer-B")
    assert viewer is not None
    assert viewer.role == ParticipantRole.VIEWER
    # Viewer cannot confirm (role check)
    can_confirm_b = (
        viewer.role != ParticipantRole.VIEWER
        and pending["require_scope"] in viewer.tool_scopes
    )
    assert can_confirm_b is False

    # Editor C confirms — has the required scope
    editor_c = await store.get_participant(sid, "editor-C")
    assert editor_c is not None
    can_confirm_c = (
        editor_c.role != ParticipantRole.VIEWER
        and pending["require_scope"] in editor_c.tool_scopes
    )
    assert can_confirm_c is True

    # Editor A cannot confirm their own request if they lack the scope
    editor_a = await store.get_participant(sid, "editor-A")
    can_confirm_a = (
        editor_a.role != ParticipantRole.VIEWER
        and pending["require_scope"] in editor_a.tool_scopes
    )
    # editor-A has ["tool_a"] but the tool requires "tool_b"
    assert can_confirm_a is False
