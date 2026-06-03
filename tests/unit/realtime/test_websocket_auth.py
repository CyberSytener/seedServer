import pytest

from app.core.security.jwt import JWTHandler


def test_jwt_handler_create_and_validate():
    try:
        handler = JWTHandler()
    except ImportError:
        pytest.skip("PyJWT not installed")

    token = handler.create_token("user_123")
    assert isinstance(token, str)

    payload = handler.validate_token(token)
    assert payload and payload.get("user_id") == "user_123"

    uid = handler.extract_user_id(token)
    assert uid == "user_123"


def test_jwt_handler_with_fake_jwt(monkeypatch):
    # Create a fake jwt object to exercise code paths even when PyJWT not installed
    import app.core.security.jwt as wsa

    class FakeJWT:
        class ExpiredSignatureError(Exception):
            pass
        class InvalidTokenError(Exception):
            pass
        def encode(self, payload, key, algorithm):
            return "fake-token"
        def decode(self, token, secret_key, algorithms, **kwargs):
            return {"user_id": "fake_user"}

    fake = FakeJWT()
    monkeypatch.setattr(wsa, 'jwt', fake)

    handler = JWTHandler()
    tok = handler.create_token('fake_user')
    assert tok == 'fake-token'
    assert handler.validate_token(tok)['user_id'] == 'fake_user'
    assert handler.extract_user_id(tok) == 'fake_user'

    # Test expired and invalid token handling
    def bad_decode(token, secret_key, algorithms=None, **kwargs):
        raise FakeJWT.ExpiredSignatureError()
    fake.decode = bad_decode
    assert handler.validate_token('any') is None
    def invalid_decode(token, secret_key, algorithms=None, **kwargs):
        raise FakeJWT.InvalidTokenError()
    fake.decode = invalid_decode
    assert handler.validate_token('any') is None

def test_jwt_handler_expired_token():
    try:
        handler = JWTHandler(token_expiry_hours=-1)
    except ImportError:
        pytest.skip("PyJWT not installed")

    token = handler.create_token("u2")
    assert handler.validate_token(token) is None
    assert handler.extract_user_id(token) is None


def test_jwt_handler_invalid_token_returns_none():
    try:
        handler = JWTHandler()
    except ImportError:
        pytest.skip("PyJWT not installed")

    assert handler.validate_token("not-a-token") is None
    assert handler.extract_user_id("not-a-token") is None

