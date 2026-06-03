"""Tests for timing-safe internal auth token check (Task 0.3).

Verifies that ``/internal/dependencies`` uses ``hmac.compare_digest``
rather than ``==`` and correctly gates access behind the
``INTERNAL_AUTH_TOKEN`` env var or localhost restriction.
"""
from __future__ import annotations

import hmac
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.support.app_factory import create_test_app


def _build_client(monkeypatch, tmp_path, *, internal_token: str | None = None):
    env = {
        "SEED_ADMIN_KEY": "test_key",
        "SEED_PUBLIC_MODE": "0",  # needed so the endpoint is reachable
    }
    if internal_token is not None:
        env["INTERNAL_AUTH_TOKEN"] = internal_token
    app = create_test_app(
        monkeypatch,
        db_path=str(tmp_path / "timing_safe.db"),
        env_overrides=env,
    )
    return TestClient(app)


class TestInternalDependenciesAuth:
    """Verify /internal/dependencies gating."""

    def test_valid_token_allowed(self, monkeypatch, tmp_path):
        client = _build_client(monkeypatch, tmp_path, internal_token="s3cret")
        resp = client.get(
            "/internal/dependencies",
            headers={"X-Internal-Auth": "s3cret"},
        )
        # Should *not* be 401 — may be 200 or 500 depending on dep modules
        assert resp.status_code != 401

    def test_wrong_token_rejected(self, monkeypatch, tmp_path):
        client = _build_client(monkeypatch, tmp_path, internal_token="s3cret")
        resp = client.get(
            "/internal/dependencies",
            headers={"X-Internal-Auth": "wrong"},
        )
        assert resp.status_code == 401

    def test_missing_token_header_rejected(self, monkeypatch, tmp_path):
        client = _build_client(monkeypatch, tmp_path, internal_token="s3cret")
        resp = client.get("/internal/dependencies")
        assert resp.status_code == 401

    def test_uses_constant_time_comparison(self, monkeypatch, tmp_path):
        """Ensure hmac.compare_digest is actually called (not ==)."""
        client = _build_client(monkeypatch, tmp_path, internal_token="s3cret")
        with patch("app.main.hmac.compare_digest", wraps=hmac.compare_digest) as spy:
            client.get(
                "/internal/dependencies",
                headers={"X-Internal-Auth": "s3cret"},
            )
            spy.assert_called_once()
