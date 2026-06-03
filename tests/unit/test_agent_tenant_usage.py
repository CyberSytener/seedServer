"""Tests for P0-37: Real-time tenant usage recording from agent sessions.

Covers:
- _record_tenant_usage_fire_and_forget helper on AgentSession
- Idempotency key deduplication in record_usage()
- Fire-and-forget error resilience (recording failure never crashes agent)
- Skip behaviour when tenant_id is None
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.core.agent.models import AgentSessionData, SessionStatus
from app.core.agent.session import AgentSession


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_session_data(
    *,
    tenant_id: Optional[str] = "tenant-t1",
    project_id: Optional[str] = "proj-p1",
    user_id: str = "user-u1",
    session_id: str = "sess-001",
) -> AgentSessionData:
    return AgentSessionData(
        session_id=session_id,
        user_id=user_id,
        persona_id="seed",
        budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
        tool_scopes=["read"],
        status=SessionStatus.ACTIVE,
        tenant_id=tenant_id,
        project_id=project_id,
    )


def _make_agent_session(
    *,
    tenant_governance: Any = None,
) -> AgentSession:
    return AgentSession(
        session_store=MagicMock(),
        tool_registry=MagicMock(),
        action_router=MagicMock(),
        llm_service=MagicMock(),
        tenant_governance=tenant_governance,
    )


class FakeGovernance:
    """Fake TenantGovernanceService that records all calls."""

    def __init__(self, *, should_raise: bool = False):
        self.calls: List[Dict[str, Any]] = []
        self._should_raise = should_raise

    def record_usage(self, **kwargs: Any) -> Dict[str, Any]:
        if self._should_raise:
            raise RuntimeError("governance DB unavailable")
        self.calls.append(kwargs)
        return {"tenant_id": kwargs["tenant_id"], "allowed": True, "recorded_status": "ok"}


# ---------------------------------------------------------------------------
# Tests: _record_tenant_usage_fire_and_forget
# ---------------------------------------------------------------------------

class TestRecordTenantUsageHelper:
    """Unit tests for _record_tenant_usage_fire_and_forget."""

    def test_records_llm_usage(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data()

        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=1500.0,
            cost_usd=0.003,
            actor_id="user-u1",
            idempotency_key="sess-001:llm:0",
        )

        assert len(gov.calls) == 1
        call = gov.calls[0]
        assert call["tenant_id"] == "tenant-t1"
        assert call["operation"] == "agent_llm"
        assert call["quantity"] == 1500.0
        assert call["cost_usd"] == 0.003
        assert call["actor_id"] == "user-u1"
        assert call["project_id"] == "proj-p1"
        assert call["idempotency_key"] == "sess-001:llm:0"
        assert call["enforce_quotas"] is False

    def test_records_tool_call_usage(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data()

        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_tool_call",
            quantity=1.0,
            actor_id="user-u1",
            idempotency_key="sess-001:tool:read_file:123",
        )

        assert len(gov.calls) == 1
        assert gov.calls[0]["operation"] == "agent_tool_call"
        assert gov.calls[0]["quantity"] == 1.0

    def test_skips_when_no_tenant_id(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data(tenant_id=None)

        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=100.0,
        )

        assert len(gov.calls) == 0

    def test_skips_when_no_governance_service(self):
        agent = _make_agent_session(tenant_governance=None)
        session = _make_session_data()

        # Should not raise
        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=100.0,
        )

    def test_never_crashes_on_governance_error(self):
        gov = FakeGovernance(should_raise=True)
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data()

        # Should not raise, just log warning
        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=100.0,
        )

    def test_uses_session_user_id_as_fallback_actor(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data(user_id="fallback-user")

        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=50.0,
            actor_id=None,
        )

        assert gov.calls[0]["actor_id"] == "fallback-user"

    def test_passes_enforce_quotas_false(self):
        """Recording should never enforce quotas — that's P0-38."""
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data()

        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=100.0,
        )

        assert gov.calls[0]["enforce_quotas"] is False

    def test_multiple_calls_recorded(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data()

        for i in range(3):
            agent._record_tenant_usage_fire_and_forget(
                session=session,
                operation="agent_llm",
                quantity=float(100 * (i + 1)),
                idempotency_key=f"sess-001:llm:{i}",
            )

        assert len(gov.calls) == 3

    def test_empty_tenant_id_skipped(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        session = _make_session_data(tenant_id="")

        agent._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_llm",
            quantity=100.0,
        )

        assert len(gov.calls) == 0


# ---------------------------------------------------------------------------
# Tests: Idempotency in record_usage
# ---------------------------------------------------------------------------

class TestIdempotencyDedup:
    """Tests for idempotency_key dedup in TenantGovernanceService.record_usage()."""

    def _make_governance(self):
        from app.services.tenant_governance import TenantGovernanceService
        from unittest.mock import MagicMock as _Mock

        db = _Mock()
        db.execute = _Mock()
        db.fetch_one = _Mock(return_value=None)
        db.fetch_all = _Mock(return_value=[])

        gov = TenantGovernanceService(db)
        # Stub check_quota to return allowed
        gov.check_quota = _Mock(return_value={
            "allowed": True,
            "checks": [],
            "violations": [],
        })
        return gov, db

    def test_first_call_records(self):
        gov, db = self._make_governance()
        result = gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            quantity=100.0,
            idempotency_key="key-1",
        )
        assert result.get("deduplicated") is None
        assert result["tenant_id"] == "t1"
        assert db.execute.called

    def test_duplicate_key_deduplicates(self):
        gov, db = self._make_governance()
        gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            idempotency_key="key-dup",
        )
        db.execute.reset_mock()

        result = gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            idempotency_key="key-dup",
        )
        assert result["deduplicated"] is True
        assert result["idempotency_key"] == "key-dup"
        assert not db.execute.called  # no DB write for duplicate

    def test_different_keys_not_deduped(self):
        gov, db = self._make_governance()
        gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            idempotency_key="key-a",
        )
        db.execute.reset_mock()

        result = gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            idempotency_key="key-b",
        )
        assert result.get("deduplicated") is None
        assert db.execute.called

    def test_no_idempotency_key_always_records(self):
        gov, db = self._make_governance()
        # Reset call count after __init__ (schema setup calls execute)
        db.execute.reset_mock()
        for _ in range(3):
            result = gov.record_usage(
                tenant_id="t1",
                operation="agent_llm",
                actor_id="u1",
            )
            assert result.get("deduplicated") is None
        # Each record_usage does 1 INSERT + 1 audit INSERT = 2 calls
        assert db.execute.call_count == 6

    def test_idempotency_key_expires(self):
        gov, db = self._make_governance()
        gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            idempotency_key="key-expire",
        )

        # Manually expire the key by setting its timestamp far in the past
        gov._idempotency_keys["key-expire"] = time.time() - 7200  # 2 hours ago
        db.execute.reset_mock()

        result = gov.record_usage(
            tenant_id="t1",
            operation="agent_llm",
            actor_id="u1",
            idempotency_key="key-expire",
        )
        # Should NOT be deduplicated since the key expired
        assert result.get("deduplicated") is None
        assert db.execute.called


# ---------------------------------------------------------------------------
# Tests: tenant_governance param on AgentSession
# ---------------------------------------------------------------------------

class TestAgentSessionGovernanceParam:
    """AgentSession.__init__ accepts tenant_governance."""

    def test_default_none(self):
        agent = _make_agent_session()
        assert agent.tenant_governance is None

    def test_custom_governance(self):
        gov = FakeGovernance()
        agent = _make_agent_session(tenant_governance=gov)
        assert agent.tenant_governance is gov


# ---------------------------------------------------------------------------
# Tests: Integration — calls wired into session code
# ---------------------------------------------------------------------------

class TestUsageRecordingIntegration:
    """Verify that consume_llm and consume_tool_call sites call recording."""

    def test_llm_usage_call_site_exists(self):
        """Verify that the LLM call site in process_message invokes recording."""
        import inspect
        src = inspect.getsource(AgentSession.process_message)
        assert "_record_tenant_usage_fire_and_forget" in src
        assert 'operation="agent_llm"' in src

    def test_tool_usage_call_site_exists(self):
        """Verify that _execute_tool invokes recording."""
        import inspect
        src = inspect.getsource(AgentSession._execute_tool)
        assert "_record_tenant_usage_fire_and_forget" in src
        assert 'operation="agent_tool_call"' in src

    def test_idempotency_key_format_llm(self):
        """LLM idempotency key format: {session_id}:llm:{iteration}."""
        import inspect
        src = inspect.getsource(AgentSession.process_message)
        assert "session_id}:llm:{iteration}" in src

    def test_tool_idempotency_key_contains_session_and_tool(self):
        """Tool idempotency key contains session_id and tool_name."""
        import inspect
        src = inspect.getsource(AgentSession._execute_tool)
        assert "session.session_id}:tool:{tool_name}" in src
