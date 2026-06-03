"""Tests for auth failure rate-limiting (Task 4.5)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# AuthFailureRateLimiter unit tests
# ---------------------------------------------------------------------------

class TestAuthFailureRateLimiter:
    def _make(self, max_failures: int = 5, window_seconds: int = 60):
        from app.core.auth import AuthFailureRateLimiter
        return AuthFailureRateLimiter(max_failures=max_failures, window_seconds=window_seconds)

    def test_not_blocked_initially(self):
        limiter = self._make()
        assert limiter.is_blocked("1.2.3.4") is False

    def test_blocked_after_max_failures(self):
        limiter = self._make(max_failures=3)
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is True

    def test_not_blocked_under_threshold(self):
        limiter = self._make(max_failures=5)
        for _ in range(4):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4") is False

    def test_different_ips_independent(self):
        limiter = self._make(max_failures=2)
        limiter.record_failure("1.1.1.1")
        limiter.record_failure("1.1.1.1")
        assert limiter.is_blocked("1.1.1.1") is True
        assert limiter.is_blocked("2.2.2.2") is False

    def test_reset_clears_ip(self):
        limiter = self._make(max_failures=2)
        limiter.record_failure("1.1.1.1")
        limiter.record_failure("1.1.1.1")
        assert limiter.is_blocked("1.1.1.1") is True
        limiter.reset("1.1.1.1")
        assert limiter.is_blocked("1.1.1.1") is False

    def test_window_expiry(self):
        """Failures older than the window are pruned."""
        limiter = self._make(max_failures=2, window_seconds=1)
        limiter.record_failure("1.1.1.1")
        limiter.record_failure("1.1.1.1")
        assert limiter.is_blocked("1.1.1.1") is True
        time.sleep(1.1)
        assert limiter.is_blocked("1.1.1.1") is False

    def test_exactly_at_threshold(self):
        limiter = self._make(max_failures=3)
        for _ in range(3):
            limiter.record_failure("1.1.1.1")
        assert limiter.is_blocked("1.1.1.1") is True


# ---------------------------------------------------------------------------
# Integration: authenticate() respects the rate limiter
# ---------------------------------------------------------------------------

def _fake_request(ip: str = "10.0.0.1"):
    req = MagicMock()
    req.client.host = ip
    req.headers = {}
    req.url.path = "/v1/test"
    return req


def _fake_db():
    db = MagicMock()
    db.fetchone.return_value = None
    return db


class TestAuthenticateRateLimiting:
    @pytest.fixture(autouse=True)
    def _reset_limiter(self):
        """Ensure a clean limiter for every test."""
        from app.core import auth
        original = auth._auth_failure_limiter
        auth._auth_failure_limiter = auth.AuthFailureRateLimiter(max_failures=3, window_seconds=60)
        yield
        auth._auth_failure_limiter = original

    def test_returns_429_after_threshold(self):
        from app.core import auth
        from app.core.auth import authenticate

        ip = "10.0.0.99"
        # Record failures up to threshold
        for _ in range(3):
            auth._auth_failure_limiter.record_failure(ip)

        req = _fake_request(ip=ip)
        db = _fake_db()
        with pytest.raises(HTTPException) as exc:
            authenticate(req, db)
        assert exc.value.status_code == 429
        assert "too many" in exc.value.detail.lower()

    def test_normal_auth_not_affected(self):
        """Below threshold, auth proceeds normally (may fail for other reasons)."""
        from app.core import auth
        from app.core.auth import authenticate

        ip = "10.0.0.50"
        # Only 1 failure — under threshold of 3
        auth._auth_failure_limiter.record_failure(ip)

        req = _fake_request(ip=ip)
        db = _fake_db()
        # With no API key / headers, should get 401 (missing key) not 429
        with pytest.raises(HTTPException) as exc:
            authenticate(req, db)
        assert exc.value.status_code != 429  # NOT rate-limited

    def test_failure_recorded_on_invalid_key(self):
        """An invalid key auth attempt records a failure."""
        from app.core import auth
        from app.core.auth import authenticate

        ip = "10.0.0.55"
        req = _fake_request(ip=ip)
        req.headers = {"authorization": "Bearer bad_key_12345"}
        db = _fake_db()

        # Should fail with 401 (invalid key) and record a failure
        with pytest.raises(HTTPException) as exc:
            authenticate(req, db)
        assert exc.value.status_code == 401

        assert len(auth._auth_failure_limiter._buckets.get(ip, [])) >= 1

    def test_multiple_failures_trigger_lockout(self):
        """Three invalid-key attempts lock out the IP."""
        from app.core import auth
        from app.core.auth import authenticate

        ip = "10.0.0.77"
        req = _fake_request(ip=ip)
        req.headers = {"authorization": "Bearer bad_key_xyz"}
        db = _fake_db()

        for _ in range(3):
            with pytest.raises(HTTPException):
                authenticate(req, db)

        # Now the IP should be rate-limited (429)
        with pytest.raises(HTTPException) as exc:
            authenticate(req, db)
        assert exc.value.status_code == 429
