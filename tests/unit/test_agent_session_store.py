"""Tests for AgentSessionStore — Phase 7 P7-02.

Validates:
- agent_sessions table CRUD (create, read, update, delete)
- agent_session_messages append + ordered retrieval
- Round-trip JSON serialization for persona_overrides, budget_config, tool_scopes
- AsyncSqliteDB is used (no sync blocking)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session_store import AgentSessionStore
from app.infrastructure.db.async_sqlite import AsyncSqliteDB
from app.infrastructure.db.sqlite import DB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "test_agent.db")


@pytest.fixture()
def sync_db(db_path):
    db = DB(db_path)
    db.init_schema()
    # Ensure user exists for FK
    db.execute(
        "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, datetime('now'))",
        ("test_user", "test@example.com"),
    )
    return db


@pytest.fixture()
def async_db(sync_db):
    return AsyncSqliteDB(sync_db)


@pytest.fixture()
def store(async_db):
    return AgentSessionStore(async_db)


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

class TestAgentSessionCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get_session(self, store):
        session = AgentSessionData(
            session_id="sess-001",
            user_id="test_user",
            persona_id="seed",
            persona_overrides={"display_name": "Nikita"},
            budget_config={"max_total_tokens": 10000, "max_tool_calls": 10},
            tool_scopes=["recipe_generator", "inventory_sync"],
        )
        created = await store.create_session(session)
        assert created.session_id == "sess-001"

        fetched = await store.get_session("sess-001")
        assert fetched is not None
        assert fetched.user_id == "test_user"
        assert fetched.persona_id == "seed"
        assert fetched.persona_overrides == {"display_name": "Nikita"}
        assert fetched.budget_config["max_total_tokens"] == 10000
        assert fetched.tool_scopes == ["recipe_generator", "inventory_sync"]
        assert fetched.status == SessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_none(self, store):
        result = await store.get_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_session(self, store):
        session = AgentSessionData(session_id="sess-002", user_id="test_user")
        await store.create_session(session)

        session.persona_id = "bard_cat"
        session.status = SessionStatus.PAUSED
        session.pending_confirmations = [{"tool": "inventory_sync", "input": {}}]
        await store.update_session(session)

        fetched = await store.get_session("sess-002")
        assert fetched is not None
        assert fetched.persona_id == "bard_cat"
        assert fetched.status == SessionStatus.PAUSED
        assert len(fetched.pending_confirmations) == 1
        assert fetched.pending_confirmations[0]["tool"] == "inventory_sync"

    @pytest.mark.asyncio
    async def test_delete_session(self, store):
        session = AgentSessionData(session_id="sess-003", user_id="test_user")
        await store.create_session(session)
        await store.delete_session("sess-003")
        assert await store.get_session("sess-003") is None

    @pytest.mark.asyncio
    async def test_list_sessions_for_user(self, store):
        for i in range(3):
            await store.create_session(
                AgentSessionData(session_id=f"sess-list-{i}", user_id="test_user")
            )
        sessions = await store.list_sessions_for_user("test_user")
        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_list_sessions_filter_by_status(self, store):
        s1 = AgentSessionData(session_id="s-active", user_id="test_user", status=SessionStatus.ACTIVE)
        s2 = AgentSessionData(session_id="s-done", user_id="test_user", status=SessionStatus.COMPLETED)
        await store.create_session(s1)
        await store.create_session(s2)

        s2.status = SessionStatus.COMPLETED
        await store.update_session(s2)

        active = await store.list_sessions_for_user("test_user", status="active")
        assert len(active) == 1
        assert active[0].session_id == "s-active"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class TestAgentSessionMessages:
    @pytest.mark.asyncio
    async def test_append_and_retrieve_messages(self, store):
        session = AgentSessionData(session_id="sess-msg", user_id="test_user")
        await store.create_session(session)

        msgs = [
            AgentSessionMessage(
                message_id=f"msg-{i}",
                session_id="sess-msg",
                role=MessageRole.USER if i % 2 == 0 else MessageRole.AGENT,
                content=f"message {i}",
                timestamp=f"2026-02-27T10:00:0{i}Z",
            )
            for i in range(5)
        ]
        for m in msgs:
            await store.append_message(m)

        history = await store.get_messages("sess-msg")
        assert len(history) == 5
        # Ordered by timestamp ASC
        assert history[0].content == "message 0"
        assert history[4].content == "message 4"
        assert history[0].role == MessageRole.USER
        assert history[1].role == MessageRole.AGENT

    @pytest.mark.asyncio
    async def test_message_with_tool_fields(self, store):
        session = AgentSessionData(session_id="sess-tool", user_id="test_user")
        await store.create_session(session)

        msg = AgentSessionMessage(
            message_id="msg-tool-1",
            session_id="sess-tool",
            role=MessageRole.TOOL_CALL,
            content=None,
            tool_name="recipe_generator",
            tool_input=json.dumps({"ingredients": ["tomato"]}),
            tool_output=None,
            budget_snapshot=json.dumps({"consumed_tokens": 100}),
        )
        await store.append_message(msg)

        history = await store.get_messages("sess-tool")
        assert len(history) == 1
        assert history[0].role == MessageRole.TOOL_CALL
        assert history[0].tool_name == "recipe_generator"
        assert json.loads(history[0].tool_input)["ingredients"] == ["tomato"]

    @pytest.mark.asyncio
    async def test_message_roles_include_confirmation_request(self, store):
        session = AgentSessionData(session_id="sess-conf", user_id="test_user")
        await store.create_session(session)

        msg = AgentSessionMessage(
            message_id="msg-conf-1",
            session_id="sess-conf",
            role=MessageRole.CONFIRMATION_REQUEST,
            content="Please confirm: run inventory_sync?",
        )
        await store.append_message(msg)

        history = await store.get_messages("sess-conf")
        assert len(history) == 1
        assert history[0].role == MessageRole.CONFIRMATION_REQUEST
