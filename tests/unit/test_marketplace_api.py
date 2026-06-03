from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.marketplace_routes import build_marketplace_router
from app.api.modes import router as modes_router
from app.infrastructure.db.sqlite import DB


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    async def start_saga(self, *, action_id: str, saga_type: str, payload: dict, user_id: str):
        self.calls.append(
            {
                "action_id": action_id,
                "saga_type": saga_type,
                "payload": payload,
                "user_id": user_id,
            }
        )
        return "saga-marketplace-1"


def _build_client(monkeypatch, tmp_path) -> tuple[TestClient, _FakeOrchestrator]:
    monkeypatch.setenv("SEED_ADMIN_KEY", "market_admin")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "0")
    monkeypatch.setenv("SEED_API_KEY_PEPPER", "pepper")

    db = DB(str(tmp_path / "marketplace_api.db"))
    db.init_schema()

    app = FastAPI()
    app.include_router(modes_router)
    app.include_router(build_marketplace_router(db=db))

    orchestrator = _FakeOrchestrator()
    app.state.seed = SimpleNamespace(db=db)
    app.state.saga_orchestrator = orchestrator
    return TestClient(app), orchestrator


def test_marketplace_admin_catalog_and_reputation_flow(monkeypatch, tmp_path):
    client, _ = _build_client(monkeypatch, tmp_path)
    admin_headers = {"X-Admin-Key": "market_admin"}

    upsert = client.post(
        "/v1/admin/marketplace/modules",
        headers=admin_headers,
        json={
            "mode_id": "general_assistant",
            "display_name": "General Assistant",
            "description": "Public assistant listing",
            "visibility": "public",
            "sandbox_policy": {"allowed_capabilities": ["llm.generate"]},
            "billing_policy": {"revenue_share_creator_pct": 0.75},
        },
    )
    assert upsert.status_code == 200
    assert upsert.json()["module"]["mode_id"] == "general_assistant"

    modules = client.get("/v1/marketplace/modules")
    assert modules.status_code == 200
    assert any(item["mode_id"] == "general_assistant" for item in modules.json()["modules"])

    rating = client.post(
        "/v1/marketplace/modules/general_assistant/ratings",
        headers=admin_headers,
        json={"rating": 5, "review": "Great"},
    )
    assert rating.status_code == 200

    reputation = client.get("/v1/marketplace/modules/general_assistant/reputation")
    assert reputation.status_code == 200
    payload = reputation.json()["reputation"]
    assert payload["rating_count"] == 1
    assert payload["average_rating"] == 5.0


def test_marketplace_policy_is_enforced_in_modes_runtime(monkeypatch, tmp_path):
    client, orchestrator = _build_client(monkeypatch, tmp_path)
    admin_headers = {"X-Admin-Key": "market_admin"}

    upsert = client.post(
        "/v1/admin/marketplace/modules",
        headers=admin_headers,
        json={
            "mode_id": "general_assistant",
            "visibility": "public",
            "sandbox_policy": {"allowed_capabilities": ["llm.generate"]},
            "billing_policy": {"revenue_share_creator_pct": 0.8},
        },
    )
    assert upsert.status_code == 200

    blocked_run = client.post(
        "/v1/modes/general_assistant/run",
        headers=admin_headers,
        json={
            "control": {
                "requested_capabilities": ["llm.read"],
            },
            "data": {
                "user_request": "Summarize this text",
            },
        },
    )
    assert blocked_run.status_code == 400
    violations = blocked_run.json()["detail"]["violations"]
    assert "marketplace_sandbox_capability_denied:llm.read" in violations

    allowed_run = client.post(
        "/v1/modes/general_assistant/run",
        headers=admin_headers,
        json={
            "control": {
                "requested_capabilities": ["llm.generate"],
            },
            "data": {
                "user_request": "Summarize this text",
            },
        },
    )
    assert allowed_run.status_code == 200
    assert len(orchestrator.calls) == 1
    payload = orchestrator.calls[0]["payload"]
    assert payload["marketplace"]["mode_id"] == "general_assistant"
    assert payload["marketplace"]["revenue_share_creator_pct"] == 0.8

    usage = client.get(
        "/v1/admin/marketplace/modules/general_assistant/usage/export",
        headers=admin_headers,
        params={"hours": 24},
    )
    assert usage.status_code == 200
    assert usage.json()["event_count"] == 1


def test_marketplace_settlement_admin_endpoints(monkeypatch, tmp_path):
    client, _ = _build_client(monkeypatch, tmp_path)
    admin_headers = {"X-Admin-Key": "market_admin"}

    upsert = client.post(
        "/v1/admin/marketplace/modules",
        headers=admin_headers,
        json={
            "mode_id": "general_assistant",
            "visibility": "public",
            "owner_tenant_id": "tenant_alpha",
            "billing_policy": {
                "revenue_share_creator_pct": 0.8,
                "minimum_payout_credits": 1.0,
                "settlement_window_days": 30,
            },
        },
    )
    assert upsert.status_code == 200

    usage_event = client.post(
        "/v1/modes/general_assistant/run",
        headers=admin_headers,
        json={
            "control": {"requested_capabilities": ["llm.generate"]},
            "data": {"user_request": "Summarize this text"},
        },
    )
    assert usage_event.status_code == 200

    settlement = client.post(
        "/v1/admin/marketplace/settlements/run",
        headers=admin_headers,
        json={"run_id": "settlement_run_api_1", "mode_id": "general_assistant"},
    )
    assert settlement.status_code == 200
    settlement_payload = settlement.json()
    assert settlement_payload["created_count"] == 1

    payouts = client.get(
        "/v1/admin/marketplace/payouts",
        headers=admin_headers,
        params={"mode_id": "general_assistant"},
    )
    assert payouts.status_code == 200
    payout_rows = payouts.json()["payouts"]
    assert len(payout_rows) == 1
    payout_id = payout_rows[0]["payout_id"]
    assert payout_rows[0]["owner_tenant_id"] == "tenant_alpha"

    payout = client.get(
        f"/v1/admin/marketplace/payouts/{payout_id}",
        headers=admin_headers,
    )
    assert payout.status_code == 200
    assert payout.json()["payout"]["mode_id"] == "general_assistant"
