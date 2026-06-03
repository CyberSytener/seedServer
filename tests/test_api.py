from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
import redis

from tests.support.app_factory import create_test_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")

    # Skip if Redis isn't available.
    rr = None
    try:
        rr = redis.Redis.from_url("redis://localhost:6379/15", decode_responses=False)
        rr.ping()
    except Exception:
        pytest.skip("Redis not available for integration tests")
    finally:
        if rr is not None:
            rr.close()

    app = create_test_app(
        monkeypatch,
        db_path=db_path,
        env_overrides={"SEED_ADMIN_KEY": ""},  # open signup in tests
    )

    with TestClient(app) as client:
        yield client


def test_create_user_and_limits(client: TestClient):
    user = client.post(
        "/v1/users",
        json={"user_id": "u1", "email": "u1@seed.dev", "meta": {}},
    ).json()
    assert "api_key" in user
    api_key = user["api_key"]

    r = client.get("/v1/limits", headers={"Authorization": f"Bearer {api_key}"})
    assert r.status_code == 200
    data = r.json()
    assert data["user_id"] == "u1"
    assert "plan" in data and "usage" in data


def test_me_requires_auth(client: TestClient):
    response = client.get("/v1/me")
    assert response.status_code == 401


def test_me_invalid_bearer_returns_401(client: TestClient):
    response = client.get(
        "/v1/me",
        headers={
            "Authorization": "Bearer invalid_key_for_golden_check",
            "X-User-ID": "legacy_should_not_rescue",
        },
    )
    assert response.status_code == 401


def test_me_returns_user_profile(client: TestClient):
    user = client.post(
        "/v1/users",
        json={"user_id": "u_me", "email": "u_me@seed.dev", "meta": {"segment": "desktop"}},
    ).json()
    api_key = user["api_key"]

    response = client.get("/v1/me", headers={"Authorization": f"Bearer {api_key}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "u_me"
    assert payload["email"] == "u_me@seed.dev"
    assert payload["is_admin"] is False
    assert payload["meta"]["segment"] == "desktop"
    assert "creditsBalance" in payload
    assert "creditsDailyLimit" in payload
    assert isinstance(payload["creditsBalance"], int)
    assert isinstance(payload["creditsDailyLimit"], int)


def test_models_requires_auth(client: TestClient):
    response = client.get("/v1/models")
    assert response.status_code == 401


def test_models_returns_catalog_for_desktop_preflight(client: TestClient):
    user = client.post(
        "/v1/users",
        json={"user_id": "u_models", "email": "u_models@seed.dev", "meta": {}},
    ).json()
    api_key = user["api_key"]

    response = client.get("/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    assert response.status_code == 200

    payload = response.json()
    assert "models" in payload
    assert isinstance(payload["models"], list)
    assert len(payload["models"]) > 0
    assert "defaultFastModel" in payload
    assert "defaultBatchModel" in payload

    first_model = payload["models"][0]
    assert "provider" in first_model
    assert "id" in first_model
    assert "label" in first_model
    assert "tier" in first_model
    assert "capabilities" in first_model
    assert "available" in first_model
    assert "pricing" in first_model
    assert "inputPer1kTokensUsd" in first_model["pricing"]
    assert "outputPer1kTokensUsd" in first_model["pricing"]
    assert "creditMultiplier" in first_model["pricing"]


def test_personas_is_public_without_auth(client: TestClient):
    response = client.get("/v1/personas")
    assert response.status_code == 200


def test_personas_invalid_bearer_returns_401(client: TestClient):
    response = client.get(
        "/v1/personas",
        headers={"Authorization": "Bearer invalid_key_for_personas"},
    )
    assert response.status_code == 401


def test_duplicate_email_conflict(client: TestClient):
    r1 = client.post("/v1/users", json={"user_id": "u1", "email": "dup@seed.dev", "meta": {}})
    assert r1.status_code == 200
    r2 = client.post("/v1/users", json={"user_id": "u2", "email": "dup@seed.dev", "meta": {}})
    assert r2.status_code == 409


def test_admin_user_creation_requires_configured_admin_key(client: TestClient):
    response = client.post(
        "/v1/users",
        json={"user_id": "u_admin", "email": "u_admin@seed.dev", "is_admin": True, "meta": {}},
    )
    assert response.status_code == 403
    assert response.json().get("detail") == "admin provisioning disabled"


def test_action_creates_job(client: TestClient):
    user = client.post("/v1/users", json={"user_id": "u1", "email": "u1@seed.dev", "meta": {}}).json()
    api_key = user["api_key"]

    r = client.post(
        "/v1/actions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"action": "fix", "text": "helo   world", "options": {}},
    )
    assert r.status_code == 200
    j = r.json()
    assert "job_id" in j
    job_id = j["job_id"]

    rj = client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {api_key}"})
    assert rj.status_code == 200
    job = rj.json()
    assert job["id"] == job_id
    assert job["status"] in ("queued", "running", "done", "failed")


def test_action_idempotency_replay_returns_same_job(client: TestClient):
    user = client.post("/v1/users", json={"user_id": "u1", "email": "u1@seed.dev", "meta": {}}).json()
    api_key = user["api_key"]

    payload = {"action": "fix", "text": "helo world", "options": {"temperature": 0.1}}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Idempotency-Key": "idem-replay-1",
    }

    first = client.post("/v1/actions", headers=headers, json=payload)
    assert first.status_code == 200
    first_job_id = first.json()["job_id"]

    second = client.post("/v1/actions", headers=headers, json=payload)
    assert second.status_code == 200
    second_job_id = second.json()["job_id"]

    assert first_job_id == second_job_id


def test_action_idempotency_key_payload_conflict(client: TestClient):
    user = client.post("/v1/users", json={"user_id": "u1", "email": "u1@seed.dev", "meta": {}}).json()
    api_key = user["api_key"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Idempotency-Key": "idem-conflict-1",
    }

    first = client.post(
        "/v1/actions",
        headers=headers,
        json={"action": "fix", "text": "same key payload A", "options": {}},
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/actions",
        headers=headers,
        json={"action": "fix", "text": "same key payload B", "options": {}},
    )
    assert second.status_code == 409
    assert second.json().get("detail") == "idempotency key already used with different payload"
