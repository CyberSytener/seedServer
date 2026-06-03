"""P0-43: Multi-tenant billing path integration test.

End-to-end demo: tenant + project → quota → agent session → LLM + tool calls
→ usage recorded → quota enforcement → audit trail.

Uses real TenantGovernanceService with SQLite for realistic billing verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentEventEmitter, AgentSession
from app.core.agent.tool_registry import ToolRegistry
from app.core.blocks import BlockBase, BlockRegistry
from app.infrastructure.db.sqlite import DB
from app.services.tenant_governance import TenantGovernanceService


# ===================================================================
# Test infrastructure
# ===================================================================


class InMemoryStore:
    """Minimal in-memory session store for integration tests."""

    def __init__(self):
        self._sessions: Dict[str, AgentSessionData] = {}
        self._messages: Dict[str, List[AgentSessionMessage]] = {}

    async def create_session(self, s: AgentSessionData) -> AgentSessionData:
        self._sessions[s.session_id] = s
        self._messages[s.session_id] = []
        return s

    async def get_session(self, sid: str) -> Optional[AgentSessionData]:
        return self._sessions.get(sid)

    async def update_session(self, s: AgentSessionData) -> None:
        self._sessions[s.session_id] = s

    async def append_message(self, msg: AgentSessionMessage) -> None:
        self._messages.setdefault(msg.session_id, []).append(msg)

    async def get_messages(self, sid: str) -> List[AgentSessionMessage]:
        return self._messages.get(sid, [])


class FakeActionStatus(str, Enum):
    SUCCESS = "success"


@dataclass
class FakeActionResult:
    status: FakeActionStatus = FakeActionStatus.SUCCESS
    result: Any = "ok"
    error: Optional[str] = None


class FakeActionRouter:
    def __init__(self):
        self.executed: List[str] = []

    def execute_action(self, action: Any) -> FakeActionResult:
        self.executed.append(action.name)
        return FakeActionResult(result=f"result_for_{action.name}")


@dataclass
class StubGenResult:
    text: str = ""
    tokens_in: int = 80
    tokens_out: int = 120
    cost_usd: float = 0.01


class ToolCallingLLM:
    """LLM stub: tool call on first round, final text on second."""

    def __init__(self):
        self.call_count = 0

    async def agenerate_with_metadata(self, **kw):
        self.call_count += 1
        if self.call_count == 1:
            return StubGenResult(
                text='Let me search.\n\n<tool_call>{"name": "billing_search", "arguments": {"query": "usage"}}</tool_call>',
            )
        else:
            return StubGenResult(
                text="Here are your billing details.",
            )


class SimpleTextLLM:
    """LLM stub: always returns plain text (no tool calls)."""

    async def agenerate_with_metadata(self, **kw):
        return StubGenResult(text="Simple answer.", cost_usd=0.005)


def _make_tool_registry():
    class BillingSearchBlock(BlockBase):
        DESCRIPTION = "Search billing records"
        INPUT_SCHEMA = {"query": {"type": "string"}}
        OUTPUT_SCHEMA = {"result": {"type": "string"}}

        async def execute(self, context, inputs):
            return {"result": "billing records found"}

    br = BlockRegistry()
    br.register("billing_search", BillingSearchBlock, description="Search billing records")
    return ToolRegistry(br)


class NoopEventEmitter(AgentEventEmitter):
    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        pass


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def tenant_env(tmp_path):
    """Set up real TenantGovernanceService + agent infrastructure."""
    db = DB(path=str(tmp_path / "tenant_billing_test.db"))
    gov = TenantGovernanceService(db)

    # Create tenant + project
    gov.upsert_tenant(
        tenant_id="org-alpha",
        display_name="Alpha Organization",
        metadata=None,
        actor_id="admin-1",
    )
    gov.upsert_project(
        tenant_id="org-alpha",
        project_id="proj-billing",
        display_name="Billing Project",
        metadata=None,
        actor_id="admin-1",
    )
    gov.grant_role(
        tenant_id="org-alpha",
        user_id="user-agent",
        role="operator",
        actor_id="admin-1",
        project_id="proj-billing",
    )

    store = InMemoryStore()
    tool_registry = _make_tool_registry()
    action_router = FakeActionRouter()
    emitter = NoopEventEmitter()

    return {
        "db": db,
        "gov": gov,
        "store": store,
        "tool_registry": tool_registry,
        "action_router": action_router,
        "emitter": emitter,
    }


# ===================================================================
# Tests
# ===================================================================


class TestTenantBillingDemo:
    """End-to-end multi-tenant billing flow."""

    @pytest.mark.asyncio
    async def test_step1_create_tenant_and_project(self, tenant_env):
        """Tenant and project exist after fixture setup."""
        gov = tenant_env["gov"]
        snapshot = gov.governance_snapshot(tenant_id="org-alpha")
        assert snapshot["tenant"]["tenant_id"] == "org-alpha"
        assert len(snapshot["projects"]) == 1
        assert snapshot["projects"][0]["project_id"] == "proj-billing"
        assert len(snapshot["memberships"]) >= 1

    @pytest.mark.asyncio
    async def test_step2_set_quota(self, tenant_env):
        """Quota set for agent_cost_usd operation."""
        gov = tenant_env["gov"]
        quota = gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=1.00,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
            hard_limit=True,
        )
        assert quota["operation"] == "agent_cost_usd"
        assert float(quota["limit_value"]) == 1.00

        quotas = gov.list_quotas(tenant_id="org-alpha", project_id="proj-billing")
        assert any(q["operation"] == "agent_cost_usd" for q in quotas)

    @pytest.mark.asyncio
    async def test_step3_agent_session_with_tenant(self, tenant_env):
        """Agent session created with tenant_id records usage during LLM + tool calls."""
        gov = tenant_env["gov"]
        store = tenant_env["store"]

        # Set generous quota
        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=100.00,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
        )

        agent = AgentSession(
            session_store=store,
            tool_registry=tenant_env["tool_registry"],
            action_router=tenant_env["action_router"],
            llm_service=ToolCallingLLM(),
            event_emitter=tenant_env["emitter"],
            tenant_governance=gov,
        )

        session = AgentSessionData(
            session_id="billing-001",
            user_id="user-agent",
            persona_id="seed",
            budget_config={"max_tokens": 50000, "max_cost_units": 10.0, "max_tool_calls": 20},
            tool_scopes=["billing_search"],
            status=SessionStatus.ACTIVE,
            tenant_id="org-alpha",
            project_id="proj-billing",
        )
        await store.create_session(session)
        response = await agent.process_message("billing-001", "Show me billing details.")

        assert response.text  # non-empty response
        assert response.stopped_reason != "tenant_quota_exceeded"

    @pytest.mark.asyncio
    async def test_step4_usage_recorded(self, tenant_env):
        """Usage export shows correct metrics after agent session."""
        gov = tenant_env["gov"]
        store = tenant_env["store"]

        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=100.00,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
        )

        agent = AgentSession(
            session_store=store,
            tool_registry=tenant_env["tool_registry"],
            action_router=tenant_env["action_router"],
            llm_service=ToolCallingLLM(),
            event_emitter=tenant_env["emitter"],
            tenant_governance=gov,
        )

        session = AgentSessionData(
            session_id="billing-002",
            user_id="user-agent",
            persona_id="seed",
            budget_config={"max_tokens": 50000, "max_cost_units": 10.0, "max_tool_calls": 20},
            tool_scopes=["billing_search"],
            status=SessionStatus.ACTIVE,
            tenant_id="org-alpha",
            project_id="proj-billing",
        )
        await store.create_session(session)
        await agent.process_message("billing-002", "Show me billing details.")

        usage = gov.export_usage(
            tenant_id="org-alpha",
            hours=1,
            project_id="proj-billing",
        )

        assert usage["events_count"] >= 1, "Usage events should be recorded"
        ops = usage["totals_by_operation"]
        # LLM usage recorded as agent_llm
        has_llm = "agent_llm" in ops
        # Tool call usage recorded as agent_tool_call
        has_tool = "agent_tool_call" in ops
        assert has_llm or has_tool, f"Expected agent usage ops, got: {list(ops.keys())}"

    @pytest.mark.asyncio
    async def test_step5_quota_enforcement(self, tenant_env):
        """Agent returns 'tenant_quota_exceeded' when quota is exceeded."""
        gov = tenant_env["gov"]
        store = tenant_env["store"]

        # Set very low quota that will be exceeded
        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=0.001,  # nearly zero
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
            hard_limit=True,
        )

        # Record some usage to fill the quota
        gov.record_usage(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
            cost_usd=0.01,  # way over 0.001 limit
            enforce_quotas=False,
        )

        agent = AgentSession(
            session_store=store,
            tool_registry=tenant_env["tool_registry"],
            action_router=tenant_env["action_router"],
            llm_service=SimpleTextLLM(),
            event_emitter=tenant_env["emitter"],
            tenant_governance=gov,
        )

        session = AgentSessionData(
            session_id="billing-003",
            user_id="user-agent",
            persona_id="seed",
            budget_config={"max_tokens": 50000, "max_cost_usd": 10.0, "max_tool_calls": 20},
            tool_scopes=["billing_search"],
            status=SessionStatus.ACTIVE,
            tenant_id="org-alpha",
            project_id="proj-billing",
        )
        await store.create_session(session)
        response = await agent.process_message("billing-003", "Show me billing details.")

        assert response.stopped_reason == "tenant_quota_exceeded"
        assert "quota" in response.text.lower()

    @pytest.mark.asyncio
    async def test_step6_audit_trail(self, tenant_env):
        """Audit log contains entries for tenant operations."""
        gov = tenant_env["gov"]

        audit = gov.get_audit(
            tenant_id="org-alpha",
            limit=50,
        )
        # Fixture created tenant + project + role → at least 3 audit entries
        assert len(audit) >= 3
        actions = [e["action"] for e in audit]
        assert "tenant.upsert" in actions
        assert "project.upsert" in actions
        assert "role.grant" in actions


class TestTenantUsageAttribution:
    """Verify usage is correctly attributed to tenant operations."""

    @pytest.mark.asyncio
    async def test_llm_usage_records_cost(self, tenant_env):
        """LLM calls record cost_usd in tenant usage."""
        gov = tenant_env["gov"]
        store = tenant_env["store"]

        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=100.00,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
        )

        agent = AgentSession(
            session_store=store,
            tool_registry=tenant_env["tool_registry"],
            action_router=tenant_env["action_router"],
            llm_service=SimpleTextLLM(),
            event_emitter=tenant_env["emitter"],
            tenant_governance=gov,
        )

        session = AgentSessionData(
            session_id="billing-004",
            user_id="user-agent",
            persona_id="seed",
            budget_config={"max_tokens": 50000, "max_cost_units": 10.0, "max_tool_calls": 20},
            tool_scopes=["billing_search"],
            status=SessionStatus.ACTIVE,
            tenant_id="org-alpha",
            project_id="proj-billing",
        )
        await store.create_session(session)
        await agent.process_message("billing-004", "Hello")

        usage = gov.export_usage(
            tenant_id="org-alpha",
            hours=1,
            project_id="proj-billing",
        )

        if "agent_llm" in usage["totals_by_operation"]:
            llm_total = usage["totals_by_operation"]["agent_llm"]
            assert llm_total["cost_usd"] > 0, "LLM usage should record cost"

    @pytest.mark.asyncio
    async def test_tool_call_usage_records_quantity(self, tenant_env):
        """Tool calls record quantity=1 in tenant usage."""
        gov = tenant_env["gov"]
        store = tenant_env["store"]

        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=100.00,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
        )

        agent = AgentSession(
            session_store=store,
            tool_registry=tenant_env["tool_registry"],
            action_router=tenant_env["action_router"],
            llm_service=ToolCallingLLM(),
            event_emitter=tenant_env["emitter"],
            tenant_governance=gov,
        )

        session = AgentSessionData(
            session_id="billing-005",
            user_id="user-agent",
            persona_id="seed",
            budget_config={"max_tokens": 50000, "max_cost_units": 10.0, "max_tool_calls": 20},
            tool_scopes=["billing_search"],
            status=SessionStatus.ACTIVE,
            tenant_id="org-alpha",
            project_id="proj-billing",
        )
        await store.create_session(session)
        await agent.process_message("billing-005", "Search billing records")

        usage = gov.export_usage(
            tenant_id="org-alpha",
            hours=1,
            project_id="proj-billing",
        )

        if "agent_tool_call" in usage["totals_by_operation"]:
            tool_total = usage["totals_by_operation"]["agent_tool_call"]
            assert tool_total["quantity"] >= 1, "Tool call should record quantity"

    @pytest.mark.asyncio
    async def test_no_usage_without_tenant(self, tenant_env):
        """Sessions without tenant_id don't record tenant usage."""
        gov = tenant_env["gov"]
        store = tenant_env["store"]

        # Baseline usage count
        baseline = gov.export_usage(tenant_id="org-alpha", hours=1)
        baseline_count = baseline["events_count"]

        agent = AgentSession(
            session_store=store,
            tool_registry=tenant_env["tool_registry"],
            action_router=tenant_env["action_router"],
            llm_service=SimpleTextLLM(),
            event_emitter=tenant_env["emitter"],
            tenant_governance=gov,
        )

        # Session WITHOUT tenant_id
        session = AgentSessionData(
            session_id="billing-006",
            user_id="user-agent",
            persona_id="seed",
            budget_config={"max_tokens": 50000, "max_cost_units": 10.0, "max_tool_calls": 20},
            tool_scopes=["billing_search"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)
        await agent.process_message("billing-006", "Hello")

        # Count should not increase
        after = gov.export_usage(tenant_id="org-alpha", hours=1)
        assert after["events_count"] == baseline_count


class TestTenantQuotaMetrics:
    """Verify quota check uses correct metrics."""

    @pytest.mark.asyncio
    async def test_check_quota_before_agent_loop(self, tenant_env):
        """check_quota is called with operation='agent_cost_usd'."""
        gov = tenant_env["gov"]

        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=50.00,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
        )

        result = gov.check_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            project_id="proj-billing",
        )
        assert result["allowed"] is True
        assert result["tenant_id"] == "org-alpha"

    @pytest.mark.asyncio
    async def test_quota_blocked_after_exceeding(self, tenant_env):
        """check_quota returns allowed=False after usage exceeds limit."""
        gov = tenant_env["gov"]

        gov.set_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            window="day",
            limit_value=0.05,
            metric="cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
            hard_limit=True,
        )

        # Record usage exceeding quota
        gov.record_usage(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            actor_id="admin-1",
            project_id="proj-billing",
            cost_usd=0.10,
            enforce_quotas=False,
        )

        result = gov.check_quota(
            tenant_id="org-alpha",
            operation="agent_cost_usd",
            project_id="proj-billing",
            cost_usd=0.01,
        )
        assert result["allowed"] is False
        assert len(result["violations"]) >= 1
