from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.console import create_console_runtime_router
from app.core.saga_blueprints import BlueprintStatus, BlueprintStore, RunStore
from app.infrastructure.db.sqlite import DB


class _FakeOrchestrator:
    def __init__(self) -> None:
        self._counter = 0
        self.sagas: dict[str, dict] = {}

    async def start_saga(
        self,
        *,
        action_id: str,
        saga_type: str,
        payload: dict,
        user_id: str,
    ) -> str:
        self._counter += 1
        saga_id = f"saga-{self._counter}"
        now = datetime.now(timezone.utc).isoformat()
        if saga_type == "flow_executor":
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
            nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
            timeline = [
                {
                    "node_id": str(node.get("node_id") or f"node_{index}"),
                    "module_id": str(node.get("module_id") or "unknown"),
                    "status": "succeeded",
                    "elapsed_sec": 0.07,
                    "error": None,
                    "meta": {"output_keys": ["ok"]},
                }
                for index, node in enumerate(nodes)
                if isinstance(node, dict)
            ]
            self.sagas[saga_id] = {
                "saga_id": saga_id,
                "saga_type": saga_type,
                "state": "succeeded",
                "created_at": now,
                "updated_at": now,
                "steps": [
                    {
                        "name": item["node_id"],
                        "adapter_type": item["module_id"],
                        "status": "succeeded",
                        "elapsed_sec": item["elapsed_sec"],
                        "meta": item["meta"],
                    }
                    for item in timeline
                ],
                "result": {
                    "output": {
                        "flow_id": graph.get("flow_id"),
                        "node_count": len(timeline),
                    },
                    "score": 1.0,
                    "stop_reason": "ok",
                    "timeline": timeline,
                    "artifacts": [
                        {
                            "uri": "artifact://bb/flow-result.json",
                            "sha256": "flow123",
                            "kind": "compiled_mode_payload",
                        }
                    ],
                    "assertions": {"passed": True, "failures": []},
                },
            }
            return saga_id

        self.sagas[saga_id] = {
            "saga_id": saga_id,
            "saga_type": saga_type,
            "state": "succeeded",
            "created_at": now,
            "updated_at": now,
            "steps": [
                {
                    "name": "execute",
                    "adapter_type": "llm",
                    "status": "succeeded",
                    "elapsed_sec": 0.15,
                    "meta": {
                        "usage": {
                            "input_tokens": 12,
                            "output_tokens": 8,
                            "total_tokens": 20,
                        },
                        "cost": {"units": 0.42},
                    },
                }
            ],
            "result": {
                "artifacts": {
                    "final_response_ref": {
                        "uri": "artifact://aa/module-final.json",
                        "sha256": "abc123",
                        "kind": "final_response",
                    }
                }
            },
        }
        return saga_id

    async def get_saga_state(self, saga_id: str) -> dict | None:
        return self.sagas.get(saga_id)


def _headers() -> dict[str, str]:
    return {"X-Admin-Key": "test_admin", "Authorization": "Bearer seed_dummy"}


def _test_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_client() -> tuple[TestClient, FastAPI]:
    os.environ["SEED_ADMIN_KEY"] = "test_admin"
    app = FastAPI()
    app.include_router(create_console_runtime_router())
    app.state.seed = SimpleNamespace(db=object())
    app.state.saga_orchestrator = _FakeOrchestrator()
    app.state.console_blueprint_store = BlueprintStore()
    app.state.console_run_store = RunStore()
    return TestClient(app), app


def _build_client_with_db(db: object) -> tuple[TestClient, FastAPI]:
    os.environ["SEED_ADMIN_KEY"] = "test_admin"
    app = FastAPI()
    app.include_router(create_console_runtime_router())
    app.state.seed = SimpleNamespace(db=db)
    app.state.saga_orchestrator = _FakeOrchestrator()
    app.state.console_blueprint_store = BlueprintStore()
    app.state.console_run_store = RunStore()
    return TestClient(app), app


def test_modules_endpoints_list_and_get() -> None:
    client, _ = _build_client()

    list_response = client.get("/v1/modules", headers=_headers())
    assert list_response.status_code == 200
    modules = list_response.json()["modules"]
    assert any(item["module_id"] == "general_assistant" for item in modules)

    detail_response = client.get("/v1/modules/general_assistant", headers=_headers())
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["module_id"] == "general_assistant"
    assert isinstance(payload["input_schema"], dict)
    assert isinstance(payload["output_schema"], dict)


def test_module_run_lifecycle_and_artifacts() -> None:
    client, _ = _build_client()

    create_response = client.post(
        "/v1/runs",
        headers=_headers(),
        json={
            "target": {"type": "module", "id": "general_assistant"},
            "mode": "stub",
            "input": {"user_request": "Summarize this text"},
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    run_id = created["run_id"]
    assert created["target_type"] == "module"

    detail_response = client.get(f"/v1/runs/{run_id}", headers=_headers())
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "done"
    assert detail["metrics"]["tokens"] == 20

    artifacts_response = client.get(f"/v1/runs/{run_id}/artifacts", headers=_headers())
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["uri"].startswith("artifact://")

    events_response = client.get(f"/v1/runs/{run_id}/events", headers=_headers())
    assert events_response.status_code == 200
    assert events_response.headers["content-type"].startswith("text/event-stream")
    assert "run.completed" in events_response.text


def test_module_stub_run_falls_back_when_orchestrator_unavailable() -> None:
    client, app = _build_client()
    app.state.saga_orchestrator = None

    create_response = client.post(
        "/v1/runs",
        headers=_headers(),
        json={
            "target": {"type": "module", "id": "general_assistant"},
            "mode": "stub",
            "input": {"user_request": "Check local demo"},
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "done"
    assert created["target_id"] == "general_assistant"

    detail_response = client.get(f"/v1/runs/{created['run_id']}", headers=_headers())
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "done"
    assert detail["result"]["module_id"] == "general_assistant"
    assert detail["timeline"][0]["meta"]["fallback"] == "local_stub"


def test_flows_endpoints_and_flow_run_creation() -> None:
    client, app = _build_client()
    asyncio.run(
        app.state.console_blueprint_store.save(
            "flow_demo",
            {
                "name": "flow_demo",
                "version": "v1",
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {"user_id": {"from": "user_id"}},
                    },
                    {
                        "id": "job_scorer_1",
                        "block": "job_scorer",
                        "inputs": {
                            "user_id": {"from": "user_id"},
                            "jobs": {"from": "market_scanner_1.jobs"},
                        },
                    },
                ],
            },
            owner_id="admin",
            status=BlueprintStatus.DRAFT,
        )
    )

    flows_response = client.get("/v1/flows", headers=_headers())
    assert flows_response.status_code == 200
    assert any(item["flow_id"] == "flow_demo" for item in flows_response.json()["flows"])

    create_run_response = client.post(
        "/v1/runs",
        headers=_headers(),
        json={
            "target": {"type": "flow", "id": "flow_demo"},
            "mode": "stub",
            "input": {"user_id": "u1"},
        },
    )

    assert create_run_response.status_code == 200
    created = create_run_response.json()
    assert created["target_type"] == "flow"

    runs_response = client.get("/v1/runs?target_type=flow", headers=_headers())
    assert runs_response.status_code == 200
    runs = runs_response.json()["runs"]
    assert any(item["run_id"] == created["run_id"] for item in runs)

    run_detail = client.get(f"/v1/runs/{created['run_id']}", headers=_headers())
    assert run_detail.status_code == 200
    detail_payload = run_detail.json()
    assert detail_payload["status"] == "done"
    assert detail_payload["result"]["stop_reason"] == "ok"
    assert len(detail_payload["timeline"]) == 2

    stats_response = client.get("/v1/runs/module-stats?blueprint_name=flow_demo", headers=_headers())
    assert stats_response.status_code == 200
    module_stats = stats_response.json()["modules"]
    assert any(entry["block"] == "market_scanner" for entry in module_stats)


def test_compile_flow_creates_compiled_artifact_and_persists_flow() -> None:
    client, _ = _build_client()

    compile_response = client.post(
        "/v1/flows/compile",
        headers=_headers(),
        json={
            "flow_id": "compiled_demo",
            "version": "v2",
            "graph": {
                "nodes": [
                    {"node_id": "market_scanner_1", "module_id": "market_scanner", "config": {}},
                    {"node_id": "job_scorer_1", "module_id": "job_scorer", "config": {}},
                ],
                "edges": [
                    {
                        "from": "market_scanner_1",
                        "to": "job_scorer_1",
                        "mapping": {"jobs": "jobs"},
                    }
                ],
            },
            "assertions": {"required_nodes": ["market_scanner_1", "job_scorer_1"]},
            "save": True,
        },
    )
    assert compile_response.status_code == 200
    payload = compile_response.json()
    assert payload["flow_id"] == "compiled_demo"
    assert payload["version"] == "v2"
    assert payload["compiled_mode_payload_ref"]["uri"].startswith("artifact://")
    assert payload["saved"] is True

    flow_response = client.get("/v1/flows/compiled_demo", headers=_headers())
    assert flow_response.status_code == 200
    flow = flow_response.json()
    assert flow["flow_id"] == "compiled_demo"
    assert len(flow["nodes"]) == 2


def test_compile_flow_from_blueprint_preserves_inputs_and_params() -> None:
    client, _ = _build_client()

    compile_response = client.post(
        "/v1/flows/compile",
        headers=_headers(),
        json={
            "flow_id": "gallery_contract_demo",
            "version": "v1",
            "blueprint": {
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {
                            "user_id": {"from": "user_id"},
                            "persona": {"from": "persona"},
                        },
                        "params": {"limit": 3},
                    },
                    {
                        "id": "job_scorer_1",
                        "block": "job_scorer",
                        "inputs": {
                            "user_id": {"from": "user_id"},
                            "jobs": {"from": "market_scanner_1.jobs"},
                        },
                    },
                ]
            },
            "save": True,
        },
    )
    assert compile_response.status_code == 200

    flow_response = client.get("/v1/flows/gallery_contract_demo", headers=_headers())
    assert flow_response.status_code == 200
    flow = flow_response.json()
    first_node = flow["nodes"][0]
    assert first_node["config"]["inputs"]["user_id"]["from"] == "user_id"
    assert first_node["config"]["inputs"]["persona"]["from"] == "persona"
    assert first_node["config"]["params"]["limit"] == 3
    assert flow["edges"] == [
        {"from": "market_scanner_1", "to": "job_scorer_1", "mapping": {"jobs": "jobs"}}
    ]


def test_flow_sandbox_marks_saved_flow_as_sandboxed() -> None:
    client, _ = _build_client()

    compile_response = client.post(
        "/v1/flows/compile",
        headers=_headers(),
        json={
            "flow_id": "sandbox_status_demo",
            "version": "v1",
            "blueprint": {
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {"user_id": {"from": "user_id"}},
                    }
                ]
            },
            "save": True,
        },
    )
    assert compile_response.status_code == 200

    sandbox_response = client.post(
        "/v1/flows/sandbox_status_demo/sandbox",
        headers=_headers(),
    )
    assert sandbox_response.status_code == 200
    sandbox_payload = sandbox_response.json()
    assert sandbox_payload["status"] == BlueprintStatus.SANDBOXED.value
    assert sandbox_payload["dry_run"]["status"] == "succeeded"
    assert sandbox_payload["dry_run"]["run_id"]

    flow_response = client.get("/v1/flows/sandbox_status_demo", headers=_headers())
    assert flow_response.status_code == 200
    assert flow_response.json()["status"] == "sandboxed"


def test_flow_fallback_injects_user_id_from_auth_context(monkeypatch) -> None:
    prev_mode = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "1"
    client, app = _build_client()
    app.state.saga_orchestrator = None

    asyncio.run(
        app.state.console_blueprint_store.save(
            "flow_fallback_user_id",
            {
                "name": "flow_fallback_user_id",
                "version": "v1",
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {"user_id": {"from": "user_id"}},
                    }
                ],
            },
            owner_id="system",
            status=BlueprintStatus.DRAFT,
        )
    )

    captured: dict[str, dict] = {}

    async def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["payload"] = args[1]
        return {"status": "succeeded", "result": {}, "execution_trace": []}

    monkeypatch.setattr("app.api.console.utils._run_saga", _fake_run)

    try:
        response = client.post(
            "/v1/runs",
            headers=_test_headers("test_ctx-user|developer|runs:write"),
            json={
                "target": {"type": "flow", "id": "flow_fallback_user_id"},
                "mode": "stub",
                "input": {},
            },
        )
        assert response.status_code == 200
        assert captured["payload"]["user_id"] == "ctx-user"
    finally:
        if prev_mode is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev_mode


def test_real_run_requires_provider_scope_and_respects_budget_caps() -> None:
    prev_mode = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "1"
    client, app = _build_client()
    app.state.provider_profiles = {
        "default_real": {
            "id": "default_real",
            "enabled": True,
            "requires_scope": "providers:use:real",
            "daily_budget_units": 5.0,
            "per_run_cap_units": 2.0,
            "allowed_models": ["gpt-4.1-mini"],
            "redaction_policy": {"store_raw_response": False},
        }
    }

    asyncio.run(
        app.state.console_blueprint_store.save(
            "flow_real_gate",
            {
                "name": "flow_real_gate",
                "version": "v1",
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {"user_id": {"from": "user_id"}},
                    }
                ],
            },
            owner_id="system",
            status=BlueprintStatus.DRAFT,
        )
    )

    try:
        denied = client.post(
            "/v1/runs",
            headers=_test_headers("test_sim-user|user|runs:write"),
            json={
                "target": {"type": "flow", "id": "flow_real_gate"},
                "mode": "real",
                "budget": {"requested_units": 1.0},
                "input": {"user_id": "u1"},
            },
        )
        assert denied.status_code == 403
        denied_payload = denied.json()
        assert denied_payload["detail"]["error"] == "missing_scope"
        assert denied_payload["detail"]["required_scope"] == "providers:use:real"

        over_cap = client.post(
            "/v1/runs",
            headers=_test_headers("test_sim-user|developer|runs:write,providers:use:real"),
            json={
                "target": {"type": "flow", "id": "flow_real_gate"},
                "mode": "real",
                "budget": {"requested_units": 3.0},
                "input": {"user_id": "u1"},
            },
        )
        assert over_cap.status_code == 400

        allowed = client.post(
            "/v1/runs",
            headers=_test_headers("test_sim-user|developer|runs:write,providers:use:real"),
            json={
                "target": {"type": "flow", "id": "flow_real_gate"},
                "mode": "real",
                "provider_profile": "default_real",
                "budget": {"requested_units": 1.0},
                "input": {"user_id": "u1"},
            },
        )
        assert allowed.status_code == 200
        payload = allowed.json()
        assert payload["provider_profile"] == "default_real"
    finally:
        if prev_mode is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev_mode


def test_provider_profiles_crud_enforces_scope_and_supports_lifecycle() -> None:
    prev_mode = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "1"
    client, _ = _build_client()

    try:
        denied = client.put(
            "/v1/provider-profiles/dev_profile",
            headers=_test_headers("test_dev|developer|providers:read"),
            json={"enabled": True},
        )
        assert denied.status_code == 403

        created = client.put(
            "/v1/provider-profiles/dev_profile",
            headers=_test_headers("test_admin|admin|"),
            json={
                "enabled": True,
                "allowed_models": ["gpt-4.1-mini"],
                "daily_budget_units": 12.0,
                "per_run_cap_units": 3.0,
                "requires_scope": "providers:use:real",
            },
        )
        assert created.status_code == 200
        assert created.json()["operation"] == "created"

        fetched = client.get(
            "/v1/provider-profiles/dev_profile",
            headers=_test_headers("test_dev|developer|runs:write"),
        )
        assert fetched.status_code == 200
        assert fetched.json()["profile"]["id"] == "dev_profile"

        deleted = client.delete(
            "/v1/provider-profiles/dev_profile",
            headers=_test_headers("test_admin|admin|"),
        )
        assert deleted.status_code == 200

        missing = client.get(
            "/v1/provider-profiles/dev_profile",
            headers=_test_headers("test_dev|developer|runs:write"),
        )
        assert missing.status_code == 404
    finally:
        if prev_mode is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev_mode


def test_real_run_daily_budget_is_persistent_across_app_restart(tmp_path) -> None:
    prev_mode = os.environ.get("SEED_TEST_AUTH_MODE")
    os.environ["SEED_TEST_AUTH_MODE"] = "1"
    db_path = tmp_path / "console_runtime_budget.sqlite3"
    db1 = DB(str(db_path))
    db1.init_schema()
    client1, app1 = _build_client_with_db(db1)
    app1.state.provider_profiles = {
        "default_real": {
            "id": "default_real",
            "enabled": True,
            "requires_scope": "providers:use:real",
            "daily_budget_units": 1.0,
            "per_run_cap_units": 2.0,
        }
    }

    asyncio.run(
        app1.state.console_blueprint_store.save(
            "flow_budget_persist",
            {
                "name": "flow_budget_persist",
                "version": "v1",
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {"user_id": {"from": "user_id"}},
                    }
                ],
            },
            owner_id="system",
            status=BlueprintStatus.DRAFT,
        )
    )

    try:
        first = client1.post(
            "/v1/runs",
            headers=_test_headers("test_budget-user|developer|runs:write,providers:use:real"),
            json={
                "target": {"type": "flow", "id": "flow_budget_persist"},
                "mode": "real",
                "budget": {"requested_units": 0.7},
                "input": {"user_id": "u1"},
            },
        )
        assert first.status_code == 200
    finally:
        db1.close()

    db2 = DB(str(db_path))
    db2.init_schema()
    client2, app2 = _build_client_with_db(db2)
    app2.state.provider_profiles = {
        "default_real": {
            "id": "default_real",
            "enabled": True,
            "requires_scope": "providers:use:real",
            "daily_budget_units": 1.0,
            "per_run_cap_units": 2.0,
        }
    }
    asyncio.run(
        app2.state.console_blueprint_store.save(
            "flow_budget_persist",
            {
                "name": "flow_budget_persist",
                "version": "v1",
                "steps": [
                    {
                        "id": "market_scanner_1",
                        "block": "market_scanner",
                        "inputs": {"user_id": {"from": "user_id"}},
                    }
                ],
            },
            owner_id="system",
            status=BlueprintStatus.DRAFT,
        )
    )
    try:
        second = client2.post(
            "/v1/runs",
            headers=_test_headers("test_budget-user|developer|runs:write,providers:use:real"),
            json={
                "target": {"type": "flow", "id": "flow_budget_persist"},
                "mode": "real",
                "budget": {"requested_units": 0.5},
                "input": {"user_id": "u1"},
            },
        )
        assert second.status_code == 429
    finally:
        db2.close()
        if prev_mode is None:
            os.environ.pop("SEED_TEST_AUTH_MODE", None)
        else:
            os.environ["SEED_TEST_AUTH_MODE"] = prev_mode
