from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def _build_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SEED_DB_PATH", str(tmp_path / "chat_payload_contract.db"))
    monkeypatch.setenv("SEED_REDIS_URL", "redis://localhost:6379/15")
    monkeypatch.setenv("SEED_REDIS_NAMESPACE", "seed_test")
    monkeypatch.setenv("SEED_ADMIN_KEY", "test_admin_key_equiv")
    monkeypatch.setenv("SEED_API_KEY_PEPPER", "route_eq_pepper")
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_FAST", "stub")
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_BATCH", "stub")
    monkeypatch.setenv("SEED_METRICS_ENABLED", "0")
    monkeypatch.setenv("SEED_ENABLE_LEGACY_X_USER_ID", "0")
    monkeypatch.setenv("SEED_SEED_DEV_USERS_ON_STARTUP", "0")
    monkeypatch.setenv("SEED_DEV_CORS", "0")
    monkeypatch.setenv("JWT_SECRET_KEY", "route-equivalence-secret-key-32b")
    monkeypatch.setenv("SEED_TEST_AUTH_MODE", "1")

    with patch("app.infrastructure.monitoring.monitoring.metrics.init_metrics", lambda *args, **kwargs: None):
        from app.main import create_app

        app = create_app()
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer test_user|developer|runs:write,blueprints:write,catalog:read"}


def test_actions_invoke_cook_returns_recipe_card_v1_payload(monkeypatch, tmp_path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    payload = {
        "type": "action.request",
        "session_id": "session-1",
        "action": {
            "id": "action-1",
            "name": "chat",
            "args": {"message": "make recipe from what I have"},
        },
    }
    response = client.post("/api/v1/actions/invoke", headers=_headers(), json=payload)
    assert response.status_code == 200
    result = response.json().get("result") or {}
    flavor = result.get("flavor_architect")
    assert isinstance(flavor, list)
    assert len(flavor) >= 2
    first = flavor[0] if flavor else {}
    assert isinstance(first.get("ingredients"), list)
    assert isinstance(first.get("recipe_name"), str)
    assert isinstance(first.get("rationale"), str)
    recommendations = result.get("recommendations") or []
    assert isinstance(recommendations, list) and recommendations
    first_rec = recommendations[0]
    recipe_card = first_rec.get("recipe_card_v1") if isinstance(first_rec, dict) else None
    assert isinstance(recipe_card, dict)
    assert recipe_card.get("schema_version") == "recipe_card_v1"
    assert isinstance(recipe_card.get("ingredients"), list)
    assert isinstance(recipe_card.get("nutrition"), dict)
    assert isinstance(recipe_card.get("match_breakdown"), dict)


def test_api_chat_fallback_includes_flavor_architect_array(monkeypatch, tmp_path) -> None:
    client = _build_client(monkeypatch, tmp_path)
    response = client.post("/api/v1/chat", headers=_headers(), json={"message": "recipe please"})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("flavor_architect"), list)
