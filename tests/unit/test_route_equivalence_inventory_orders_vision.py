from __future__ import annotations

from collections import Counter
from unittest.mock import patch

from fastapi import FastAPI


def _route_counts(app: FastAPI) -> Counter[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            pairs.append((method, path))
    return Counter(pairs)


def _find_route_module(app: FastAPI, method: str, path: str) -> str | None:
    for route in app.routes:
        if getattr(route, "path", None) != path:
            continue
        methods = getattr(route, "methods", set())
        if method in methods:
            endpoint = getattr(route, "endpoint", None)
            return getattr(endpoint, "__module__", None)
    return None


def _find_websocket_route_modules(app: FastAPI, path: str) -> list[str | None]:
    modules: list[str | None] = []
    for route in app.routes:
        if getattr(route, "path", None) != path:
            continue
        methods = getattr(route, "methods", None)
        if methods:
            continue
        endpoint = getattr(route, "endpoint", None)
        modules.append(getattr(endpoint, "__module__", None))
    return modules


def test_inventory_orders_vision_routes_registered_once_and_via_extracted_router(monkeypatch, tmp_path):
    monkeypatch.setenv("SEED_DB_PATH", str(tmp_path / "route_eq_inventory_orders_vision.db"))
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

    with patch("app.infrastructure.monitoring.monitoring.metrics.init_metrics", lambda *args, **kwargs: None):
        from app.main import create_app

        app = create_app()

    expected_modules = {
        ("GET", "/api/v1/inventory/ledger"): "app.api.inventory_orders_vision_routes",
        ("POST", "/api/v1/inventory/extract"): "app.api.inventory_orders_vision_routes",
        ("POST", "/api/v1/inventory/items"): "app.api.inventory_orders_vision_routes",
        ("PATCH", "/api/v1/inventory/items/{item_id}"): "app.api.inventory_orders_vision_routes",
        ("DELETE", "/api/v1/inventory/items/{item_id}"): "app.api.inventory_orders_vision_routes",
        ("POST", "/api/v1/cooking/complete"): "app.api.inventory_orders_vision_routes",
        ("GET", "/api/v1/inventory/store"): "app.api.inventory_orders_vision_routes",
        ("POST", "/api/v1/orders/saga/init"): "app.api.inventory_orders_vision_routes",
        ("GET", "/api/v1/orders"): "app.api.inventory_orders_vision_routes",
        ("GET", "/api/v1/orders/{order_id}"): "app.api.inventory_orders_vision_routes",
        ("POST", "/api/v1/vision/analyze"): "app.api.inventory_orders_vision_routes",
    }

    counts = _route_counts(app)
    for route_key, module_name in expected_modules.items():
        assert counts[route_key] == 1, f"expected exactly one registration for {route_key}"
        registered_module = _find_route_module(app, route_key[0], route_key[1])
        assert (
            registered_module == module_name
        ), f"route {route_key} expected module {module_name}, got {registered_module}"

    ws_modules = _find_websocket_route_modules(app, "/api/v1/orders/stream")
    assert len(ws_modules) == 1, "expected exactly one websocket registration for /api/v1/orders/stream"
    assert ws_modules[0] == "app.api.inventory_orders_vision_routes"
