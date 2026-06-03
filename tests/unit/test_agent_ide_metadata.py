"""Tests for IDE-compatible agent session events (P0-34).

Verifies:
1. ``correlation_id`` and ``request_id`` present in all agent message types
2. ``file_references`` in AgentFinal, AgentToolCallResult, AgentConfirmationRequest
3. ``diff`` field in AgentConfirmationRequest for apply_patch
4. FileReference serialization
5. apply_patch confirmation gate integration
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

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
    FileReference,
    parse_agent_message,
)


SESSION_ID = "agt_ide_test"
CORR_ID = "corr-001"
REQ_ID = "req-001"


# ---------------------------------------------------------------------------
# FileReference
# ---------------------------------------------------------------------------


class TestFileReference:
    def test_minimal(self):
        ref = FileReference(path="src/main.py")
        assert ref.path == "src/main.py"
        assert ref.start_line is None
        assert ref.end_line is None
        assert ref.description is None

    def test_full(self):
        ref = FileReference(
            path="src/main.py",
            start_line=10,
            end_line=25,
            description="Main entry point",
        )
        assert ref.start_line == 10
        assert ref.end_line == 25

    def test_json_roundtrip(self):
        ref = FileReference(path="a.py", start_line=1, end_line=5, description="test")
        data = json.loads(ref.model_dump_json())
        restored = FileReference(**data)
        assert restored.path == "a.py"
        assert restored.start_line == 1


# ---------------------------------------------------------------------------
# correlation_id and request_id on ALL message types
# ---------------------------------------------------------------------------


class TestCorrelationAndRequestId:
    """Every agent message type must accept correlation_id and request_id."""

    ALL_TYPES_WITH_MINIMAL_ARGS: Dict[str, Dict[str, Any]] = {
        "agent.stream_start": {"agent_session_id": SESSION_ID},
        "agent.partial": {
            "agent_session_id": SESSION_ID,
            "content": "x",
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
        "agent.error": {"agent_session_id": SESSION_ID, "error": "fail"},
    }

    @pytest.mark.parametrize("type_str", list(ALL_TYPES_WITH_MINIMAL_ARGS.keys()))
    def test_accepts_correlation_and_request_ids(self, type_str: str):
        cls = AGENT_MESSAGE_TYPES[type_str]
        args = self.ALL_TYPES_WITH_MINIMAL_ARGS[type_str]
        msg = cls(**args, correlation_id=CORR_ID, request_id=REQ_ID)
        assert msg.correlation_id == CORR_ID
        assert msg.request_id == REQ_ID

    @pytest.mark.parametrize("type_str", list(ALL_TYPES_WITH_MINIMAL_ARGS.keys()))
    def test_defaults_to_none(self, type_str: str):
        cls = AGENT_MESSAGE_TYPES[type_str]
        args = self.ALL_TYPES_WITH_MINIMAL_ARGS[type_str]
        msg = cls(**args)
        assert msg.correlation_id is None
        assert msg.request_id is None

    @pytest.mark.parametrize("type_str", list(ALL_TYPES_WITH_MINIMAL_ARGS.keys()))
    def test_serializes_ids(self, type_str: str):
        cls = AGENT_MESSAGE_TYPES[type_str]
        args = self.ALL_TYPES_WITH_MINIMAL_ARGS[type_str]
        msg = cls(**args, correlation_id=CORR_ID, request_id=REQ_ID)
        data = json.loads(msg.model_dump_json())
        assert data["correlation_id"] == CORR_ID
        assert data["request_id"] == REQ_ID


# ---------------------------------------------------------------------------
# file_references on AgentFinal, AgentToolCallResult, AgentConfirmationRequest
# ---------------------------------------------------------------------------


class TestFileReferencesOnTypes:
    def test_agent_final_file_references(self):
        refs = [
            FileReference(path="src/main.py", start_line=1, end_line=10),
            FileReference(path="src/utils.py", description="Utils"),
        ]
        msg = AgentFinal(
            agent_session_id=SESSION_ID,
            text="Done",
            file_references=refs,
        )
        assert len(msg.file_references) == 2
        assert msg.file_references[0].path == "src/main.py"

    def test_agent_final_file_references_default_empty(self):
        msg = AgentFinal(agent_session_id=SESSION_ID)
        assert msg.file_references == []

    def test_agent_final_file_references_json_roundtrip(self):
        ref = FileReference(path="x.py", start_line=5, end_line=10)
        msg = AgentFinal(
            agent_session_id=SESSION_ID,
            text="ok",
            file_references=[ref],
        )
        data = json.loads(msg.model_dump_json())
        assert len(data["file_references"]) == 1
        assert data["file_references"][0]["path"] == "x.py"
        restored = AgentFinal(**data)
        assert restored.file_references[0].start_line == 5

    def test_agent_tool_call_result_file_references(self):
        refs = [FileReference(path="out.json", description="Output file")]
        msg = AgentToolCallResult(
            agent_session_id=SESSION_ID,
            tool_name="write_file",
            file_references=refs,
        )
        assert len(msg.file_references) == 1

    def test_agent_tool_call_result_file_references_default_empty(self):
        msg = AgentToolCallResult(
            agent_session_id=SESSION_ID,
            tool_name="read",
        )
        assert msg.file_references == []

    def test_agent_confirmation_request_file_references(self):
        refs = [FileReference(path="patched.py", start_line=10, end_line=20)]
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id="c1",
            tool_name="apply_patch",
            file_references=refs,
        )
        assert len(msg.file_references) == 1


# ---------------------------------------------------------------------------
# diff field on AgentConfirmationRequest
# ---------------------------------------------------------------------------


class TestApplyPatchDiff:
    def test_diff_field(self):
        diff_text = "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,4 @@\n+import os\n import sys"
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id="c2",
            tool_name="apply_patch",
            proposed_input={"file": "main.py", "patch": diff_text},
            diff=diff_text,
            description="Add import os to main.py",
        )
        assert msg.diff == diff_text
        assert msg.tool_name == "apply_patch"

    def test_diff_default_none(self):
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id="c3",
            tool_name="shell_exec",
        )
        assert msg.diff is None

    def test_diff_json_roundtrip(self):
        diff = "@@ -1 +1 @@\n-old\n+new"
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id="c4",
            tool_name="apply_patch",
            diff=diff,
        )
        data = json.loads(msg.model_dump_json())
        assert data["diff"] == diff
        restored = AgentConfirmationRequest(**data)
        assert restored.diff == diff


# ---------------------------------------------------------------------------
# apply_patch confirmation gate
# ---------------------------------------------------------------------------


class TestApplyPatchConfirmationGate:
    """Confirm that apply_patch tool calls produce confirmation requests with diffs."""

    def test_confirmation_request_for_apply_patch_includes_diff(self):
        """AgentConfirmationRequest for apply_patch carries diff + file_references."""
        diff_text = "--- a/app.py\n+++ b/app.py\n@@ -5,3 +5,4 @@\n+# new comment"
        msg = AgentConfirmationRequest(
            agent_session_id=SESSION_ID,
            confirmation_id=str(uuid.uuid4()),
            tool_name="apply_patch",
            proposed_input={"file": "app.py", "patch": diff_text},
            diff=diff_text,
            file_references=[
                FileReference(path="app.py", start_line=5, end_line=8),
            ],
            description="Add comment to app.py",
            correlation_id=CORR_ID,
            request_id=REQ_ID,
        )
        assert msg.tool_name == "apply_patch"
        assert msg.diff is not None
        assert len(msg.file_references) == 1
        assert msg.correlation_id == CORR_ID

    def test_parse_confirmation_with_diff(self):
        """parse_agent_message can deserialize confirmation with diff."""
        data = {
            "type": "agent.confirmation_request",
            "agent_session_id": SESSION_ID,
            "confirmation_id": "c5",
            "tool_name": "apply_patch",
            "diff": "@@ diff @@",
            "file_references": [{"path": "f.py", "start_line": 1}],
        }
        msg = parse_agent_message(data)
        assert isinstance(msg, AgentConfirmationRequest)
        assert msg.diff == "@@ diff @@"
        assert msg.file_references[0].path == "f.py"


# ---------------------------------------------------------------------------
# Backward compatibility — existing P0-32 tests still work
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure adding new fields doesn't break existing deserialization."""

    def test_parse_without_new_fields(self):
        """Messages without correlation_id/request_id/file_references still parse."""
        data = {
            "type": "agent.final",
            "agent_session_id": SESSION_ID,
            "text": "hello",
        }
        msg = parse_agent_message(data)
        assert isinstance(msg, AgentFinal)
        assert msg.correlation_id is None
        assert msg.file_references == []

    def test_parse_tool_result_without_file_refs(self):
        data = {
            "type": "agent.tool_call_result",
            "agent_session_id": SESSION_ID,
            "tool_name": "read",
        }
        msg = parse_agent_message(data)
        assert isinstance(msg, AgentToolCallResult)
        assert msg.file_references == []

    def test_all_types_still_parseable(self):
        """Every type can be parsed with minimal fields (no new fields)."""
        samples = {
            "agent.stream_start": {"agent_session_id": SESSION_ID},
            "agent.partial": {"agent_session_id": SESSION_ID, "content": "a", "index": 0},
            "agent.tool_call_start": {"agent_session_id": SESSION_ID, "tool_name": "x"},
            "agent.tool_call_result": {"agent_session_id": SESSION_ID, "tool_name": "x"},
            "agent.confirmation_request": {"agent_session_id": SESSION_ID, "confirmation_id": "c", "tool_name": "x"},
            "agent.budget_update": {"agent_session_id": SESSION_ID},
            "agent.final": {"agent_session_id": SESSION_ID},
            "agent.error": {"agent_session_id": SESSION_ID, "error": "e"},
        }
        for type_str, fields in samples.items():
            msg = parse_agent_message({"type": type_str, **fields})
            assert msg.type.value == type_str
