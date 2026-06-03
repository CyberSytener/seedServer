from __future__ import annotations

from unittest.mock import patch

from tests.support.app_factory import create_test_app, route_signatures


def test_create_test_app_route_parity_with_create_app(monkeypatch, tmp_path):
    app_from_factory = create_test_app(monkeypatch, db_path=str(tmp_path / "factory.db"))

    with patch("app.infrastructure.monitoring.monitoring.metrics.init_metrics", lambda *args, **kwargs: None):
        from app.main import create_app

        app_direct = create_app()

    factory_routes = route_signatures(app_from_factory)
    direct_routes = route_signatures(app_direct)

    assert factory_routes == direct_routes
    assert ("POST", "/v1/users") in factory_routes
    assert ("GET", "/health") in factory_routes
