"""Test: startup warns when api_key_pepper is empty in production (Phase 4, Task 4.2)."""
from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock

import pytest


def _make_settings(**overrides):
    """Return a Settings-like object with sensible defaults + overrides."""
    from dataclasses import fields
    from app.settings import Settings

    defaults = {
        "environment": "production",
        "is_production": True,
        "public_mode": False,
        "db_path": ":memory:",
        "default_plan": "free",
        "emergency_mode": False,
        "fast_timeout_sec": 3,
        "max_input_chars_default": 12000,
        "max_output_chars_default": 20000,
        "admin_key": "test-admin-key",
        "api_key_pepper": "",
        "cache_ttl_days": 7,
        "enable_legacy_x_user_id": False,
        "redis_url": "redis://localhost:6379/0",
        "redis_namespace": "seed",
        "embedded_workers": False,
        "embedded_scheduler": False,
        "embedded_worker_queues": "q_fast",
        "default_provider_fast": "gemini",
        "default_provider_batch": "gemini",
        "openai_api_key": "",
        "openai_base_url": "",
        "openai_model_fast": "",
        "openai_model_batch": "",
        "gemini_api_key": "",
        "gemini_base_url": "",
        "gemini_model_fast": "",
        "gemini_model_batch": "",
        "jwt_audience": "seed-server",
        "jwt_issuer": "seed-server",
        "hard_rpm_default": 240,
        "hard_rps_default": 20,
        "metrics_enabled": False,
        "log_level": "INFO",
        "cors_dev_mode": False,
        "cors_origins": "",
        "allowed_origins": "",
        "dev_mode": False,
        "optimize_mode": False,
        "prompt_test_mode": False,
        "max_request_body_bytes": 10 * 1024 * 1024,
        "parser_version": "baseline",
        "enable_openai": True,
        "enable_gemini": True,
        "enable_stub": True,
        "seed_dev_users_on_startup": False,
        "test_auth_mode": False,
        "test_auth_default_role": "developer",
        "test_auth_default_scopes": "",
        "agent_session_ttl_seconds": 3600,
        "sandbox_enabled": False,
        "agent_max_nesting_depth": 3,
        "agent_max_parallel_children": 5,
        "sandbox_egress_proxy_url": "http://sandbox_egress_proxy:3128",
        "sandbox_egress_allowlist": "github.com,api.github.com,raw.githubusercontent.com,codeload.github.com",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_empty_pepper_warns_in_production(caplog):
    """Production mode + empty pepper → warning logged."""
    settings = _make_settings(is_production=True, public_mode=False, api_key_pepper="")

    with patch("app.main.get_settings", return_value=settings):
        with caplog.at_level(logging.WARNING):
            # We only need to exercise the startup guard section.
            # Import create_app and catch the expected downstream errors.
            try:
                from app.main import create_app
                create_app()
            except Exception:
                pass  # We don't care about full app init — only the warning

    assert any("SEED_API_KEY_PEPPER is empty" in r.message for r in caplog.records)


def test_empty_pepper_warns_in_public_mode(caplog):
    """Public mode + empty pepper → warning logged."""
    settings = _make_settings(
        is_production=False, public_mode=True, api_key_pepper="",
        environment="development",
    )

    with patch("app.main.get_settings", return_value=settings):
        with caplog.at_level(logging.WARNING):
            try:
                from app.main import create_app
                create_app()
            except Exception:
                pass

    assert any("SEED_API_KEY_PEPPER is empty" in r.message for r in caplog.records)


def test_nonempty_pepper_no_warning(caplog):
    """Non-empty pepper → no warning."""
    settings = _make_settings(is_production=True, api_key_pepper="my-secret-pepper")

    with patch("app.main.get_settings", return_value=settings):
        with caplog.at_level(logging.WARNING):
            try:
                from app.main import create_app
                create_app()
            except Exception:
                pass

    assert not any("SEED_API_KEY_PEPPER is empty" in r.message for r in caplog.records)


def test_dev_mode_empty_pepper_no_warning(caplog):
    """Dev mode + empty pepper → no warning (only matters in production/public)."""
    settings = _make_settings(
        is_production=False, public_mode=False, api_key_pepper="",
        environment="development",
    )

    with patch("app.main.get_settings", return_value=settings):
        with caplog.at_level(logging.WARNING):
            try:
                from app.main import create_app
                create_app()
            except Exception:
                pass

    assert not any("SEED_API_KEY_PEPPER is empty" in r.message for r in caplog.records)
