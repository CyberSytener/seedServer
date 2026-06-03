"""Tests for P0-22 — Sub-agent orchestration API endpoints.

Covers:
- GET /v1/agent/sessions/{id} includes ``children`` and ``parent_session_id``
- GET /v1/agent/sessions/{id}/tree returns full hierarchy
- DELETE /v1/agent/sessions/{id} cascades cancel to descendants
- Scope enforcement (403) and ownership isolation
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


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

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
    async def agenerate_with_metadata(self, *, prompt, system_instruction="", **kw):
        return FakeGenerationResult()


class FakeActionRouter:
    def execute_action(self, action, **kw):
        from app.models.realtime.actions import ActionResult, ActionStatus
        return ActionResult(
            action_id=action.id, action_name=action.name,
            status=ActionStatus.SUCCESS, result={"ok": True},
        )


class InMemorySessionStore:
    """Session store supporting parent/child queries for orchestration tests."""

    def __init__(self):
        self.sessions: Dict[str, AgentSessionData] = {}
        self.messages: Dict[str, List[AgentSessionMessage]] = {}
        self.participants: Dict[str, list] = {}

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


@dataclass
class FakeAuthContext:
    user_id: str = "user-A"
    scopes: list = None

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []

    def has_scope(self, scope):
        return "*" in self.scopes or scope in self.scopes


def make_auth_provider(user_id: str, granted_scopes: List[str]):
    def _provider(request, scope):
        ctx = FakeAuthContext(user_id=user_id, scopes=granted_scopes)
        if not ctx.has_scope(scope):
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")
        return ctx
    return _provider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def client(store, tool_registry):
    """FastAPI TestClient wired to build_agent_router with user-A having full scopes."""
    router = build_agent_router(
        session_store=store,
        tool_registry=tool_registry,
        action_router=FakeActionRouter(),
        llm_service=FakeLLMService(),
        auth_provider=make_auth_provider("user-A", ["*"]),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _seed_tree(store: InMemorySessionStore) -> Dict[str, AgentSessionData]:
    """Create a 3-node tree: root -> child-1, child-1 -> grandchild-1."""
    import asyncio

    root = AgentSessionData(session_id="root", user_id="user-A", tool_scopes=["a"])
    child = AgentSessionData(
        session_id="child-1", user_id="user-A",
        parent_session_id="root", tool_scopes=["a"],
    )
    grandchild = AgentSessionData(
        session_id="gc-1", user_id="user-A",
        parent_session_id="child-1", tool_scopes=["a"],
    )

    loop = asyncio.new_event_loop()
    for s in [root, child, grandchild]:
        loop.run_until_complete(store.create_session(s))
    loop.close()
    return {"root": root, "child": child, "grandchild": grandchild}


# ---------------------------------------------------------------------------
# Tests: GET /sessions/{id} includes children + parent_session_id
# ---------------------------------------------------------------------------

class TestGetSessionWithChildren:

    def test_parent_session_id_in_response(self, store, tool_registry):
        sessions = _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/child-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_session_id"] == "root"

    def test_children_list_in_response(self, store, tool_registry):
        sessions = _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/root")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["children"]) == 1
        assert body["children"][0]["session_id"] == "child-1"

    def test_leaf_has_empty_children(self, store, tool_registry):
        sessions = _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/gc-1")
        assert resp.status_code == 200
        assert resp.json()["children"] == []

    def test_root_has_null_parent(self, store, tool_registry):
        sessions = _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/root")
        assert resp.json()["parent_session_id"] is None


# ---------------------------------------------------------------------------
# Tests: GET /sessions/{id}/tree
# ---------------------------------------------------------------------------

class TestSessionTree:

    def test_tree_returns_full_hierarchy(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/root/tree")
        assert resp.status_code == 200
        body = resp.json()
        assert body["root_session_id"] == "root"
        ids = {n["session_id"] for n in body["nodes"]}
        assert ids == {"root", "child-1", "gc-1"}

    def test_tree_nodes_have_parent_links(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/root/tree")
        nodes = {n["session_id"]: n for n in resp.json()["nodes"]}
        assert nodes["root"]["parent_session_id"] is None
        assert nodes["child-1"]["parent_session_id"] == "root"
        assert nodes["gc-1"]["parent_session_id"] == "child-1"

    def test_tree_404_nonexistent(self, client):
        resp = client.get("/v1/agent/sessions/nope/tree")
        assert resp.status_code == 404

    def test_tree_leaf_returns_single_node(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/gc-1/tree")
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 1
        assert resp.json()["nodes"][0]["session_id"] == "gc-1"


# ---------------------------------------------------------------------------
# Tests: DELETE cascades cancel to descendants
# ---------------------------------------------------------------------------

class TestCascadeCancel:

    def test_delete_cancels_entire_tree(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.delete("/v1/agent/sessions/root")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["cancelled_ids"]) == {"root", "child-1", "gc-1"}

        # All sessions should be completed
        import asyncio
        loop = asyncio.new_event_loop()
        for sid in ["root", "child-1", "gc-1"]:
            s = loop.run_until_complete(store.get_session(sid))
            assert s.status == SessionStatus.COMPLETED
        loop.close()

    def test_delete_child_cancels_subtree_only(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.delete("/v1/agent/sessions/child-1")
        assert resp.status_code == 200
        body = resp.json()
        assert "child-1" in body["cancelled_ids"]
        assert "gc-1" in body["cancelled_ids"]
        assert "root" not in body["cancelled_ids"]

    def test_delete_404_nonexistent(self, client):
        resp = client.delete("/v1/agent/sessions/nope")
        assert resp.status_code == 404

    def test_delete_already_completed_not_in_cancelled(self, store, tool_registry):
        """Already-completed sessions should not appear in cancelled_ids."""
        _seed_tree(store)
        # Mark grandchild as already completed
        import asyncio
        loop = asyncio.new_event_loop()
        gc = loop.run_until_complete(store.get_session("gc-1"))
        gc.status = SessionStatus.COMPLETED
        loop.run_until_complete(store.update_session(gc))
        loop.close()

        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.delete("/v1/agent/sessions/root")
        body = resp.json()
        assert "gc-1" not in body["cancelled_ids"]
        assert "root" in body["cancelled_ids"]


# ---------------------------------------------------------------------------
# Tests: ownership / scope enforcement
# ---------------------------------------------------------------------------

class TestOwnershipEnforcement:

    def test_tree_forbidden_for_other_user(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-B", ["*"]),
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/root/tree")
        assert resp.status_code == 403

    def test_scope_missing_returns_403(self, store, tool_registry):
        _seed_tree(store)
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_registry,
            action_router=FakeActionRouter(),
            llm_service=FakeLLMService(),
            auth_provider=make_auth_provider("user-A", []),  # no scopes
        )
        app = FastAPI()
        app.include_router(router)
        tc = TestClient(app)

        resp = tc.get("/v1/agent/sessions/root/tree")
        assert resp.status_code == 403
