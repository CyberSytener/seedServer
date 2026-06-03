from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth_routes import build_auth_router
from app.settings import get_settings


class _DummyDB:
    def fetchone(self, *_args, **_kwargs):
        return None

    def execute(self, *_args, **_kwargs):
        return None


class _DummyRedis:
    pass


async def _noop_seed(_app: FastAPI, _user_id: str) -> None:
    return None


def test_auth_providers_endpoint_reflects_enabled_modes(monkeypatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_KEY", "admin_test")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "1")
    monkeypatch.setenv("JWT_SECRET_KEY", "jwt_secret_for_tests")

    app = FastAPI()
    router = build_auth_router(
        app=app,
        db=_DummyDB(),
        redis_client=_DummyRedis(),
        settings=get_settings(),
        dev_password_hash=lambda _u, _p: "hash",
        seed_dev_inventory=_noop_seed,
        get_active_plan_for_user=lambda _u: "free",
        get_plan=lambda _plan: SimpleNamespace(fast_daily_limit=0),
        build_models_catalog=lambda _settings: [],
        job_id_factory=lambda prefix: f"{prefix}_1",
    )
    app.include_router(router)

    client = TestClient(app)
    response = client.get("/v1/auth/providers")
    assert response.status_code == 200

    payload = response.json()
    provider_map = {item["id"]: item["enabled"] for item in payload["providers"]}
    assert payload["default"] == "api_key"
    assert provider_map["api_key"] is True
    assert provider_map["admin_key"] is True
    assert provider_map["jwt"] is True
    assert provider_map["legacy_x_user_id"] is True


def test_me_accepts_test_token_without_persisted_user(monkeypatch) -> None:
    monkeypatch.setenv("SEED_ENV", "test")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "1")
    monkeypatch.setenv("SEED_ADMIN_KEY", "admin_test")

    app = FastAPI()
    router = build_auth_router(
        app=app,
        db=_DummyDB(),
        redis_client=_DummyRedis(),
        settings=get_settings(),
        dev_password_hash=lambda _u, _p: "hash",
        seed_dev_inventory=_noop_seed,
        get_active_plan_for_user=lambda _u: "free",
        get_plan=lambda _plan: SimpleNamespace(fast_daily_limit=0),
        build_models_catalog=lambda _settings: [],
        job_id_factory=lambda prefix: f"{prefix}_1",
    )
    app.include_router(router)

    client = TestClient(app)
    response = client.get(
        "/v1/me",
        headers={"Authorization": "Bearer test_devuser|developer|runs:read"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "devuser"
    assert payload["meta"]["role"] == "developer"
    assert payload["meta"]["test_mode"] is True
