"""Tests for JWT audience and issuer validation (Phase 4, Task 4.1)."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# Ensure a valid secret is available for all tests in this module.
_TEST_SECRET = "a" * 32

_ENV = {
    "JWT_SECRET_KEY": _TEST_SECRET,
    "SEED_JWT_AUDIENCE": "seed-server",
    "SEED_JWT_ISSUER": "seed-server",
}


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch):
    for k, v in _ENV.items():
        monkeypatch.setenv(k, v)


def _handler(**kwargs):
    from app.core.security.jwt import JWTHandler
    return JWTHandler(**kwargs)


# ---- Token creation includes aud / iss / sub ----

def test_create_token_includes_aud_iss_sub():
    h = _handler()
    token = h.create_token("user-1")
    payload = h.validate_token(token)
    assert payload is not None
    assert payload["aud"] == "seed-server"
    assert payload["iss"] == "seed-server"
    assert payload["sub"] == "user-1"
    assert payload["user_id"] == "user-1"  # backward compat


def test_create_token_custom_audience_issuer():
    h = _handler(audience="my-aud", issuer="my-iss")
    token = h.create_token("user-2")
    payload = h.validate_token(token)
    assert payload is not None
    assert payload["aud"] == "my-aud"
    assert payload["iss"] == "my-iss"


# ---- Validation rejects wrong aud / iss ----

def test_wrong_audience_rejected():
    h_create = _handler(audience="correct-aud", issuer="seed-server")
    token = h_create.create_token("u1")

    h_validate = _handler(audience="wrong-aud", issuer="seed-server")
    assert h_validate.validate_token(token) is None


def test_wrong_issuer_rejected():
    h_create = _handler(audience="seed-server", issuer="correct-iss")
    token = h_create.create_token("u1")

    h_validate = _handler(audience="seed-server", issuer="wrong-iss")
    assert h_validate.validate_token(token) is None


def test_missing_aud_in_token_rejected():
    """A token created without 'aud' must be rejected when audience is required."""
    import jwt as _jwt

    payload = {"user_id": "u1", "sub": "u1", "iss": "seed-server"}
    token = _jwt.encode(payload, _TEST_SECRET, algorithm="HS256")

    h = _handler()
    assert h.validate_token(token) is None


def test_missing_iss_in_token_rejected():
    """A token created without 'iss' must be rejected when issuer is required."""
    import jwt as _jwt

    payload = {"user_id": "u1", "sub": "u1", "aud": "seed-server"}
    token = _jwt.encode(payload, _TEST_SECRET, algorithm="HS256")

    h = _handler()
    assert h.validate_token(token) is None


# ---- extract_user_id still works ----

def test_extract_user_id():
    h = _handler()
    token = h.create_token("user-42")
    assert h.extract_user_id(token) == "user-42"


def test_extract_user_id_invalid_token():
    h = _handler()
    assert h.extract_user_id("garbage.token.here") is None
