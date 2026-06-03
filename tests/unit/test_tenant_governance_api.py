from __future__ import annotations

from fastapi.testclient import TestClient

from tests.support.app_factory import create_test_app


def _build_client(monkeypatch, tmp_path) -> TestClient:
    app = create_test_app(
        monkeypatch,
        db_path=str(tmp_path / "tenant_governance.db"),
        env_overrides={
            "SEED_ADMIN_KEY": "tenant_admin_key",
            "SEED_ENABLE_LEGACY_X_USER_ID": "0",
            "SEED_METRICS_ENABLED": "0",
        },
    )
    return TestClient(app)


def test_tenant_governance_admin_flow(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    headers = {"X-Admin-Key": "tenant_admin_key"}

    tenant_resp = client.post(
        "/v1/admin/tenants",
        headers=headers,
        json={"tenant_id": "tenant_alpha", "display_name": "Tenant Alpha"},
    )
    assert tenant_resp.status_code == 200
    assert tenant_resp.json()["tenant"]["tenant_id"] == "tenant_alpha"

    project_resp = client.post(
        "/v1/admin/tenants/tenant_alpha/projects",
        headers=headers,
        json={"project_id": "proj_a", "display_name": "Project A"},
    )
    assert project_resp.status_code == 200
    assert project_resp.json()["project"]["project_id"] == "proj_a"

    role_resp = client.post(
        "/v1/admin/tenants/tenant_alpha/roles",
        headers=headers,
        json={"project_id": "proj_a", "user_id": "user_1", "role": "operator"},
    )
    assert role_resp.status_code == 200
    membership = role_resp.json()["membership"]
    assert membership["user_id"] == "user_1"
    assert membership["role"] == "operator"

    quota_resp = client.post(
        "/v1/admin/tenants/tenant_alpha/quotas",
        headers=headers,
        json={
            "project_id": "proj_a",
            "operation": "send_email",
            "metric": "quantity",
            "window": "day",
            "limit_value": 2,
            "hard_limit": True,
        },
    )
    assert quota_resp.status_code == 200
    quota = quota_resp.json()["quota"]
    assert quota["limit_value"] == 2.0

    check_before = client.post(
        "/v1/admin/tenants/tenant_alpha/usage/check",
        headers=headers,
        json={"project_id": "proj_a", "operation": "send_email", "quantity": 1},
    )
    assert check_before.status_code == 200
    assert check_before.json()["allowed"] is True

    record_ok = client.post(
        "/v1/admin/tenants/tenant_alpha/usage/record",
        headers=headers,
        json={"project_id": "proj_a", "operation": "send_email", "quantity": 2},
    )
    assert record_ok.status_code == 200
    assert record_ok.json()["recorded_status"] == "ok"

    check_after = client.post(
        "/v1/admin/tenants/tenant_alpha/usage/check",
        headers=headers,
        json={"project_id": "proj_a", "operation": "send_email", "quantity": 1},
    )
    assert check_after.status_code == 200
    assert check_after.json()["allowed"] is False

    blocked = client.post(
        "/v1/admin/tenants/tenant_alpha/usage/record",
        headers=headers,
        json={"project_id": "proj_a", "operation": "send_email", "quantity": 1, "enforce_quotas": True},
    )
    assert blocked.status_code == 200
    assert blocked.json()["recorded_status"] == "blocked"

    usage_export = client.get(
        "/v1/admin/tenants/tenant_alpha/usage/export",
        headers=headers,
        params={"hours": 24, "project_id": "proj_a"},
    )
    assert usage_export.status_code == 200
    usage_payload = usage_export.json()
    assert usage_payload["events_count"] >= 2
    assert usage_payload["blocked_count"] >= 1
    assert "send_email" in usage_payload["totals_by_operation"]

    audit = client.get(
        "/v1/admin/tenants/tenant_alpha/audit",
        headers=headers,
        params={"project_id": "proj_a", "limit": 20},
    )
    assert audit.status_code == 200
    assert len(audit.json()["events"]) >= 1

    snapshot = client.get(
        "/v1/admin/tenants/tenant_alpha/governance",
        headers=headers,
    )
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["tenant"]["tenant_id"] == "tenant_alpha"
    assert any(project["project_id"] == "proj_a" for project in payload["projects"])


def test_tenant_governance_requires_admin(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    response = client.post(
        "/v1/admin/tenants",
        json={"tenant_id": "tenant_beta"},
    )
    assert response.status_code == 401

