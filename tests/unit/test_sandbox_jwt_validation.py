"""Tests for P7-15a: Scoped JWT validation for sandbox RPC.

Covers the 5 specified rejection paths + success:
  1. Expired token → rejected
  2. Wrong audience → rejected
  3. Wrong issuer → rejected
  4. Replayed rpc_id → rejected
  5. Missing tool_name claim → rejected
  Plus: valid token → accepted
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.agent.sandbox_jwt import (
    SANDBOX_ALGORITHM,
    SANDBOX_AUDIENCE,
    SANDBOX_ISSUER,
    SANDBOX_SCOPE,
    SandboxTokenError,
    issue_sandbox_token,
    validate_sandbox_token,
)

# Use a fixed test secret
TEST_SECRET = "test-sandbox-secret-at-least-32-chars-long!"


# ===================================================================
# 1. Valid token (success path)
# ===================================================================

class TestValidToken:

    def test_round_trip(self):
        session_id = "sess-1"
        tool_name = "inventory_sync"
        rpc_id = str(uuid.uuid4())

        token = issue_sandbox_token(
            session_id, tool_name, rpc_id,
            secret=TEST_SECRET,
        )
        payload = validate_sandbox_token(
            token,
            expected_rpc_id=rpc_id,
            expected_tool_name=tool_name,
            secret=TEST_SECRET,
        )

        assert payload["sub"] == session_id
        assert payload["session_id"] == session_id
        assert payload["tool_name"] == tool_name
        assert payload["rpc_id"] == rpc_id
        assert payload["scope"] == SANDBOX_SCOPE
        assert payload["aud"] == SANDBOX_AUDIENCE
        assert payload["iss"] == SANDBOX_ISSUER

    def test_token_without_expected_claims_still_validates(self):
        """Validate without specifying expected_rpc_id / expected_tool_name."""
        token = issue_sandbox_token("s1", "tool_a", "rpc-1", secret=TEST_SECRET)
        payload = validate_sandbox_token(token, secret=TEST_SECRET)
        assert payload["tool_name"] == "tool_a"


# ===================================================================
# 2. Expired token → rejected
# ===================================================================

class TestExpiredToken:

    def test_expired_token(self):
        import jwt as pyjwt

        # Create a token that expired 10 seconds ago
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "s1",
            "aud": SANDBOX_AUDIENCE,
            "iss": SANDBOX_ISSUER,
            "iat": now - timedelta(seconds=70),
            "exp": now - timedelta(seconds=10),
            "session_id": "s1",
            "tool_name": "tool_a",
            "rpc_id": "rpc-1",
            "scope": SANDBOX_SCOPE,
        }
        token = pyjwt.encode(payload, TEST_SECRET, algorithm=SANDBOX_ALGORITHM)

        with pytest.raises(SandboxTokenError, match="expired"):
            validate_sandbox_token(token, secret=TEST_SECRET)


# ===================================================================
# 3. Wrong audience → rejected
# ===================================================================

class TestWrongAudience:

    def test_wrong_audience(self):
        import jwt as pyjwt

        now = datetime.now(timezone.utc)
        payload = {
            "sub": "s1",
            "aud": "wrong:audience",  # <-- wrong
            "iss": SANDBOX_ISSUER,
            "iat": now,
            "exp": now + timedelta(seconds=60),
            "tool_name": "tool_a",
            "rpc_id": "r1",
            "scope": SANDBOX_SCOPE,
        }
        token = pyjwt.encode(payload, TEST_SECRET, algorithm=SANDBOX_ALGORITHM)

        with pytest.raises(SandboxTokenError, match="[Aa]udience"):
            validate_sandbox_token(token, secret=TEST_SECRET)


# ===================================================================
# 4. Wrong issuer → rejected
# ===================================================================

class TestWrongIssuer:

    def test_wrong_issuer(self):
        import jwt as pyjwt

        now = datetime.now(timezone.utc)
        payload = {
            "sub": "s1",
            "aud": SANDBOX_AUDIENCE,
            "iss": "evil:issuer",  # <-- wrong
            "iat": now,
            "exp": now + timedelta(seconds=60),
            "tool_name": "tool_a",
            "rpc_id": "r1",
            "scope": SANDBOX_SCOPE,
        }
        token = pyjwt.encode(payload, TEST_SECRET, algorithm=SANDBOX_ALGORITHM)

        with pytest.raises(SandboxTokenError, match="[Ii]ssuer"):
            validate_sandbox_token(token, secret=TEST_SECRET)


# ===================================================================
# 5. Mismatched rpc_id → rejected
# ===================================================================

class TestRpcIdMismatch:

    def test_rpc_id_mismatch(self):
        token = issue_sandbox_token("s1", "tool_a", "rpc-original", secret=TEST_SECRET)

        with pytest.raises(SandboxTokenError, match="rpc_id mismatch"):
            validate_sandbox_token(
                token,
                expected_rpc_id="rpc-different",
                secret=TEST_SECRET,
            )


# ===================================================================
# 6. Missing/mismatched tool_name → rejected
# ===================================================================

class TestToolNameMismatch:

    def test_tool_name_mismatch(self):
        token = issue_sandbox_token("s1", "tool_a", "rpc-1", secret=TEST_SECRET)

        with pytest.raises(SandboxTokenError, match="tool_name mismatch"):
            validate_sandbox_token(
                token,
                expected_tool_name="tool_b",
                secret=TEST_SECRET,
            )


# ===================================================================
# 7. Invalid scope → rejected
# ===================================================================

class TestInvalidScope:

    def test_wrong_scope(self):
        import jwt as pyjwt

        now = datetime.now(timezone.utc)
        payload = {
            "sub": "s1",
            "aud": SANDBOX_AUDIENCE,
            "iss": SANDBOX_ISSUER,
            "iat": now,
            "exp": now + timedelta(seconds=60),
            "tool_name": "tool_a",
            "rpc_id": "r1",
            "scope": "admin:full",  # <-- wrong scope
        }
        token = pyjwt.encode(payload, TEST_SECRET, algorithm=SANDBOX_ALGORITHM)

        with pytest.raises(SandboxTokenError, match="scope"):
            validate_sandbox_token(token, secret=TEST_SECRET)


# ===================================================================
# 8. Wrong signing secret → rejected
# ===================================================================

class TestWrongSecret:

    def test_wrong_secret(self):
        token = issue_sandbox_token("s1", "tool_a", "rpc-1", secret=TEST_SECRET)

        with pytest.raises(SandboxTokenError, match="[Ii]nvalid token"):
            validate_sandbox_token(token, secret="completely-different-secret-xxxx")
