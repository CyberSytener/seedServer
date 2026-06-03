"""Tests for X-Request-ID middleware."""

import uuid

import pytest
from starlette.testclient import TestClient

from app.middleware.request_id import RequestIDMiddleware


# ---------------------------------------------------------------------------
# Minimal app fixture
# ---------------------------------------------------------------------------

def _make_app():
    """Return a tiny FastAPI app with RequestIDMiddleware installed."""
    from fastapi import FastAPI, Request

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping(request: Request):
        return {"request_id": getattr(request.state, "request_id", None)}

    return app


@pytest.fixture()
def client():
    return TestClient(_make_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generates_request_id_when_absent(client):
    """Response must contain X-Request-ID even without incoming header."""
    resp = client.get("/ping")
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-ID")
    assert rid is not None
    # Must be a valid UUID-4
    uuid.UUID(rid)


def test_forwards_client_request_id(client):
    """If the client sends X-Request-ID it must be echoed back unchanged."""
    custom_id = "my-trace-42"
    resp = client.get("/ping", headers={"X-Request-ID": custom_id})
    assert resp.headers["X-Request-ID"] == custom_id
    assert resp.json()["request_id"] == custom_id


def test_request_state_populated(client):
    """Handler should see request_id on request.state."""
    resp = client.get("/ping")
    body = resp.json()
    assert body["request_id"] is not None
    assert body["request_id"] == resp.headers["X-Request-ID"]


def test_empty_header_treated_as_absent(client):
    """Blank X-Request-ID header should be replaced with a UUID."""
    resp = client.get("/ping", headers={"X-Request-ID": "   "})
    rid = resp.headers["X-Request-ID"]
    # Should be a new UUID, not whitespace
    uuid.UUID(rid)
