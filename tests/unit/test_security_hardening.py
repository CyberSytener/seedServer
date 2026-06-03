from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.auth import authenticate
from app.core.security.jwt import JWTHandler
from app.infrastructure.db.sqlite import DB
from app.settings import get_settings


def _build_request(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host="127.0.0.1"),
        url=SimpleNamespace(path="/test"),
    )


def _init_users_table(db: DB) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            api_key_hash TEXT,
            api_key_last4 TEXT,
            api_key_created_at TEXT,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0
        )
        """
    )


def test_admin_like_key_no_longer_authenticates_without_configured_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEED_ENV", "development")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "0")
    monkeypatch.delenv("SEED_ADMIN_KEY", raising=False)

    db = DB(":memory:")
    _init_users_table(db)
    request = _build_request({"X-Admin-Key": "sk_test_like_admin_key"})

    with pytest.raises(HTTPException) as exc:
        authenticate(request, db)

    db.close()
    assert exc.value.status_code == 401
    assert exc.value.detail == "missing api key"


def test_admin_key_env_fallback_is_not_used_when_settings_admin_key_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEED_ENV", "development")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "0")
    monkeypatch.setenv("SEED_ADMIN_KEY", "env_admin_secret_should_not_be_used")
    monkeypatch.setattr(
        "app.core.auth.get_settings",
        lambda: SimpleNamespace(admin_key="", enable_legacy_x_user_id=False),
    )

    db = DB(":memory:")
    _init_users_table(db)
    request = _build_request({"X-Admin-Key": "env_admin_secret_should_not_be_used"})

    with pytest.raises(HTTPException) as exc:
        authenticate(request, db)

    db.close()
    assert exc.value.status_code == 401
    assert exc.value.detail == "missing api key"


def test_production_profile_hard_disables_legacy_x_user_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEED_ENV", "production")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "1")

    db = DB(":memory:")
    _init_users_table(db)
    request = _build_request({"X-User-ID": "legacy_user"})

    with pytest.raises(HTTPException) as exc:
        authenticate(request, db)

    db.close()
    assert exc.value.status_code == 401
    assert exc.value.detail == "missing api key"


def test_production_profile_disables_dev_only_flags(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEED_ENV", "production")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "1")
    monkeypatch.setenv("SEED_DEV_CORS", "1")
    monkeypatch.setenv("SEED_SEED_DEV_USERS_ON_STARTUP", "1")

    settings = get_settings()

    assert settings.is_production is True
    assert settings.enable_legacy_x_user_id is False
    assert settings.cors_dev_mode is False
    assert settings.seed_dev_users_on_startup is False


def test_jwt_handler_rejects_empty_secret():
    pytest.importorskip("jwt")
    with pytest.raises(RuntimeError, match="required and must be non-empty"):
        JWTHandler(secret_key="")


def test_jwt_handler_rejects_disallowed_algorithm():
    pytest.importorskip("jwt")
    with pytest.raises(ValueError, match="Unsupported JWT algorithm"):
        JWTHandler(secret_key="a" * 32, algorithm="RS256")


def test_jwt_handler_rejects_short_hs_secret():
    pytest.importorskip("jwt")
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        JWTHandler(secret_key="short-secret")
