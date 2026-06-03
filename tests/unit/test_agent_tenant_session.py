"""Tests for tenant-aware agent session creation (P0-36).

Verifies:
1. AgentSessionData has tenant_id and project_id fields
2. to_row() / from_row() serialize/deserialize tenant fields
3. DB schema includes tenant columns
4. Session store persists tenant fields
5. API accepts and returns tenant_id / project_id
"""

from __future__ import annotations

import json
from dataclasses import fields as dc_fields
from typing import Any, Dict
from unittest import mock

import pytest

from app.core.agent.models import AgentSessionData, SessionStatus


# ---------------------------------------------------------------------------
# AgentSessionData model
# ---------------------------------------------------------------------------


class TestAgentSessionDataTenantFields:
    def test_has_tenant_id_field(self):
        names = {f.name for f in dc_fields(AgentSessionData)}
        assert "tenant_id" in names
        assert "project_id" in names

    def test_defaults_to_none(self):
        s = AgentSessionData(user_id="u1")
        assert s.tenant_id is None
        assert s.project_id is None

    def test_set_tenant_and_project(self):
        s = AgentSessionData(
            user_id="u1",
            tenant_id="t1",
            project_id="p1",
        )
        assert s.tenant_id == "t1"
        assert s.project_id == "p1"

    def test_to_row_includes_tenant_fields(self):
        s = AgentSessionData(user_id="u1", tenant_id="t1", project_id="p1")
        row = s.to_row()
        # tenant_id and project_id are the last two elements
        assert row[-2] == "t1"
        assert row[-1] == "p1"

    def test_to_row_none_tenant(self):
        s = AgentSessionData(user_id="u1")
        row = s.to_row()
        assert row[-2] is None
        assert row[-1] is None

    def test_from_row_tuple(self):
        s = AgentSessionData(user_id="u1", tenant_id="t2", project_id="p2")
        row = s.to_row()
        restored = AgentSessionData.from_row(row)
        assert restored.tenant_id == "t2"
        assert restored.project_id == "p2"

    def test_from_row_tuple_short(self):
        """Backward compat: shorter rows default tenant fields to None."""
        row = (
            "sid", "uid", "seed", "{}", "{}", "[]", "[]",
            "active", "2026-01-01", "2026-01-01", None,
        )
        restored = AgentSessionData.from_row(row)
        assert restored.tenant_id is None
        assert restored.project_id is None

    def test_from_row_dict(self):
        """Row-as-dict (sqlite3.Row) includes tenant fields."""

        class FakeRow:
            def __init__(self, data: dict):
                self._data = data
                self.keys = lambda: list(data.keys())

            def __getitem__(self, key):
                return self._data[key]

        data = {
            "session_id": "s1",
            "user_id": "u1",
            "persona_id": "seed",
            "persona_overrides": "{}",
            "budget_config": "{}",
            "tool_scopes": "[]",
            "pending_confirmations": "[]",
            "status": "active",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
            "parent_session_id": None,
            "tenant_id": "t3",
            "project_id": "p3",
        }
        row = FakeRow(data)
        # Ensure hasattr(row, "keys") is True
        assert hasattr(row, "keys")
        restored = AgentSessionData.from_row(row)
        assert restored.tenant_id == "t3"
        assert restored.project_id == "p3"

    def test_from_row_dict_missing_tenant(self):
        """Backward compat: dict rows without tenant fields default to None."""

        class FakeRow:
            def __init__(self, data: dict):
                self._data = data
                self.keys = lambda: list(data.keys())

            def __getitem__(self, key):
                return self._data[key]

        data = {
            "session_id": "s1",
            "user_id": "u1",
            "persona_id": "seed",
            "persona_overrides": "{}",
            "budget_config": "{}",
            "tool_scopes": "[]",
            "pending_confirmations": "[]",
            "status": "active",
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
            "parent_session_id": None,
        }
        row = FakeRow(data)
        restored = AgentSessionData.from_row(row)
        assert restored.tenant_id is None
        assert restored.project_id is None


# ---------------------------------------------------------------------------
# DB Schema
# ---------------------------------------------------------------------------


class TestDBSchema:
    def test_schema_has_tenant_columns(self):
        """The CREATE TABLE statement includes tenant_id and project_id."""
        from app.infrastructure.db import sqlite as sqlite_mod

        schema = sqlite_mod._SCHEMA_SQL
        assert "tenant_id TEXT" in schema
        assert "project_id TEXT" in schema

    def test_schema_has_tenant_index(self):
        from app.infrastructure.db import sqlite as sqlite_mod

        schema = sqlite_mod._SCHEMA_SQL
        assert "idx_agent_sessions_tenant" in schema


# ---------------------------------------------------------------------------
# Session Store
# ---------------------------------------------------------------------------


class TestSessionStoreTenantPersistence:
    def test_create_session_sql_includes_tenant_columns(self):
        """CREATE SQL mentions tenant_id and project_id."""
        from app.core.agent.session_store import AgentSessionStore
        import inspect
        source = inspect.getsource(AgentSessionStore.create_session)
        assert "tenant_id" in source
        assert "project_id" in source


# ---------------------------------------------------------------------------
# API — CreateSessionRequest / CreateSessionResponse
# ---------------------------------------------------------------------------


class TestAPISchemas:
    def test_create_request_has_tenant_fields(self):
        from app.api.agent_routes import CreateSessionRequest

        req = CreateSessionRequest(tenant_id="t1", project_id="p1")
        assert req.tenant_id == "t1"
        assert req.project_id == "p1"

    def test_create_request_defaults_none(self):
        from app.api.agent_routes import CreateSessionRequest

        req = CreateSessionRequest()
        assert req.tenant_id is None
        assert req.project_id is None

    def test_create_response_has_tenant_fields(self):
        from app.api.agent_routes import CreateSessionResponse

        resp = CreateSessionResponse(
            session_id="s1",
            status="active",
            persona_id="seed",
            tenant_id="t1",
            project_id="p1",
        )
        assert resp.tenant_id == "t1"
        assert resp.project_id == "p1"

    def test_create_response_defaults_none(self):
        from app.api.agent_routes import CreateSessionResponse

        resp = CreateSessionResponse(
            session_id="s1",
            status="active",
            persona_id="seed",
        )
        assert resp.tenant_id is None
        assert resp.project_id is None
