"""Tests for auth failure Prometheus metrics instrumentation."""

import importlib

import pytest
from fastapi import HTTPException

from app.core.metrics import AUTH_FAILURES


def _get_counter_value(reason: str) -> float:
    """Return the current value of AUTH_FAILURES for a given reason label."""
    # prometheus_client exposes _value on the child metric
    return AUTH_FAILURES.labels(reason=reason)._value.get()


@pytest.fixture()
def _reset_auth_metrics():
    """Snapshot metric values so tests can measure deltas."""
    yield


class TestResolveAuthContextMetrics:
    """Verify AUTH_FAILURES is incremented on resolve_auth_context failures."""

    @staticmethod
    def _make_fake_request(headers: dict | None = None, path: str = "/test"):
        """Return a minimal request-like object."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        req = MagicMock(spec=["headers", "url", "client"])
        req.headers = headers or {}
        req.url = SimpleNamespace(path=path)
        req.client = SimpleNamespace(host="127.0.0.1")
        return req

    def test_missing_api_key_increments_counter(self, _reset_auth_metrics):
        from app.core.auth import authenticate

        before = _get_counter_value("missing_api_key")

        class FakeDB:
            pass

        fake_req = self._make_fake_request(headers={})
        with pytest.raises(HTTPException) as exc_info:
            authenticate(fake_req, FakeDB())
        assert exc_info.value.status_code == 401

        after = _get_counter_value("missing_api_key")
        assert after == before + 1

    def test_invalid_api_key_increments_counter(self, _reset_auth_metrics):
        from app.core.auth import authenticate

        before = _get_counter_value("invalid_api_key")

        class FakeDB:
            def fetchone(self, *a, **kw):
                return None

        fake_req = self._make_fake_request(
            headers={"Authorization": "Bearer bad-key-not-in-db"}
        )
        with pytest.raises(HTTPException) as exc_info:
            authenticate(fake_req, FakeDB())
        assert exc_info.value.status_code == 401

        after = _get_counter_value("invalid_api_key")
        assert after == before + 1

    def test_banned_user_increments_counter(self, _reset_auth_metrics):
        from app.core.auth import authenticate

        before = _get_counter_value("banned")

        class FakeDB:
            def fetchone(self, *a, **kw):
                return {"id": "user1", "is_admin": 0, "is_banned": 1}

        fake_req = self._make_fake_request(
            headers={"Authorization": "Bearer some-key"}
        )
        with pytest.raises(HTTPException) as exc_info:
            authenticate(fake_req, FakeDB())
        assert exc_info.value.status_code == 403

        after = _get_counter_value("banned")
        assert after == before + 1


class TestRequireAdminKeyMetrics:
    """Verify AUTH_FAILURES is incremented on require_admin_key failures."""

    @staticmethod
    def _make_fake_request(headers: dict | None = None):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        req = MagicMock(spec=["headers"])
        req.headers = headers or {}
        return req

    def test_admin_disabled_increments_counter(self, monkeypatch, _reset_auth_metrics):
        from app.core import auth as auth_mod

        before = _get_counter_value("admin_disabled")

        # Make get_settings return empty admin_key
        class FakeSettings:
            admin_key = ""

        monkeypatch.setattr(auth_mod, "get_settings", lambda: FakeSettings())

        with pytest.raises(HTTPException) as exc_info:
            auth_mod.require_admin_key(self._make_fake_request())
        assert exc_info.value.status_code == 403

        after = _get_counter_value("admin_disabled")
        assert after == before + 1

    def test_invalid_admin_key_increments_counter(self, monkeypatch, _reset_auth_metrics):
        from app.core import auth as auth_mod

        before = _get_counter_value("invalid_admin_key")

        class FakeSettings:
            admin_key = "correct-secret"

        monkeypatch.setattr(auth_mod, "get_settings", lambda: FakeSettings())

        with pytest.raises(HTTPException) as exc_info:
            auth_mod.require_admin_key(
                self._make_fake_request(headers={"X-Admin-Key": "wrong"})
            )
        assert exc_info.value.status_code == 401

        after = _get_counter_value("invalid_admin_key")
        assert after == before + 1
