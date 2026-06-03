from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.admin_routes import build_admin_router
from app.core.auth import authenticate, issue_key_for_user
from app.core.authz import resolve_auth_context
from app.infrastructure.db.sqlite import DB


def _request(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host="127.0.0.1"),
        url=SimpleNamespace(path="/v1/test"),
    )


async def _set_system_mode(_mode: str) -> None:
    return None


def test_admin_endpoints_accept_admin_key_and_reject_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_KEY", "strict_admin_key")

    db = DB(":memory:")
    db.init_schema()
    try:
        db.execute(
            "INSERT INTO users(id, email, is_admin) VALUES(?, ?, 1)",
            ("admin_user", "admin@example.com"),
        )
        admin_bearer_key = issue_key_for_user(db, "admin_user")

        app = FastAPI()
        app.include_router(build_admin_router(db=db, set_system_mode=_set_system_mode))
        client = TestClient(app)

        accepted = client.post(
            "/v1/admin/mode",
            headers={"X-Admin-Key": "strict_admin_key"},
            json={"mode": "normal"},
        )
        assert accepted.status_code == 200

        rejected = client.post(
            "/v1/admin/mode",
            headers={"Authorization": f"Bearer {admin_bearer_key}"},
            json={"mode": "normal"},
        )
        assert rejected.status_code == 401
        assert rejected.json()["detail"] == "admin key required"
    finally:
        db.close()


def test_invalid_bearer_does_not_fallback_to_legacy_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "1")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "0")

    db = DB(":memory:")
    db.init_schema()
    try:
        db.execute(
            "INSERT INTO users(id, email) VALUES(?, ?)",
            ("legacy_user", "legacy@example.com"),
        )
        request = _request(
            {
                "Authorization": "Bearer not_a_real_key",
                "X-User-ID": "legacy_user",
            }
        )

        with pytest.raises(HTTPException) as exc:
            authenticate(request, db)

        assert exc.value.status_code == 401
        assert exc.value.detail == "invalid api key"
    finally:
        db.close()


def test_test_auth_mode_flag_gates_test_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    db = DB(":memory:")
    db.init_schema()
    try:
        token = "test_dev-user|developer|runs:write,providers:use:real"
        request = _request({"Authorization": f"Bearer {token}"})

        monkeypatch.setenv("SEED_TEST_AUTH_MODE", "0")
        with pytest.raises(HTTPException) as disabled_exc:
            authenticate(request, db)
        assert disabled_exc.value.status_code == 401

        monkeypatch.setenv("SEED_TEST_AUTH_MODE", "1")
        enabled_ctx = authenticate(request, db)
        assert enabled_ctx.user_id == "dev-user"
        assert enabled_ctx.is_admin is False
    finally:
        db.close()


def test_test_tokens_are_blocked_outside_dev_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ENV", "production")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "1")

    db = DB(":memory:")
    db.init_schema()
    try:
        request = _request({"Authorization": "Bearer test_prod-user|developer|runs:write"})
        with pytest.raises(HTTPException) as exc:
            authenticate(request, db)
        assert exc.value.status_code == 401
    finally:
        db.close()


def test_dev_user_meta_does_not_upgrade_role_when_test_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEED_ENV", "development")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "0")

    db = DB(":memory:")
    db.init_schema()
    try:
        db.execute(
            "INSERT INTO users(id, email, meta_json, is_admin) VALUES(?, ?, ?, 0)",
            ("meta_dev_user", "meta-dev@example.com", '{"dev_user": true}'),
        )
        api_key = issue_key_for_user(db, "meta_dev_user")

        app = FastAPI()
        app.state.seed = SimpleNamespace(db=db)

        @app.get("/ctx")
        async def ctx_endpoint(request: Request):
            ctx = resolve_auth_context(request, db, required=True)
            return {"role": ctx.role, "user_id": ctx.user_id}

        client = TestClient(app)
        response = client.get("/ctx", headers={"Authorization": f"Bearer {api_key}"})
        assert response.status_code == 200
        assert response.json()["user_id"] == "meta_dev_user"
        assert response.json()["role"] == "user"
    finally:
        db.close()
