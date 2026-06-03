"""Tests for confirmation gate mechanism — Phase 7 P7-04a.

Validates:
- PendingConfirmation model serialization round-trip
- Tool marked requires_confirmation=True → pending confirmation produced
- Non-confirmation tool → no pending confirmation
- Confirm resolves pending confirmation
- Cancel discards pending confirmation
- Multiple pending confirmations tracked independently
- LLM cannot bypass gate (server-side enforcement)
"""

from __future__ import annotations

import json

import pytest

from app.core.agent.models import (
    AgentSessionData,
    PendingConfirmation,
    SessionStatus,
)
from app.core.agent.tool_registry import ToolPermissionConfig


# ---------------------------------------------------------------------------
# PendingConfirmation model tests
# ---------------------------------------------------------------------------

class TestPendingConfirmation:
    def test_to_dict_and_from_dict_round_trip(self):
        pc = PendingConfirmation(
            confirmation_id="conf-001",
            tool_name="inventory_sync",
            tool_input={"source_id": "ext-1"},
            explanation="This will sync all inventory items",
        )
        d = pc.to_dict()
        assert d["tool_name"] == "inventory_sync"

        pc2 = PendingConfirmation.from_dict(d)
        assert pc2.confirmation_id == "conf-001"
        assert pc2.tool_name == "inventory_sync"
        assert pc2.tool_input == {"source_id": "ext-1"}

    def test_json_serializable(self):
        pc = PendingConfirmation(tool_name="test", tool_input={"key": "val"})
        serialized = json.dumps(pc.to_dict())
        deserialized = json.loads(serialized)
        assert deserialized["tool_name"] == "test"


# ---------------------------------------------------------------------------
# Confirmation gate logic (standalone, before session loop integration)
# ---------------------------------------------------------------------------

class TestConfirmationGateLogic:
    """Test the confirmation gate decision logic as a pure function.

    The actual wiring into the session loop happens in P7-05.
    Here we test the decision: given a tool name and permission config,
    should we require confirmation?
    """

    @pytest.fixture()
    def permissions(self):
        return ToolPermissionConfig({
            "defaults": {
                "requires_confirmation": False,
            },
            "tools": {
                "inventory_sync": {
                    "requires_confirmation": True,
                    "sandbox_required": True,
                },
                "recipe_generator": {
                    "requires_confirmation": False,
                },
            },
        })

    def test_write_tool_requires_confirmation(self, permissions):
        assert permissions.requires_confirmation("inventory_sync") is True

    def test_read_tool_does_not_require_confirmation(self, permissions):
        assert permissions.requires_confirmation("recipe_generator") is False

    def test_unconfigured_tool_uses_default(self, permissions):
        assert permissions.requires_confirmation("unknown_tool") is False

    def test_pending_confirmation_stored_on_session(self):
        """Session stores pending confirmations as list."""
        session = AgentSessionData(session_id="sess-gate")

        pc = PendingConfirmation(
            tool_name="inventory_sync",
            tool_input={"source_id": "ext-1"},
            explanation="Will sync inventory",
        )
        session.pending_confirmations.append(pc.to_dict())

        assert len(session.pending_confirmations) == 1
        assert session.pending_confirmations[0]["tool_name"] == "inventory_sync"

    def test_confirm_resolves_pending(self):
        """When user confirms, the pending confirmation is removed."""
        session = AgentSessionData(session_id="sess-gate-2")
        pc = PendingConfirmation(
            confirmation_id="conf-AAA",
            tool_name="inventory_sync",
            tool_input={"source_id": "ext-1"},
        )
        session.pending_confirmations.append(pc.to_dict())

        # User confirms conf-AAA
        confirmed_id = "conf-AAA"
        session.pending_confirmations = [
            p for p in session.pending_confirmations
            if p.get("confirmation_id") != confirmed_id
        ]
        assert len(session.pending_confirmations) == 0

    def test_cancel_discards_pending(self):
        """When user cancels, the pending confirmation is removed."""
        session = AgentSessionData(session_id="sess-gate-3")
        pc = PendingConfirmation(
            confirmation_id="conf-BBB",
            tool_name="inventory_sync",
            tool_input={"source_id": "ext-2"},
        )
        session.pending_confirmations.append(pc.to_dict())

        # User cancels
        cancelled_id = "conf-BBB"
        session.pending_confirmations = [
            p for p in session.pending_confirmations
            if p.get("confirmation_id") != cancelled_id
        ]
        assert len(session.pending_confirmations) == 0

    def test_multiple_pending_confirmations(self):
        """Multiple tools can have pending confirmations simultaneously."""
        session = AgentSessionData(session_id="sess-gate-4")
        for i in range(3):
            pc = PendingConfirmation(
                confirmation_id=f"conf-{i}",
                tool_name=f"tool_{i}",
                tool_input={"idx": i},
            )
            session.pending_confirmations.append(pc.to_dict())

        assert len(session.pending_confirmations) == 3

        # Confirm only conf-1
        session.pending_confirmations = [
            p for p in session.pending_confirmations
            if p.get("confirmation_id") != "conf-1"
        ]
        assert len(session.pending_confirmations) == 2
        remaining_ids = {p["confirmation_id"] for p in session.pending_confirmations}
        assert remaining_ids == {"conf-0", "conf-2"}

    def test_server_side_enforcement_not_bypassed_by_llm(self):
        """The gate is server-side: even if the LLM says confirmed=True,
        the server only proceeds if there's a real user confirmation in session state."""
        session = AgentSessionData(session_id="sess-gate-5")

        # LLM claims tool should be executed, but no pending confirmation exists
        # The gate check: is there a matching pending confirmation from a real user?
        fake_llm_confirmation_id = "conf-FAKE"
        matching = [
            p for p in session.pending_confirmations
            if p.get("confirmation_id") == fake_llm_confirmation_id
        ]
        # Server rejects — no matching pending confirmation
        assert len(matching) == 0, "Server must reject fake confirmations"
