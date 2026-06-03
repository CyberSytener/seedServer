"""Tests for agent WebSocket message types (P0-32)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.api.ws.agent_types import (
    AGENT_MESSAGE_TYPES,
    AgentBudgetUpdate,
    AgentConfirmationRequest,
    AgentError,
    AgentFinal,
    AgentMessageType,
    AgentPartial,
    AgentStreamStart,
    AgentToolCallStart,
    AgentToolCallResult,
    AgentWebSocketMessage,
    parse_agent_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_ID = "agt_session_abc123"


# ---------------------------------------------------------------------------
# AgentMessageType enum
# ---------------------------------------------------------------------------


class TestAgentMessageType:
    """Enum value and string identity tests."""

    def test_all_types_are_strings(self):
        for t in AgentMessageType:
            assert isinstance(t.value, str)

    def test_agent_prefix(self):
        for t in AgentMessageType:
            assert t.value.startswith("agent.")

    def test_expected_count(self):
        assert len(AgentMessageType) == 8

    def test_lookup_map_matches_enum(self):
        assert set(AGENT_MESSAGE_TYPES.keys()) == {t.value for t in AgentMessageType}

    def test_enum_is_str_subclass(self):
        """AgentMessageType instances compare equal to their string value."""
        assert AgentMessageType.PARTIAL == "agent.partial"


# ---------------------------------------------------------------------------
# Serialisation / deserialisation round-trip
# ---------------------------------------------------------------------------


class TestAgentStreamStart:
    def test_defaults(self):
        msg = AgentStreamStart(agent_session_id=SESSION_ID)
        assert msg.type == AgentMessageType.STREAM_START
        assert msg.agent_session_id == SESSION_ID
        assert msg.message_id  # not empty
        assert msg.timestamp.tzinfo is not None

    def test_json_roundtrip(self):
        msg = AgentStreamStart(agent_session_id=SESSION_ID)
        data = json.loads(msg.model_dump_json())
        assert data["type"] == "agent.stream_start"
        restored = AgentStreamStart(**data)
        assert restored.agent_session_id == msg.agent_session_id


class TestAgentPartial:
    def test_fields(self):
        msg = AgentPartial(
            agent_session_id=SESSION_ID, content="Hello", index=0
        )
        assert msg.type == AgentMessageType.PARTIAL
        assert msg.content == "Hello"
        assert msg.index == 0

    def test_json_roundtrip(self):
        msg = AgentPartial(
            agent_session_id=SESSION_ID, content="chunk", index=5
        )
        data = json.loads(msg.model_dump_json())
        assert data["index"] == 5
        restored = AgentPartial(**data)
        assert restored.content == "chunk"


class TestAgentToolCallStart:
    def test_fields(self):
        msg = AgentToolCallStart(
            agent_session_id=SESSION_ID,
            tool_name="file_read",
            input_preview={"path": "main.py"},
        )
        assert msg.tool_name == "file_read"
        assert msg.input_preview == {"path": "main.py"}

    def test_optional_input_preview(self):
        msg = AgentToolCallStart(
            agent_session_id=SESSION_ID, tool_name="search"
        )
        assert msg.input_preview is None


class TestAgentToolCallResult:
    def test_fields(self):
        msg = AgentToolCallResult(
            agent_session_id=SESSION_ID,
            tool_name="file_read",
            output_summary="200 lines read",
            duration_ms=42.5,
            status="success",
        )
        assert msg.duration_ms == 42.5
        assert msg.status == "success"

    def test_error_status(self):
        msg = AgentToolCallResult(
            agent_session_id=SESSION_ID,
            tool_name="search",
            status="error",
            output_summary="timeout",
        )
        assert msg.status == "error"


class TestAgentConfirmationRequest:
    def test_fields(self):
        cid = str(uuid.uuid4())
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id=cid,
            tool_name="apply_patch",
            proposed_input={"file": "x.py", "patch": "..."},
            description="Apply patch to x.py",
        )
        assert msg.confirmation_id == cid
        assert msg.tool_name == "apply_patch"
        assert msg.description == "Apply patch to x.py"

    def test_json_roundtrip(self):
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id="cf-1",
            tool_name="delete",
            proposed_input={"target": "foo"},
        )
        data = json.loads(msg.model_dump_json())
        assert data["confirmation_id"] == "cf-1"
        restored = AgentConfirmationRequest(**data)
        assert restored.proposed_input == {"target": "foo"}


class TestAgentBudgetUpdate:
    def test_fields(self):
        snap = {"tokens_used": 1500, "tokens_remaining": 3500}
        msg = AgentBudgetUpdate(
            agent_session_id=SESSION_ID, budget_snapshot=snap
        )
        assert msg.budget_snapshot["tokens_remaining"] == 3500

    def test_empty_snapshot(self):
        msg = AgentBudgetUpdate(agent_session_id=SESSION_ID)
        assert msg.budget_snapshot == {}


class TestAgentFinal:
    def test_full_message(self):
        msg = AgentFinal(
            agent_session_id=SESSION_ID,
            text="Done!",
            artifacts=[{"type": "file", "path": "out.py"}],
            trace=[{"step": 1, "action": "read"}],
            budget_snapshot={"tokens_used": 2000},
            stopped_reason="completed",
        )
        assert msg.text == "Done!"
        assert len(msg.artifacts) == 1
        assert msg.stopped_reason == "completed"

    def test_defaults(self):
        msg = AgentFinal(agent_session_id=SESSION_ID)
        assert msg.text == ""
        assert msg.artifacts == []
        assert msg.trace == []
        assert msg.stopped_reason is None

    def test_json_roundtrip(self):
        msg = AgentFinal(
            agent_session_id=SESSION_ID,
            text="Result",
            artifacts=[{"data": 42}],
        )
        data = json.loads(msg.model_dump_json())
        restored = AgentFinal(**data)
        assert restored.text == "Result"
        assert restored.artifacts == [{"data": 42}]


class TestAgentError:
    def test_fields(self):
        msg = AgentError(
            agent_session_id=SESSION_ID,
            error="Rate limit exceeded",
            recoverable=True,
        )
        assert msg.error == "Rate limit exceeded"
        assert msg.recoverable is True

    def test_default_not_recoverable(self):
        msg = AgentError(
            agent_session_id=SESSION_ID, error="Fatal"
        )
        assert msg.recoverable is False

    def test_json_roundtrip(self):
        msg = AgentError(
            agent_session_id=SESSION_ID, error="oops", recoverable=True
        )
        data = json.loads(msg.model_dump_json())
        restored = AgentError(**data)
        assert restored.error == "oops"
        assert restored.recoverable is True


# ---------------------------------------------------------------------------
# parse_agent_message
# ---------------------------------------------------------------------------


class TestParseAgentMessage:
    def test_parse_each_type(self):
        """Every type in the enum can be parsed from a raw dict."""
        samples = {
            "agent.stream_start": {"agent_session_id": SESSION_ID},
            "agent.partial": {
                "agent_session_id": SESSION_ID,
                "content": "hi",
                "index": 0,
            },
            "agent.tool_call_start": {
                "agent_session_id": SESSION_ID,
                "tool_name": "read",
            },
            "agent.tool_call_result": {
                "agent_session_id": SESSION_ID,
                "tool_name": "read",
            },
            "agent.confirmation_request": {
                "agent_session_id": SESSION_ID,
                "confirmation_id": "c1",
                "tool_name": "edit",
            },
            "agent.budget_update": {"agent_session_id": SESSION_ID},
            "agent.final": {"agent_session_id": SESSION_ID},
            "agent.error": {
                "agent_session_id": SESSION_ID,
                "error": "boom",
            },
        }
        for type_str, fields in samples.items():
            data = {"type": type_str, **fields}
            msg = parse_agent_message(data)
            assert msg.type.value == type_str

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown agent message type"):
            parse_agent_message({"type": "agent.unknown"})

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="Unknown agent message type"):
            parse_agent_message({"agent_session_id": SESSION_ID})


# ---------------------------------------------------------------------------
# Union type
# ---------------------------------------------------------------------------


class TestAgentWebSocketMessageUnion:
    def test_union_covers_all_types(self):
        """The union type contains every model in the registry."""
        import typing

        args = typing.get_args(AgentWebSocketMessage)
        assert set(args) == set(AGENT_MESSAGE_TYPES.values())


# ---------------------------------------------------------------------------
# Interoperability with existing WS types
# ---------------------------------------------------------------------------


class TestInteropWithExistingTypes:
    """Ensure no conflicts with existing MessageType enum."""

    def test_no_overlap_with_existing_types(self):
        from app.api.ws.types import MessageType

        existing = {t.value for t in MessageType}
        agent = {t.value for t in AgentMessageType}
        assert existing.isdisjoint(agent), f"overlap: {existing & agent}"

    def test_message_id_is_uuid(self):
        msg = AgentPartial(
            agent_session_id=SESSION_ID, content="x", index=0
        )
        # Should be parseable as UUID
        uuid.UUID(msg.message_id)

    def test_timestamp_is_utc(self):
        msg = AgentStreamStart(agent_session_id=SESSION_ID)
        assert msg.timestamp.tzinfo is not None
        assert msg.timestamp.tzinfo == timezone.utc
