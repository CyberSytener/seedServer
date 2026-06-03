from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.authz import require_scope, resolve_auth_context


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.seed = SimpleNamespace(db=object())

    @app.get("/ctx")
    async def ctx_endpoint(request: Request):
        ctx = resolve_auth_context(request, request.app.state.seed.db, required=True)
        return {
            "user_id": ctx.user_id if ctx else None,
            "role": ctx.role if ctx else None,
            "auth_type": ctx.auth_type if ctx else None,
            "has_real_scope": ctx.has_scope("providers:use:real") if ctx else False,
        }

    @app.get("/real")
    async def real_endpoint(request: Request):
        ctx = require_scope(request, request.app.state.seed.db, "providers:use:real")
        return {"ok": True, "user_id": ctx.user_id, "role": ctx.role}

    return app


def test_test_token_resolves_context_and_scopes() -> None:
    prev = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "1"
    client = TestClient(_build_app())
    try:
        response = client.get(
            "/ctx",
            headers={"Authorization": "Bearer test_sim-user|developer|runs:write,providers:use:real"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["user_id"] == "sim-user"
        assert payload["auth_type"] == "test_token"
        assert payload["has_real_scope"] is True
    finally:
        if prev is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev


def test_test_token_without_required_scope_is_denied() -> None:
    prev = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "1"
    client = TestClient(_build_app())
    try:
        denied = client.get(
            "/real",
            headers={"Authorization": "Bearer test_sim-user|user|runs:write"},
        )
        assert denied.status_code == 403

        allowed = client.get(
            "/real",
            headers={"Authorization": "Bearer test_sim-user|developer|runs:write,providers:use:real"},
        )
        assert allowed.status_code == 200
    finally:
        if prev is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev


def test_test_token_is_rejected_when_mode_disabled() -> None:
    prev = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "0"
    client = TestClient(_build_app())
    try:
        response = client.get(
            "/ctx",
            headers={"Authorization": "Bearer test_sim-user|developer|runs:write,providers:use:real"},
        )
        assert response.status_code == 401
    finally:
        if prev is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev
