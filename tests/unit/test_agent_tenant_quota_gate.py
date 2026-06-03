"""Tests for P0-38: Quota enforcement as budget gate in agent loop.

Covers:
- Tenant quota check runs before budget pre_check
- Quota exceeded → stopped_reason="tenant_quota_exceeded"
- Quota OK → agent proceeds normally
- Cache prevents repeated governance calls in one process_message
- No tenant_id → quota check skipped
- No governance service → quota check skipped
- Governance error → fallback to allow
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentSession


# ---------------------------------------------------------------------------
# Helpers
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


class FakeQuotaGovernance:
    """Fake TenantGovernanceService that can be configured to allow or block."""

    def __init__(self, *, allowed: bool = True, should_raise: bool = False):
        self._allowed = allowed
        self._should_raise = should_raise
        self.check_quota_calls: List[Dict[str, Any]] = []
        self.record_usage_calls: List[Dict[str, Any]] = []

    def check_quota(self, **kwargs: Any) -> Dict[str, Any]:
        if self._should_raise:
            raise RuntimeError("governance DB unavailable")
        self.check_quota_calls.append(kwargs)
        return {
            "tenant_id": kwargs.get("tenant_id"),
            "allowed": self._allowed,
            "checks": [],
            "violations": [] if self._allowed else [{"metric": "cost_usd"}],
        }

    def record_usage(self, **kwargs: Any) -> Dict[str, Any]:
        self.record_usage_calls.append(kwargs)
        return {"allowed": True, "recorded_status": "ok"}


def _make_agent_session(
    *,
    tenant_governance: Any = None,
    session_data: Optional[AgentSessionData] = None,
) -> AgentSession:
    store = AsyncMock()
    store.get_session = AsyncMock(return_value=session_data or _make_session_data())
    store.get_messages = AsyncMock(return_value=[])
    store.append_message = AsyncMock()
    store.update_session = AsyncMock()

    tool_reg = MagicMock()
    tool_reg.list_tools_for_llm = MagicMock(return_value=[])
    tool_reg.permissions = MagicMock()
    tool_reg.permissions.sandbox_required = MagicMock(return_value=False)
    tool_reg.permissions.requires_confirmation = MagicMock(return_value=False)
    tool_reg.permissions.allowed_in_sandbox = MagicMock(return_value=True)
    tool_reg.is_tool_allowed = MagicMock(return_value=True)

    return AgentSession(
        session_store=store,
        tool_registry=tool_reg,
        action_router=MagicMock(),
        llm_service=MagicMock(),
        tenant_governance=tenant_governance,
    )


# ---------------------------------------------------------------------------
# Tests: Code structure verification
# ---------------------------------------------------------------------------

class TestQuotaGateCodeStructure:
    """Verify the quota gate code exists at the right location."""

    def test_quota_check_before_budget_precheck(self):
        """check_quota call appears before budget.pre_check() in source."""
        src = inspect.getsource(AgentSession.process_message)
        quota_pos = src.find("tenant_quota_exceeded")
        budget_pos = src.find("budget.pre_check()")
        assert quota_pos > 0, "tenant_quota_exceeded not found in process_message"
        assert budget_pos > 0, "budget.pre_check() not found"
        assert quota_pos < budget_pos, "quota check should appear before budget pre_check"

    def test_quota_cache_variable_exists(self):
        """Quota cache variable declared in process_message."""
        src = inspect.getsource(AgentSession.process_message)
        assert "_tenant_quota_cache" in src

    def test_error_emit_for_quota_exceeded(self):
        """tenant_quota_exceeded triggers emit_error."""
        src = inspect.getsource(AgentSession.process_message)
        assert 'stopped_reason == "tenant_quota_exceeded"' in src


# ---------------------------------------------------------------------------
# Tests: Quota gate behaviour (integration via process_message)
# ---------------------------------------------------------------------------

class TestQuotaGateBehaviour:
    """Test quota enforcement in the agent loop."""

    @pytest.mark.asyncio
    async def test_quota_exceeded_stops_agent(self):
        """When check_quota returns allowed=False → stopped_reason set."""
        gov = FakeQuotaGovernance(allowed=False)
        agent = _make_agent_session(tenant_governance=gov)
        response = await agent.process_message("sess-001", "Hello")

        assert response.stopped_reason == "tenant_quota_exceeded"
        assert "quota" in response.text.lower()
        assert len(gov.check_quota_calls) == 1

    @pytest.mark.asyncio
    async def test_quota_ok_proceeds(self):
        """When check_quota returns allowed=True → agent proceeds."""
        gov = FakeQuotaGovernance(allowed=True)
        agent = _make_agent_session(tenant_governance=gov)

        # Mock LLM to return a simple text (no tool calls)
        llm_result = MagicMock()
        llm_result.tokens_in = 100
        llm_result.tokens_out = 50
        llm_result.cost_usd = 0.001
        llm_result.text = "Hello! How can I help?"
        agent.llm_service.agenerate_with_metadata = AsyncMock(return_value=llm_result)

        response = await agent.process_message("sess-001", "Hello")

        assert response.stopped_reason is None or response.stopped_reason != "tenant_quota_exceeded"
        assert len(gov.check_quota_calls) == 1  # cached — only 1 call

    @pytest.mark.asyncio
    async def test_no_tenant_id_skips_quota(self):
        """Sessions without tenant_id skip quota check entirely."""
        gov = FakeQuotaGovernance(allowed=False)  # would block if checked
        session = _make_session_data(tenant_id=None)
        agent = _make_agent_session(tenant_governance=gov, session_data=session)

        # Mock LLM to return simple text
        llm_result = MagicMock()
        llm_result.tokens_in = 10
        llm_result.tokens_out = 10
        llm_result.cost_usd = 0.0
        llm_result.text = "Hi"
        agent.llm_service.agenerate_with_metadata = AsyncMock(return_value=llm_result)

        response = await agent.process_message("sess-001", "Hello")

        assert response.stopped_reason != "tenant_quota_exceeded"
        assert len(gov.check_quota_calls) == 0  # never called

    @pytest.mark.asyncio
    async def test_no_governance_service_skips(self):
        """No tenant_governance → quota check skipped, agent proceeds."""
        agent = _make_agent_session(tenant_governance=None)

        llm_result = MagicMock()
        llm_result.tokens_in = 10
        llm_result.tokens_out = 10
        llm_result.cost_usd = 0.0
        llm_result.text = "Hi"
        agent.llm_service.agenerate_with_metadata = AsyncMock(return_value=llm_result)

        response = await agent.process_message("sess-001", "Hello")
        assert response.stopped_reason != "tenant_quota_exceeded"

    @pytest.mark.asyncio
    async def test_governance_error_falls_through(self):
        """If check_quota raises, agent proceeds (allow on error)."""
        gov = FakeQuotaGovernance(should_raise=True)
        agent = _make_agent_session(tenant_governance=gov)

        llm_result = MagicMock()
        llm_result.tokens_in = 10
        llm_result.tokens_out = 10
        llm_result.cost_usd = 0.0
        llm_result.text = "Hello"
        agent.llm_service.agenerate_with_metadata = AsyncMock(return_value=llm_result)

        response = await agent.process_message("sess-001", "Hello")
        assert response.stopped_reason != "tenant_quota_exceeded"

    @pytest.mark.asyncio
    async def test_quota_cached_across_iterations(self):
        """check_quota is called only once even with multiple loop iterations."""
        gov = FakeQuotaGovernance(allowed=True)
        agent = _make_agent_session(tenant_governance=gov)

        call_count = 0

        async def fake_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.tokens_in = 10
            result.tokens_out = 10
            result.cost_usd = 0.0
            if call_count == 1:
                # Return a tool call on first iteration
                result.text = '<tool_call>{"name": "read_file", "arguments": {"path": "test.txt"}}</tool_call>'
            else:
                result.text = "Done reading the file."
            return result

        agent.llm_service.agenerate_with_metadata = fake_llm

        # Mock tool execution
        action_result = MagicMock()
        action_result.status = MagicMock(value="success")
        action_result.result = "file contents"
        action_result.error = None
        agent.action_router.execute_action = MagicMock(return_value=action_result)

        response = await agent.process_message("sess-001", "Read test.txt")

        # check_quota should only be called once (cached)
        assert len(gov.check_quota_calls) == 1

    @pytest.mark.asyncio
    async def test_quota_check_passes_correct_params(self):
        """Quota check uses session's tenant_id and project_id."""
        gov = FakeQuotaGovernance(allowed=False)
        session = _make_session_data(tenant_id="my-org", project_id="proj-xyz")
        agent = _make_agent_session(tenant_governance=gov, session_data=session)

        response = await agent.process_message("sess-001", "Hello")

        assert response.stopped_reason == "tenant_quota_exceeded"
        call = gov.check_quota_calls[0]
        assert call["tenant_id"] == "my-org"
        assert call["project_id"] == "proj-xyz"
        assert call["operation"] == "agent_cost_usd"


class TestQuotaExceededResponse:
    """Test the response shape when quota is exceeded."""

    @pytest.mark.asyncio
    async def test_response_text_mentions_quota(self):
        gov = FakeQuotaGovernance(allowed=False)
        agent = _make_agent_session(tenant_governance=gov)
        response = await agent.process_message("sess-001", "Hello")
        assert "quota" in response.text.lower()

    @pytest.mark.asyncio
    async def test_stopped_reason_is_tenant_quota_exceeded(self):
        gov = FakeQuotaGovernance(allowed=False)
        agent = _make_agent_session(tenant_governance=gov)
        response = await agent.process_message("sess-001", "Hello")
        assert response.stopped_reason == "tenant_quota_exceeded"

    @pytest.mark.asyncio
    async def test_no_tool_calls_when_quota_exceeded(self):
        """Agent should not make any tool calls when quota is exceeded."""
        gov = FakeQuotaGovernance(allowed=False)
        agent = _make_agent_session(tenant_governance=gov)
        response = await agent.process_message("sess-001", "Hello")

        # LLM should never be called
        if hasattr(agent.llm_service, 'agenerate_with_metadata'):
            assert not agent.llm_service.agenerate_with_metadata.called
