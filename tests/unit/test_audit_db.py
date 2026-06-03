"""Tests for DB-backed audit events (Task 4.4)."""
from __future__ import annotations

import json
import sqlite3
import types
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lightweight in-memory DB that mimics the project's DB interface
# ---------------------------------------------------------------------------
class _MemDB:
    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._conn.execute(sql, params)
        self._conn.commit()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        cur = self._conn.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return row


@pytest.fixture()
def memdb():
    return _MemDB()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_request(app_db=None, path="/test", method="POST"):
    """Return a minimal mock that looks like a Starlette Request."""
    req = MagicMock()
    req.url.path = path
    req.method = method
    if app_db is not None:
        req.app.state.seed.db = app_db
    else:
        req.app.state.seed = None
    return req


def _fake_ctx(user_id="u1", role="developer", auth_type="api_key"):
    ctx = MagicMock()
    ctx.user_id = user_id
    ctx.role = role
    ctx.auth_type = auth_type
    return ctx


# ---------------------------------------------------------------------------
# ensure_audit_events_table
# ---------------------------------------------------------------------------

class TestEnsureAuditEventsTable:
    def test_creates_table(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table

        ensure_audit_events_table(memdb)

        # Table should exist
        row = memdb.fetchone(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        )
        assert row is not None
        assert dict(row)["name"] == "audit_events"

    def test_idempotent(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table

        ensure_audit_events_table(memdb)
        ensure_audit_events_table(memdb)  # should not raise

    def test_creates_indexes(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table

        ensure_audit_events_table(memdb)

        indexes = memdb.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='audit_events'"
        )
        idx_names = {dict(r)["name"] for r in indexes}
        assert "idx_audit_events_user" in idx_names
        assert "idx_audit_events_action" in idx_names


# ---------------------------------------------------------------------------
# _store_audit_event_db
# ---------------------------------------------------------------------------

class TestStoreAuditEventDB:
    def test_insert_success(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table, _store_audit_event_db

        ensure_audit_events_table(memdb)

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "test.action",
            "allowed": True,
            "path": "/api/test",
            "method": "GET",
            "user_id": "u1",
            "role": "admin",
            "auth_type": "jwt",
            "details": {"key": "value"},
        }
        ok = _store_audit_event_db(memdb, payload)
        assert ok is True

        rows = memdb.fetchall("SELECT * FROM audit_events")
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["action"] == "test.action"
        assert row["allowed"] == 1
        assert row["user_id"] == "u1"
        assert json.loads(row["details_json"]) == {"key": "value"}

    def test_insert_fails_no_table(self, memdb: _MemDB):
        from app.core.authz import _store_audit_event_db

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "fail",
            "allowed": False,
        }
        ok = _store_audit_event_db(memdb, payload)
        assert ok is False

    def test_insert_minimal_payload(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table, _store_audit_event_db

        ensure_audit_events_table(memdb)

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": "minimal",
            "allowed": False,
        }
        assert _store_audit_event_db(memdb, payload) is True

        row = dict(memdb.fetchone("SELECT * FROM audit_events"))
        assert row["action"] == "minimal"
        assert row["allowed"] == 0
        assert row["user_id"] is None


# ---------------------------------------------------------------------------
# query_audit_events
# ---------------------------------------------------------------------------

class TestQueryAuditEvents:
    def _seed(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table, _store_audit_event_db

        ensure_audit_events_table(memdb)
        for i in range(5):
            _store_audit_event_db(memdb, {
                "timestamp": f"2025-01-0{i+1}T00:00:00+00:00",
                "action": "test.read" if i % 2 == 0 else "test.write",
                "allowed": True,
                "user_id": "u1" if i < 3 else "u2",
                "details": {"i": i},
            })

    def test_returns_all(self, memdb: _MemDB):
        from app.core.authz import query_audit_events

        self._seed(memdb)
        results = query_audit_events(memdb)
        assert len(results) == 5

    def test_filter_by_user(self, memdb: _MemDB):
        from app.core.authz import query_audit_events

        self._seed(memdb)
        results = query_audit_events(memdb, user_id="u1")
        assert len(results) == 3
        assert all(r["user_id"] == "u1" for r in results)

    def test_filter_by_action(self, memdb: _MemDB):
        from app.core.authz import query_audit_events

        self._seed(memdb)
        results = query_audit_events(memdb, action="test.read")
        assert len(results) == 3  # indices 0, 2, 4

    def test_limit(self, memdb: _MemDB):
        from app.core.authz import query_audit_events

        self._seed(memdb)
        results = query_audit_events(memdb, limit=2)
        assert len(results) == 2

    def test_details_parsed(self, memdb: _MemDB):
        from app.core.authz import query_audit_events

        self._seed(memdb)
        results = query_audit_events(memdb)
        for r in results:
            assert isinstance(r["details"], dict)
            assert "i" in r["details"]


# ---------------------------------------------------------------------------
# audit_auth_event (integration)
# ---------------------------------------------------------------------------

class TestAuditAuthEvent:
    def test_writes_to_db_when_available(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table, audit_auth_event

        ensure_audit_events_table(memdb)

        request = _fake_request(app_db=memdb, path="/v1/runs", method="POST")
        ctx = _fake_ctx(user_id="u42", role="admin")

        audit_auth_event(
            action="runs.create",
            request=request,
            context=ctx,
            allowed=True,
            details={"module": "cv_gen"},
        )

        rows = memdb.fetchall("SELECT * FROM audit_events")
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["action"] == "runs.create"
        assert row["user_id"] == "u42"
        assert row["path"] == "/v1/runs"
        assert json.loads(row["details_json"]) == {"module": "cv_gen"}

    def test_falls_back_to_jsonl_when_no_db(self, tmp_path, monkeypatch):
        from app.core.authz import audit_auth_event

        monkeypatch.chdir(tmp_path)
        request = _fake_request(app_db=None, path="/fallback", method="GET")

        audit_auth_event(
            action="fallback.test",
            request=request,
            context=None,
            allowed=False,
        )

        jsonl = tmp_path / ".seed_artifacts" / "audit" / "auth_events.jsonl"
        assert jsonl.exists()
        lines = [json.loads(ln) for ln in jsonl.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        assert lines[0]["action"] == "fallback.test"
        assert lines[0]["allowed"] is False

    def test_falls_back_to_jsonl_on_db_error(self, tmp_path, monkeypatch):
        """If DB write fails (e.g. table missing), falls back to JSONL."""
        from app.core.authz import audit_auth_event

        monkeypatch.chdir(tmp_path)

        # DB exists but table does NOT
        broken_db = _MemDB()
        request = _fake_request(app_db=broken_db, path="/broken", method="PUT")

        audit_auth_event(
            action="broken.test",
            request=request,
            context=_fake_ctx(),
            allowed=True,
        )

        jsonl = tmp_path / ".seed_artifacts" / "audit" / "auth_events.jsonl"
        assert jsonl.exists()
        lines = [json.loads(ln) for ln in jsonl.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        assert lines[0]["action"] == "broken.test"

    def test_none_context_handled(self, memdb: _MemDB):
        from app.core.authz import ensure_audit_events_table, audit_auth_event

        ensure_audit_events_table(memdb)
        request = _fake_request(app_db=memdb)

        audit_auth_event(
            action="anon.access",
            request=request,
            context=None,
            allowed=False,
        )

        row = dict(memdb.fetchone("SELECT * FROM audit_events"))
        assert row["user_id"] is None
        assert row["role"] is None
        assert row["auth_type"] is None
