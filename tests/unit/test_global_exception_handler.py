"""Tests for the global unhandled-exception handler (Task 0.2).

Verifies that any unhandled ``Exception`` raised inside a route results in
a clean 500 JSON response with ``{"detail": "internal_server_error"}`` and
**no** stack trace leakage to the client.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.support.app_factory import create_test_app


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _client_with_crash_route(monkeypatch, tmp_path) -> TestClient:
    """Build a TestClient whose app has a route that always raises."""
    app: FastAPI = create_test_app(
        monkeypatch,
        db_path=str(tmp_path / "exc_handler.db"),
        env_overrides={"SEED_ADMIN_KEY": "test_key"},
    )

    @app.get("/test-crash")
    async def _crash():
        raise RuntimeError("deliberate boom")

    return TestClient(app, raise_server_exceptions=False)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_unhandled_exception_returns_500(monkeypatch, tmp_path):
    """Route that raises RuntimeError must yield 500 + generic body."""
    client = _client_with_crash_route(monkeypatch, tmp_path)
    resp = client.get("/test-crash")

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "internal_server_error"}


def test_no_stack_trace_in_response(monkeypatch, tmp_path):
    """Ensure the raw response text never contains the secret error message."""
    client = _client_with_crash_route(monkeypatch, tmp_path)
    resp = client.get("/test-crash")

    text = resp.text
    assert "deliberate boom" not in text
    assert "Traceback" not in text
    assert "RuntimeError" not in text
