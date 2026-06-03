import pytest

import app.core.auth as auth


def test_verify_user_context_missing():
    assert auth.verify_user_context(None) is None


class DummyHandler:
    def __init__(self, payload):
        self._payload = payload

    def validate_token(self, token):
        return self._payload


def test_verify_user_context_with_token(monkeypatch):
    # Patch core JWT handler to avoid requiring PyJWT
    monkeypatch.setattr('app.core.security.jwt.JWTHandler', lambda: DummyHandler({"user_id": "user_123", "role":"user"}))

    res = auth.verify_user_context("Bearer faketoken")
    assert res is not None
    assert res["user_id"] == "user_123"
    assert res["role"] == "user"

