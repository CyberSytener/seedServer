from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agent_integration import router
from app.core.saga_blueprints import BlueprintStore


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("SEED_ADMIN_KEY", "test_admin")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "1")
    app = FastAPI()
    app.include_router(router)
    app.state.seed = SimpleNamespace(db=object())
    app.state.agent_blueprint_store = BlueprintStore()
    return TestClient(app)


def _headers(token: str = "test_agent|developer|catalog:read,blueprints:write,runs:write") -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin_only_headers() -> Dict[str, str]:
    return {"X-Admin-Key": "test_admin"}


def _valid_blueprint() -> Dict[str, Any]:
    return {
        "name": "agent_surface_blueprint",
        "version": "v1",
        "steps": [
            {
                "id": "scan_jobs",
                "block": "market_scanner",
                "inputs": {"user_id": {"from": "user_id"}},
            }
        ],
    }


def test_catalog_requires_auth(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get("/v1/catalog/tree")
    assert response.status_code == 401


def test_catalog_path_traversal_protection(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    ok = client.get("/v1/catalog/node/blueprint_dsl_v0.json", headers=_headers())
    assert ok.status_code == 200
    assert ok.json()["path"] == "blueprint_dsl_v0.json"

    traversal = client.get("/v1/catalog/node/%2e%2e/main.py", headers=_headers())
    assert traversal.status_code == 400
    assert traversal.json()["detail"]["error"] == "invalid_catalog_path"

    absolute = client.get("/v1/catalog/node/C:%5CWindows%5Cwin.ini", headers=_headers())
    assert absolute.status_code == 400
    assert absolute.json()["detail"]["error"] == "invalid_catalog_path"


def test_catalog_context_pack_endpoint(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get(
        "/v1/catalog/context-pack",
        headers=_headers(),
        params={
            "domain": "neoeats",
            "intent": "hot_offer",
            "constraints": '{"budget":"tight","latency_sec":10}',
            "max_modules": 6,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_version"] == "v0"
    assert payload["query"]["domain"] == "neoeats"
    assert payload["query"]["constraints"]["budget"] == "tight"
    assert isinstance(payload["module_candidates"], list)
    assert len(payload["module_candidates"]) <= 6


def test_catalog_context_pack_rejects_invalid_constraints(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get(
        "/v1/catalog/context-pack",
        headers=_headers(),
        params={"constraints": "{not-valid-json"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "invalid_constraints_json"


def test_catalog_context_pack_post_endpoint(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/catalog/context-pack",
        headers=_headers(),
        json={
            "domain": "neoeats",
            "intent": "recipe",
            "constraints": {"budget": "tight"},
            "max_modules": 5,
            "include_manifests": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"]["domain"] == "neoeats"
    assert payload["query"]["intent"] == "recipe"
    assert payload["query"]["constraints"]["budget"] == "tight"
    assert isinstance(payload.get("module_manifests"), list)
    assert len(payload["module_candidates"]) <= 5


def test_catalog_context_pack_post_rejects_invalid_constraints_shape(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/catalog/context-pack",
        headers=_headers(),
        json={"constraints": ["not", "an", "object"]},
    )
    assert response.status_code == 422


def test_generate_blueprint_returns_valid_and_passes_validate(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        return _valid_blueprint(), {"model_name": "mock", "model_tier": model_tier or "cheap"}

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)

    response = client.post(
        "/v1/blueprints/generate",
        headers=_headers(),
        json={"prompt": "build a job scan flow", "domain": "neoeats"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["validation"]["ok"] is True
    assert payload["blueprint"]["name"] == "agent_surface_blueprint"


def test_validate_rejects_invalid_blueprint_shape(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/blueprints/validate",
        headers=_headers(),
        json={
            "blueprint": {
                "name": "broken",
                "version": "v1",
                "steps": [{"id": "s1", "block": "missing_block", "inputs": {}}],
            }
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert any(
        isinstance(item, dict)
        and item.get("error") == "unknown_block"
        and item.get("step_id") == "s1"
        and item.get("block") == "missing_block"
        for item in payload["errors"]
    )


def test_dry_run_accepts_stub_and_returns_trace(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    async def _fake_run(*args, **kwargs):
        return {
            "status": "succeeded",
            "execution_mode": "DRY_RUN",
            "execution_trace": [
                {"step": "scan_jobs", "block": "market_scanner", "status": "succeeded", "elapsed_sec": 0.1}
            ],
        }

    monkeypatch.setattr("app.api.agent_integration._run_saga", _fake_run)

    response = client.post(
        "/v1/blueprints/dry-run",
        headers=_headers(),
        json={
            "blueprint": _valid_blueprint(),
            "sample_input": {"user_id": "u1"},
            "mode": "STUB",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "STUB"
    assert payload["runtime_execution_mode"] == "DRY_RUN"
    assert len(payload["execution_trace"]) == 1


def test_dry_run_rejects_live_mode(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/blueprints/dry-run",
        headers=_headers(),
        json={"blueprint": _valid_blueprint(), "sample_input": {"user_id": "u1"}, "mode": "LIVE"},
    )
    assert response.status_code == 422


def test_publish_fails_if_validation_fails(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/blueprints/publish",
        headers=_headers(),
        json={
            "name": "bad_blueprint",
            "version": "v1",
            "blueprint": {
                "name": "bad_blueprint",
                "version": "v1",
                "steps": [{"id": "s1", "block": "missing_block", "inputs": {}}],
            },
            "policy": {"target_status": "ACTIVE", "require_admin_approval": False},
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["error"] == "invalid_blueprint"


def test_catalog_rejects_admin_header_without_bearer(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get("/v1/catalog/tree", headers=_admin_only_headers())
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "missing_authorization"


def test_generate_rejects_admin_header_without_bearer(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/blueprints/generate",
        headers=_admin_only_headers(),
        json={"prompt": "build a flow"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "missing_authorization"


def test_publish_active_requires_publish_scope(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.post(
        "/v1/blueprints/publish",
        headers=_headers("test_writer|developer|blueprints:write"),
        json={
            "name": "needs_publish_scope",
            "version": "v1",
            "blueprint": _valid_blueprint(),
            "policy": {"target_status": "ACTIVE", "require_admin_approval": False},
        },
    )
    assert response.status_code == 403
    payload = response.json()
    assert payload["detail"]["error"] == "missing_scope"
    assert payload["detail"]["required_scope"] == "blueprints:publish"


def test_dry_run_injects_user_id_from_auth_context(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    captured: Dict[str, Any] = {}

    async def _fake_run(*args, **kwargs):
        captured["payload"] = args[1]
        return {
            "status": "succeeded",
            "execution_mode": "DRY_RUN",
            "execution_trace": [],
        }

    monkeypatch.setattr("app.api.agent_integration._run_saga", _fake_run)

    response = client.post(
        "/v1/blueprints/dry-run",
        headers=_headers("test_ctx-user|developer|blueprints:write,runs:write"),
        json={
            "blueprint": _valid_blueprint(),
            "sample_input": {},
            "mode": "DRY_RUN",
        },
    )
    assert response.status_code == 200
    assert captured["payload"]["user_id"] == "ctx-user"


def test_golden_loop_user_flow(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        return _valid_blueprint(), {"model_name": "mock", "model_tier": model_tier or "cheap"}

    async def _fake_run(*args, **kwargs):
        payload = args[1]
        return {
            "status": "succeeded",
            "execution_mode": "DRY_RUN",
            "execution_trace": [
                {"step": "scan_jobs", "block": "market_scanner", "status": "succeeded", "user_id": payload.get("user_id")}
            ],
        }

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)
    monkeypatch.setattr("app.api.agent_integration._run_saga", _fake_run)

    headers = _headers("test_loop-user|developer|catalog:read,blueprints:write,runs:write")

    assert client.get("/v1/catalog/tree", headers=headers).status_code == 200
    assert (
        client.post(
            "/v1/catalog/context-pack",
            headers=headers,
            json={"domain": "neoeats", "intent": "compose", "constraints": {"budget": "tight"}},
        ).status_code
        == 200
    )

    generated = client.post(
        "/v1/blueprints/generate",
        headers=headers,
        json={"prompt": "scan, score, notify", "domain": "neoeats"},
    )
    assert generated.status_code == 200
    blueprint = generated.json()["blueprint"]

    validated = client.post(
        "/v1/blueprints/validate",
        headers=headers,
        json={"blueprint": blueprint},
    )
    assert validated.status_code == 200
    assert validated.json()["ok"] is True

    dry_run = client.post(
        "/v1/blueprints/dry-run",
        headers=headers,
        json={"blueprint": blueprint, "sample_input": {}, "mode": "STUB"},
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["execution_trace"][0]["user_id"] == "loop-user"

    published = client.post(
        "/v1/blueprints/publish",
        headers=headers,
        json={
            "name": "golden_loop_blueprint",
            "blueprint": blueprint,
            "policy": {"target_status": "SANDBOXED", "require_admin_approval": True},
        },
    )
    assert published.status_code == 200
    assert published.json()["status"] == "SANDBOXED"


def test_generate_returns_normalized_blueprint_and_fixes(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        return (
            {
                "name": "neoeats_draft",
                "steps": [
                    {
                        "block": "normalize_input",
                        "inputs": {
                            "user_id": "user_id",
                            "ingredients": "payload.ingredients",
                            "constraints": "payload.constraints",
                        },
                    },
                    {
                        "block": "generate_recipe",
                        "inputs": {
                            "normalized": "normalize_input.normalized",
                        },
                    },
                    {
                        "block": "validate_recipe",
                        "inputs": {
                            "recipe": "generate_recipe.recipe",
                            "constraints": "normalize_input.normalized.constraints",
                        },
                    },
                ],
            },
            {"model_name": "gemini-2.0-flash-lite", "model_tier": model_tier or "cheap"},
        )

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)
    response = client.post(
        "/v1/blueprints/generate",
        headers=_headers(),
        json={"prompt": "build recipe flow", "domain": "neoeats"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert isinstance(payload.get("fixes_applied"), list)
    assert len(payload["fixes_applied"]) > 0
    assert payload["raw_blueprint"]["name"] == "neoeats_draft"
    assert payload["normalized_blueprint"]["version"] == "v1"
    assert payload["normalized_blueprint"]["steps"][0]["id"] == "normalize_input"
    assert payload["normalized_blueprint"]["steps"][0]["block"] == "neoeats.input.normalize"


def test_generate_preserves_unknown_block_and_returns_structured_error(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        return (
            {
                "name": "draft_unknown_block",
                "version": "v1",
                "steps": [{"id": "mystep", "block": "mystery.block", "inputs": {}}],
            },
            {"model_name": "gemini-2.0-flash-lite", "model_tier": model_tier or "cheap"},
        )

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)
    response = client.post(
        "/v1/blueprints/generate",
        headers=_headers(),
        json={"prompt": "build flow"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["normalized_blueprint"]["steps"][0]["id"] == "mystep"
    assert payload["normalized_blueprint"]["steps"][0]["block"] == "mystery.block"
    assert any("unknown_block_preserved" in fix for fix in payload.get("fixes_applied", []))
    assert any(
        isinstance(item, dict)
        and item.get("error") == "unknown_block"
        and item.get("step_id") == "mystep"
        and item.get("block") == "mystery.block"
        for item in payload["validation"]["errors"]
    )


def test_strict_mode_reprompt_called_once_on_validation_failure(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    call_count = {"n": 0}

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                {
                    "name": "broken",
                    "version": "v1",
                    "steps": [{"id": "s1", "block": "missing_block", "inputs": {}}],
                },
                {"model_name": "gemini-2.0-flash-lite", "model_tier": model_tier or "cheap"},
            )
        return _valid_blueprint(), {"model_name": "gemini-2.0-flash-lite", "model_tier": model_tier or "cheap"}

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)
    response = client.post(
        "/v1/blueprints/generate",
        headers=_headers(),
        json={"prompt": "build flow", "strict": True, "max_repairs": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["reprompted"] is True
    assert payload["repair_attempts"] == 1
    assert payload["ok"] is True
    assert call_count["n"] == 2


def test_generate_includes_observability_fields(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    async def _fake_draft(
        self,
        prompt: str,
        *,
        model_tier: str | None = None,
        stock_snapshot=None,
        domain: str | None = None,
    ):
        return _valid_blueprint(), {
            "model_name": "gemini-2.0-flash-lite",
            "model_tier": model_tier or "cheap",
            "provider_request_id": "req_123",
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            "cost": {"credits": 1},
        }

    monkeypatch.setattr("app.api.agent_integration.SagaArchitect.draft_blueprint", _fake_draft)
    response = client.post(
        "/v1/blueprints/generate",
        headers=_headers(),
        json={"prompt": "build flow", "domain": "neoeats"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["effective_model_name"] == "gemini-2.0-flash-lite"
    assert payload["effective_model_tier"] == "cheap"
    assert isinstance(payload["elapsed_ms"], int)
    assert payload["elapsed_ms"] >= 0
    assert payload["provider_request_id"] == "req_123"
    assert payload["usage"]["total_tokens"] == 20
    assert payload["cost"] == {"credits": 1}
