"""Unit tests for the sandbox egress proxy (P0-28).

Tests cover:
  • Domain allowlist validation (_is_allowed)
  • Rate limiting logic (_is_rate_limited)
  • Settings wiring (sandbox_egress_proxy_url & sandbox_egress_allowlist)
"""

from __future__ import annotations

import importlib
import os
import time
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Helper: import proxy module with configurable env
# ---------------------------------------------------------------------------


def _import_proxy(env_overrides: dict | None = None):
    """Import (or re-import) the proxy module with optional env vars."""
    env = {
        "PROXY_PORT": "3128",
        "PROXY_ALLOWLIST": "github.com,api.github.com,raw.githubusercontent.com,codeload.github.com",
        "PROXY_MAX_RPM": "60",
        "PROXY_MAX_BYTES": str(5 * 1024 * 1024),
        "PROXY_CONNECT_TIMEOUT": "5",
        "PROXY_READ_TIMEOUT": "15",
    }
    if env_overrides:
        env.update(env_overrides)
    with mock.patch.dict(os.environ, env, clear=False):
        import scripts.sandbox_egress_proxy as mod
        importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# Domain validation tests
# ---------------------------------------------------------------------------


class TestIsAllowed:
    """Tests for _is_allowed domain checking."""

    def setup_method(self):
        self.mod = _import_proxy()

    def test_exact_match(self):
        assert self.mod._is_allowed("github.com") is True

    def test_exact_match_case_insensitive(self):
        assert self.mod._is_allowed("GitHub.COM") is True

    def test_subdomain_of_allowed(self):
        assert self.mod._is_allowed("foo.github.com") is True

    def test_deep_subdomain(self):
        assert self.mod._is_allowed("a.b.c.github.com") is True

    def test_not_allowed(self):
        assert self.mod._is_allowed("evil.com") is False

    def test_partial_suffix_not_allowed(self):
        """'notgithub.com' should NOT match 'github.com'."""
        assert self.mod._is_allowed("notgithub.com") is False

    def test_empty_string(self):
        assert self.mod._is_allowed("") is False

    def test_api_github(self):
        assert self.mod._is_allowed("api.github.com") is True

    def test_raw_githubusercontent(self):
        assert self.mod._is_allowed("raw.githubusercontent.com") is True

    def test_codeload(self):
        assert self.mod._is_allowed("codeload.github.com") is True

    def test_different_tld_blocked(self):
        assert self.mod._is_allowed("github.io") is False


class TestIsAllowedCustomList:
    """Tests with a custom allowlist."""

    def test_custom_single_domain(self):
        mod = _import_proxy({"PROXY_ALLOWLIST": "pypi.org"})
        assert mod._is_allowed("pypi.org") is True
        assert mod._is_allowed("github.com") is False

    def test_custom_multi_domain(self):
        mod = _import_proxy({"PROXY_ALLOWLIST": "pypi.org,npmjs.com"})
        assert mod._is_allowed("pypi.org") is True
        assert mod._is_allowed("npmjs.com") is True
        assert mod._is_allowed("github.com") is False


# ---------------------------------------------------------------------------
# Rate limiter tests
# ---------------------------------------------------------------------------


class TestRateLimiter:
    """Tests for _is_rate_limited."""

    def setup_method(self):
        self.mod = _import_proxy({"PROXY_MAX_RPM": "5"})
        # Clear rate windows between tests
        self.mod._rate_windows.clear()

    def test_under_limit_not_blocked(self):
        for _ in range(4):
            assert self.mod._is_rate_limited("10.0.0.1") is False

    def test_at_limit_blocked(self):
        for _ in range(5):
            self.mod._is_rate_limited("10.0.0.2")
        assert self.mod._is_rate_limited("10.0.0.2") is True

    def test_different_ips_independent(self):
        for _ in range(5):
            self.mod._is_rate_limited("10.0.0.3")
        # Different IP should still be fine
        assert self.mod._is_rate_limited("10.0.0.4") is False

    def test_window_expiry(self):
        """Entries older than 60s are pruned."""
        ip = "10.0.0.5"
        # Fill up the window
        for _ in range(5):
            self.mod._is_rate_limited(ip)
        assert self.mod._is_rate_limited(ip) is True

        # Simulate time passing beyond 60s window
        now = time.monotonic()
        self.mod._rate_windows[ip] = [now - 70, now - 65, now - 61, now - 62, now - 63]
        assert self.mod._is_rate_limited(ip) is False


# ---------------------------------------------------------------------------
# Configuration loading tests
# ---------------------------------------------------------------------------


class TestConfiguration:
    """Tests for configuration via environment."""

    def test_default_allowlist(self):
        mod = _import_proxy()
        assert "github.com" in mod.ALLOWLIST
        assert "api.github.com" in mod.ALLOWLIST
        assert len(mod.ALLOWLIST) == 4

    def test_custom_port(self):
        mod = _import_proxy({"PROXY_PORT": "9999"})
        assert mod.PROXY_PORT == 9999

    def test_custom_rpm(self):
        mod = _import_proxy({"PROXY_MAX_RPM": "100"})
        assert mod.MAX_REQUESTS_PER_MINUTE == 100

    def test_custom_max_bytes(self):
        mod = _import_proxy({"PROXY_MAX_BYTES": "1048576"})
        assert mod.MAX_RESPONSE_BYTES == 1048576

    def test_custom_timeouts(self):
        mod = _import_proxy({"PROXY_CONNECT_TIMEOUT": "10", "PROXY_READ_TIMEOUT": "30"})
        assert mod.CONNECT_TIMEOUT == 10.0
        assert mod.READ_TIMEOUT == 30.0


# ---------------------------------------------------------------------------
# Settings integration tests
# ---------------------------------------------------------------------------


class TestSettingsIntegration:
    """Verify the Settings dataclass has the new P0-28 fields."""

    def test_settings_has_proxy_url(self):
        from app.settings import get_settings
        s = get_settings()
        assert hasattr(s, "sandbox_egress_proxy_url")
        assert "3128" in s.sandbox_egress_proxy_url

    def test_settings_has_allowlist(self):
        from app.settings import get_settings
        s = get_settings()
        assert hasattr(s, "sandbox_egress_allowlist")
        assert "github.com" in s.sandbox_egress_allowlist

    def test_settings_proxy_url_from_env(self):
        with mock.patch.dict(os.environ, {"SEED_SANDBOX_EGRESS_PROXY_URL": "http://my-proxy:9999"}):
            from app.settings import get_settings
            s = get_settings()
            assert s.sandbox_egress_proxy_url == "http://my-proxy:9999"

    def test_settings_allowlist_from_env(self):
        with mock.patch.dict(os.environ, {"SEED_SANDBOX_EGRESS_ALLOWLIST": "pypi.org,npmjs.com"}):
            from app.settings import get_settings
            s = get_settings()
            assert s.sandbox_egress_allowlist == "pypi.org,npmjs.com"
