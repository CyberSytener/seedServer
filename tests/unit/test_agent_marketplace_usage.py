"""Tests for P0-39: Marketplace settlement integration for agent tool usage.

Covers:
- BlockMetadata.listing_id field
- BlockRegistry.register with listing_id
- _record_marketplace_usage helper on AgentSession
- Marketplace recording wired into _execute_tool
- Non-marketplace tools skip recording
- Errors in recording never crash agent
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from app.core.blocks import BlockMetadata, BlockRegistry, BlockBase
from app.core.agent.models import AgentSessionData, SessionStatus
from app.core.agent.session import AgentSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_data(
    *,
    tenant_id: Optional[str] = "tenant-t1",
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
    )


class FakeMarketplace:
    """Fake MarketplaceService that records calls."""

    def __init__(self, *, should_raise: bool = False):
        self.calls: List[Dict[str, Any]] = []
        self._should_raise = should_raise

    def record_usage_event(self, **kwargs: Any) -> Dict[str, Any]:
        if self._should_raise:
            raise RuntimeError("marketplace DB unavailable")
        self.calls.append(kwargs)
        return {"mode_id": kwargs.get("mode_id"), "event_type": kwargs.get("event_type")}


class StubBlock(BlockBase):
    DESCRIPTION = "test block"
    INPUT_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {}

    async def execute(self, context, inputs):
        return {"ok": True}


def _make_agent_session(
    *,
    marketplace_service: Any = None,
    block_registry: Optional[BlockRegistry] = None,
) -> AgentSession:
    from app.core.agent.tool_registry import ToolRegistry

    br = block_registry or BlockRegistry()
    tr = ToolRegistry(br)

    return AgentSession(
        session_store=MagicMock(),
        tool_registry=tr,
        action_router=MagicMock(),
        llm_service=MagicMock(),
        marketplace_service=marketplace_service,
    )


# ---------------------------------------------------------------------------
# Tests: BlockMetadata listing_id
# ---------------------------------------------------------------------------

class TestBlockMetadataListingId:
    """BlockMetadata has an optional listing_id field."""

    def test_default_none(self):
        meta = BlockMetadata(
            name="test",
            description="desc",
            input_schema={},
            output_schema={},
        )
        assert meta.listing_id is None

    def test_explicit_listing_id(self):
        meta = BlockMetadata(
            name="test",
            description="desc",
            input_schema={},
            output_schema={},
            listing_id="mp-listing-123",
        )
        assert meta.listing_id == "mp-listing-123"

    def test_frozen(self):
        meta = BlockMetadata(
            name="test",
            description="desc",
            input_schema={},
            output_schema={},
            listing_id="mp-1",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.listing_id = "mp-2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: BlockRegistry.register with listing_id
# ---------------------------------------------------------------------------

class TestBlockRegistryListingId:
    """BlockRegistry.register passes listing_id through."""

    def test_register_without_listing_id(self):
        br = BlockRegistry()
        br.register("tool_a", StubBlock)
        meta = br.get_metadata("tool_a")
        assert meta.listing_id is None

    def test_register_with_listing_id(self):
        br = BlockRegistry()
        br.register("tool_b", StubBlock, listing_id="mp-xyz")
        meta = br.get_metadata("tool_b")
        assert meta.listing_id == "mp-xyz"

    def test_list_metadata_includes_listing_id(self):
        br = BlockRegistry()
        br.register("tool_c", StubBlock, listing_id="mp-abc")
        all_meta = br.list_metadata()
        assert any(m.listing_id == "mp-abc" for m in all_meta)


# ---------------------------------------------------------------------------
# Tests: _record_marketplace_usage
# ---------------------------------------------------------------------------

class TestRecordMarketplaceUsage:
    """Unit tests for _record_marketplace_usage helper."""

    def test_records_for_marketplace_tool(self):
        br = BlockRegistry()
        br.register("mp_tool", StubBlock, listing_id="listing-001")
        mp = FakeMarketplace()
        agent = _make_agent_session(marketplace_service=mp, block_registry=br)
        session = _make_session_data()

        agent._record_marketplace_usage(
            tool_name="mp_tool",
            session=session,
            user_id="user-u1",
        )

        assert len(mp.calls) == 1
        call = mp.calls[0]
        assert call["mode_id"] == "listing-001"
        assert call["consumer_user_id"] == "user-u1"
        assert call["event_type"] == "agent_tool_call"
        assert call["metadata"]["session_id"] == "sess-001"
        assert call["metadata"]["tool_name"] == "mp_tool"

    def test_skips_non_marketplace_tool(self):
        br = BlockRegistry()
        br.register("local_tool", StubBlock)  # no listing_id
        mp = FakeMarketplace()
        agent = _make_agent_session(marketplace_service=mp, block_registry=br)
        session = _make_session_data()

        agent._record_marketplace_usage(
            tool_name="local_tool",
            session=session,
        )

        assert len(mp.calls) == 0

    def test_skips_when_no_marketplace_service(self):
        br = BlockRegistry()
        br.register("mp_tool", StubBlock, listing_id="listing-002")
        agent = _make_agent_session(marketplace_service=None, block_registry=br)
        session = _make_session_data()

        # Should not raise
        agent._record_marketplace_usage(
            tool_name="mp_tool",
            session=session,
        )

    def test_never_crashes_on_marketplace_error(self):
        br = BlockRegistry()
        br.register("mp_tool", StubBlock, listing_id="listing-003")
        mp = FakeMarketplace(should_raise=True)
        agent = _make_agent_session(marketplace_service=mp, block_registry=br)
        session = _make_session_data()

        # Should not raise
        agent._record_marketplace_usage(
            tool_name="mp_tool",
            session=session,
        )

    def test_uses_session_user_id_fallback(self):
        br = BlockRegistry()
        br.register("mp_tool", StubBlock, listing_id="listing-004")
        mp = FakeMarketplace()
        agent = _make_agent_session(marketplace_service=mp, block_registry=br)
        session = _make_session_data(user_id="fallback-user")

        agent._record_marketplace_usage(
            tool_name="mp_tool",
            session=session,
            user_id=None,
        )

        assert mp.calls[0]["consumer_user_id"] == "fallback-user"

    def test_includes_tenant_id_in_metadata(self):
        br = BlockRegistry()
        br.register("mp_tool", StubBlock, listing_id="listing-005")
        mp = FakeMarketplace()
        agent = _make_agent_session(marketplace_service=mp, block_registry=br)
        session = _make_session_data(tenant_id="org-123")

        agent._record_marketplace_usage(
            tool_name="mp_tool",
            session=session,
        )

        assert mp.calls[0]["metadata"]["tenant_id"] == "org-123"

    def test_unknown_tool_doesnt_crash(self):
        """If the tool isn't in the block registry, should not crash."""
        br = BlockRegistry()
        mp = FakeMarketplace()
        agent = _make_agent_session(marketplace_service=mp, block_registry=br)
        session = _make_session_data()

        # Should not raise (get_metadata raises ValueError, caught by try/except)
        agent._record_marketplace_usage(
            tool_name="nonexistent_tool",
            session=session,
        )
        assert len(mp.calls) == 0


# ---------------------------------------------------------------------------
# Tests: Integration — wired into _execute_tool
# ---------------------------------------------------------------------------

class TestMarketplaceInExecuteTool:
    """Verify _record_marketplace_usage is called from _execute_tool."""

    def test_call_site_exists(self):
        src = inspect.getsource(AgentSession._execute_tool)
        assert "_record_marketplace_usage" in src

    def test_marketplace_service_param_on_init(self):
        src = inspect.getsource(AgentSession.__init__)
        assert "marketplace_service" in src


# ---------------------------------------------------------------------------
# Tests: AgentSession marketplace_service param
# ---------------------------------------------------------------------------

class TestAgentSessionMarketplaceParam:

    def test_default_none(self):
        agent = _make_agent_session()
        assert agent.marketplace_service is None

    def test_custom_service(self):
        mp = FakeMarketplace()
        agent = _make_agent_session(marketplace_service=mp)
        assert agent.marketplace_service is mp
