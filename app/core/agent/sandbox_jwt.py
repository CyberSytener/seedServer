"""Scoped JWT for sandbox RPC (Phase 7 — P7-15a).

Provides token issuance (API side) and validation (sandbox worker side)
for sandbox RPC authentication.

Key properties:
- Separate signing secret (``SEED_SANDBOX_JWT_SECRET``) from main JWT
- Audience: ``seed:sandbox`` (prevents cross-use with user JWTs)
- Issuer: ``seed:api``
- Short TTL: 60 seconds
- Custom claims: ``tool_name``, ``rpc_id``, ``session_id``
- Scope: ``agent:sandbox:execute`` only
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt as pyjwt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SANDBOX_AUDIENCE = "seed:sandbox"
SANDBOX_ISSUER = "seed:api"
SANDBOX_TOKEN_TTL_SECONDS = 60
SANDBOX_SCOPE = "agent:sandbox:execute"
SANDBOX_ALGORITHM = "HS256"

# Minimum secret length for HS256
MIN_SECRET_LENGTH = 32

# Default (insecure) secret for development only
_DEV_SECRET = "sandbox-dev-secret-do-not-use-in-production!!"


def _get_sandbox_secret() -> str:
    """Resolve the sandbox JWT signing secret."""
    return os.environ.get("SEED_SANDBOX_JWT_SECRET", _DEV_SECRET)


# ---------------------------------------------------------------------------
# Token issuance (API side)
# ---------------------------------------------------------------------------

def issue_sandbox_token(
    session_id: str,
    tool_name: str,
    rpc_id: str,
    *,
    secret: Optional[str] = None,
    ttl_seconds: int = SANDBOX_TOKEN_TTL_SECONDS,
) -> str:
    """Issue a scoped JWT for a single sandbox RPC call.

    Returns a signed JWT string.
    """
    signing_secret = secret or _get_sandbox_secret()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": session_id,
        "aud": SANDBOX_AUDIENCE,
        "iss": SANDBOX_ISSUER,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "session_id": session_id,
        "tool_name": tool_name,
        "rpc_id": rpc_id,
        "scope": SANDBOX_SCOPE,
    }

    return pyjwt.encode(payload, signing_secret, algorithm=SANDBOX_ALGORITHM)


# ---------------------------------------------------------------------------
# Token validation (sandbox worker side)
# ---------------------------------------------------------------------------

def validate_sandbox_token(
    token: str,
    *,
    expected_rpc_id: Optional[str] = None,
    expected_tool_name: Optional[str] = None,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a sandbox RPC token.

    Raises ``SandboxTokenError`` on any validation failure.
    Returns the decoded payload on success.
    """
    signing_secret = secret or _get_sandbox_secret()

    try:
        payload = pyjwt.decode(
            token,
            signing_secret,
            algorithms=[SANDBOX_ALGORITHM],
            audience=SANDBOX_AUDIENCE,
            issuer=SANDBOX_ISSUER,
        )
    except pyjwt.ExpiredSignatureError:
        raise SandboxTokenError("Token expired")
    except pyjwt.InvalidAudienceError:
        raise SandboxTokenError("Invalid audience")
    except pyjwt.InvalidIssuerError:
        raise SandboxTokenError("Invalid issuer")
    except pyjwt.InvalidTokenError as exc:
        raise SandboxTokenError(f"Invalid token: {exc}")

    # Verify custom claims
    if expected_rpc_id is not None and payload.get("rpc_id") != expected_rpc_id:
        raise SandboxTokenError(
            f"rpc_id mismatch: expected {expected_rpc_id}, got {payload.get('rpc_id')}"
        )
    if expected_tool_name is not None and payload.get("tool_name") != expected_tool_name:
        raise SandboxTokenError(
            f"tool_name mismatch: expected {expected_tool_name}, got {payload.get('tool_name')}"
        )
    if payload.get("scope") != SANDBOX_SCOPE:
        raise SandboxTokenError(f"Invalid scope: {payload.get('scope')}")

    return payload


class SandboxTokenError(Exception):
    """Raised when sandbox token validation fails."""
    pass
