"""Tests for FastAPI Depends() DI providers (Task 5.1)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_db, get_redis, get_settings_dep, get_hub, get_broker


def _make_app_with_state():
    """Create a minimal FastAPI app with seed state for DI testing."""
    app = FastAPI()

    class _Seed:
        db = MagicMock(name="db")
        redis = MagicMock(name="redis")
        settings = MagicMock(name="settings")
        queuehub = MagicMock(name="queuehub")
        broker = MagicMock(name="broker")

    app.state.seed = _Seed()
    return app


class TestDIProviders:
    def test_get_db(self):
        app = _make_app_with_state()

        @app.get("/test-db")
        def endpoint(request=None, db=None):
            return {"ok": True}

        # Use Depends in a real route
        from fastapi import Depends

        @app.get("/test-db-di")
        def endpoint_di(db=Depends(get_db)):
            return {"id": id(db)}

        client = TestClient(app)
        resp = client.get("/test-db-di")
        assert resp.status_code == 200
        assert resp.json()["id"] == id(app.state.seed.db)

    def test_get_redis(self):
        from fastapi import Depends
        app = _make_app_with_state()

        @app.get("/test-redis-di")
        def endpoint(r=Depends(get_redis)):
            return {"id": id(r)}

        client = TestClient(app)
        resp = client.get("/test-redis-di")
        assert resp.status_code == 200
        assert resp.json()["id"] == id(app.state.seed.redis)

    def test_get_settings_dep(self):
        from fastapi import Depends
        app = _make_app_with_state()

        @app.get("/test-settings-di")
        def endpoint(s=Depends(get_settings_dep)):
            return {"id": id(s)}

        client = TestClient(app)
        resp = client.get("/test-settings-di")
        assert resp.status_code == 200
        assert resp.json()["id"] == id(app.state.seed.settings)

    def test_get_hub(self):
        from fastapi import Depends
        app = _make_app_with_state()

        @app.get("/test-hub-di")
        def endpoint(h=Depends(get_hub)):
            return {"id": id(h)}

        client = TestClient(app)
        resp = client.get("/test-hub-di")
        assert resp.status_code == 200
        assert resp.json()["id"] == id(app.state.seed.queuehub)

    def test_get_broker(self):
        from fastapi import Depends
        app = _make_app_with_state()

        @app.get("/test-broker-di")
        def endpoint(b=Depends(get_broker)):
            return {"id": id(b)}

        client = TestClient(app)
        resp = client.get("/test-broker-di")
        assert resp.status_code == 200
        assert resp.json()["id"] == id(app.state.seed.broker)

    def test_override_db_in_tests(self):
        """Verify DI overrides work for test isolation."""
        from fastapi import Depends
        app = _make_app_with_state()

        mock_db = MagicMock(name="override_db")

        @app.get("/test-override")
        def endpoint(db=Depends(get_db)):
            return {"id": id(db)}

        app.dependency_overrides[get_db] = lambda: mock_db
        client = TestClient(app)
        resp = client.get("/test-override")
        assert resp.status_code == 200
        assert resp.json()["id"] == id(mock_db)

        # Clean up
        app.dependency_overrides.clear()
