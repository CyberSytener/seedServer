"""
JWT authentication utilities.

Core-safe implementation used by API and WebSocket layers.
"""

from __future__ import annotations

import os
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

try:
    import jwt
except ImportError:
    jwt = None


# Whitelist of allowed JWT signing algorithms (symmetric HMAC only).
_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})


class JWTHandler:
    """Validate JWT tokens for client authentication."""

    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str = "HS256",
        token_expiry_hours: int = 24,
        audience: str | None = None,
        issuer: str | None = None,
    ):
        if not jwt:
            raise ImportError("PyJWT required: pip install PyJWT")

        if algorithm not in _ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"Unsupported JWT algorithm '{algorithm}'. "
                f"Allowed: {sorted(_ALLOWED_JWT_ALGORITHMS)}"
            )
        self.algorithm = algorithm
        resolved_secret = (secret_key if secret_key is not None else os.getenv("JWT_SECRET_KEY", "")).strip()
        if not resolved_secret:
            raise RuntimeError("JWT_SECRET_KEY is required and must be non-empty")
        if len(resolved_secret) < 32:
            raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters for HS* algorithms")
        self.secret_key = resolved_secret
        self.token_expiry_hours = token_expiry_hours
        self.audience = audience or os.getenv("SEED_JWT_AUDIENCE", "seed-server")
        self.issuer = issuer or os.getenv("SEED_JWT_ISSUER", "seed-server")

    def create_token(
        self,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = {
            "sub": user_id,
            "user_id": user_id,  # backward compat
            "aud": self.audience,
            "iss": self.issuer,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=self.token_expiry_hours),
            **(metadata or {}),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                audience=self.audience,
                issuer=self.issuer,
            )
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    def extract_user_id(self, token: str) -> Optional[str]:
        payload = self.validate_token(token)
        return payload.get("user_id") if payload else None
