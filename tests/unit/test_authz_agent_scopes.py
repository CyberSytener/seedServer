"""Tests for Phase 7 agent-session scopes in ROLE_SCOPES and UnifiedAuthContext."""

from __future__ import annotations

import pytest

from app.core.authz import ROLE_SCOPES, UnifiedAuthContext

# ---------------------------------------------------------------------------
# Agent scope constants (Phase 7)
# ---------------------------------------------------------------------------
AGENT_SCOPES_ALL = {
    "agent:sessions",
    "agent:tools:read",
    "agent:tools:execute",
    "agent:context:read",
    "agent:persona:write",
    "agent:sandbox:execute",
}

AGENT_SCOPES_USER = {
    "agent:sessions",
    "agent:tools:read",
    "agent:context:read",
}

AGENT_SCOPES_DEVELOPER = {
    "agent:sessions",
    "agent:tools:read",
    "agent:tools:execute",
    "agent:context:read",
    "agent:persona:write",
}


# ---------------------------------------------------------------------------
# ROLE_SCOPES mapping verification
# ---------------------------------------------------------------------------
class TestRoleScopesAgentFamily:
    """Verify that each role includes the correct agent scopes."""

    def test_user_role_has_agent_read_scopes(self):
        user_scopes = ROLE_SCOPES["user"]
        for scope in AGENT_SCOPES_USER:
            assert scope in user_scopes, f"user role missing {scope}"

    def test_user_role_lacks_execute_and_write(self):
        user_scopes = ROLE_SCOPES["user"]
        assert "agent:tools:execute" not in user_scopes
        assert "agent:persona:write" not in user_scopes
        assert "agent:sandbox:execute" not in user_scopes

    def test_developer_role_has_full_agent_scopes(self):
        dev_scopes = ROLE_SCOPES["developer"]
        for scope in AGENT_SCOPES_DEVELOPER:
            assert scope in dev_scopes, f"developer role missing {scope}"

    def test_operator_role_has_full_agent_scopes(self):
        op_scopes = ROLE_SCOPES["operator"]
        for scope in AGENT_SCOPES_DEVELOPER:
            assert scope in op_scopes, f"operator role missing {scope}"

    def test_admin_role_has_wildcard(self):
        assert "*" in ROLE_SCOPES["admin"]


# ---------------------------------------------------------------------------
# UnifiedAuthContext.has_scope() behaviour with agent scopes
# ---------------------------------------------------------------------------
class TestUnifiedAuthContextAgentScopes:
    """Verify has_scope() works correctly for agent scope patterns."""

    def test_user_can_read_tools(self):
        ctx = UnifiedAuthContext(
            user_id="u1",
            role="user",
            scopes=ROLE_SCOPES["user"],
        )
        assert ctx.has_scope("agent:sessions")
        assert ctx.has_scope("agent:tools:read")
        assert ctx.has_scope("agent:context:read")

    def test_user_cannot_execute_tools(self):
        ctx = UnifiedAuthContext(
            user_id="u1",
            role="user",
            scopes=ROLE_SCOPES["user"],
        )
        assert not ctx.has_scope("agent:tools:execute")
        assert not ctx.has_scope("agent:persona:write")

    def test_developer_can_execute_tools(self):
        ctx = UnifiedAuthContext(
            user_id="d1",
            role="developer",
            scopes=ROLE_SCOPES["developer"],
        )
        assert ctx.has_scope("agent:tools:execute")
        assert ctx.has_scope("agent:persona:write")

    def test_admin_wildcard_covers_all_agent_scopes(self):
        ctx = UnifiedAuthContext(
            user_id="a1",
            role="admin",
            scopes=ROLE_SCOPES["admin"],
            is_admin=True,
        )
        for scope in AGENT_SCOPES_ALL:
            assert ctx.has_scope(scope), f"admin should have {scope} via wildcard"

    def test_prefix_wildcard_agent_star(self):
        """A scope like 'agent:*' should cover all agent sub-scopes."""
        ctx = UnifiedAuthContext(
            user_id="x1",
            role="user",
            scopes={"agent:*"},
        )
        for scope in AGENT_SCOPES_ALL:
            assert ctx.has_scope(scope), f"agent:* should cover {scope}"

    def test_agent_tools_wildcard(self):
        """agent:tools:* should cover agent:tools:read and agent:tools:execute."""
        ctx = UnifiedAuthContext(
            user_id="x1",
            role="user",
            scopes={"agent:tools:*"},
        )
        assert ctx.has_scope("agent:tools:read")
        assert ctx.has_scope("agent:tools:execute")
        # Should NOT cover unrelated scopes
        assert not ctx.has_scope("agent:sessions")
        assert not ctx.has_scope("agent:persona:write")
