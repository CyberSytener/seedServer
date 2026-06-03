"""Tests for P0-25 — Multi-user message attribution and history interleaving.

Covers:
  • sender_user_id field on AgentSessionMessage
  • to_row / from_row roundtrip with sender
  • build_prompt includes sender identity
  • History retrieval includes sender attribution
  • Two users sending messages to the same session
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.models import (
    AgentSessionMessage,
    MessageRole,
)


# ===================================================================
# AgentSessionMessage — sender_user_id field
# ===================================================================


class TestMessageSenderField:
    def test_default_none(self):
        msg = AgentSessionMessage(session_id="s1", role=MessageRole.USER, content="hi")
        assert msg.sender_user_id is None

    def test_explicit_sender(self):
        msg = AgentSessionMessage(
            session_id="s1",
            role=MessageRole.USER,
            content="hello",
            sender_user_id="user-A",
        )
        assert msg.sender_user_id == "user-A"

    def test_to_row_includes_sender(self):
        msg = AgentSessionMessage(
            session_id="s1",
            role=MessageRole.USER,
            content="hello",
            sender_user_id="user-B",
        )
        row = msg.to_row()
        assert len(row) == 10
        assert row[9] == "user-B"

    def test_to_row_none_sender(self):
        msg = AgentSessionMessage(session_id="s1", role=MessageRole.USER, content="x")
        row = msg.to_row()
        assert row[9] is None

    def test_from_row_tuple_with_sender(self):
        msg = AgentSessionMessage(
            session_id="s1",
            role=MessageRole.USER,
            content="hello",
            sender_user_id="user-C",
        )
        row = msg.to_row()
        restored = AgentSessionMessage.from_row(row)
        assert restored.sender_user_id == "user-C"

    def test_from_row_tuple_without_sender(self):
        """Backward compat: 9-element tuple (no sender_user_id)."""
        row = (
            "msg-1", "s1", "user", "hello",
            None, None, None, None,
            "2025-01-01T00:00:00",
        )
        restored = AgentSessionMessage.from_row(row)
        assert restored.sender_user_id is None

    def test_from_row_dict_with_sender(self):
        row = {
            "message_id": "msg-1",
            "session_id": "s1",
            "role": "user",
            "content": "hello",
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "budget_snapshot": None,
            "timestamp": "2025-01-01T00:00:00",
            "sender_user_id": "user-D",
        }
        restored = AgentSessionMessage.from_row(row)
        assert restored.sender_user_id == "user-D"

    def test_from_row_dict_missing_sender(self):
        """Dict without sender_user_id key (backward compat)."""
        row = {
            "message_id": "msg-1",
            "session_id": "s1",
            "role": "user",
            "content": "hello",
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "budget_snapshot": None,
            "timestamp": "2025-01-01T00:00:00",
        }
        restored = AgentSessionMessage.from_row(row)
        assert restored.sender_user_id is None


# ===================================================================
# build_prompt — sender attribution in history
# ===================================================================


class TestBuildPromptSenderAttribution:
    def test_history_with_sender(self):
        from app.core.agent.session import build_prompt

        history = [
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="Hello from A",
                sender_user_id="user-A",
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.AGENT,
                content="Response to A",
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="Hello from B",
                sender_user_id="user-B",
            ),
        ]
        prompt = build_prompt(
            system_prompt="You are a helpful assistant.",
            history=history,
            tool_manifests=[],
            user_message="current message",
        )
        # User A's message should include sender identity
        assert "[User (user-A)] Hello from A" in prompt
        # Agent response has no sender
        assert "[Agent] Response to A" in prompt
        # User B's message includes sender
        assert "[User (user-B)] Hello from B" in prompt

    def test_history_without_sender(self):
        from app.core.agent.session import build_prompt

        history = [
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="Hi there",
            ),
        ]
        prompt = build_prompt(
            system_prompt="Test",
            history=history,
            tool_manifests=[],
            user_message="msg",
        )
        # No sender → standard format
        assert "[User] Hi there" in prompt
        assert "(None)" not in prompt

    def test_tool_messages_unaffected(self):
        from app.core.agent.session import build_prompt

        history = [
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.TOOL_CALL,
                tool_name="search",
                tool_input='{"q": "test"}',
                sender_user_id="user-A",
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.TOOL_RESULT,
                tool_name="search",
                tool_output='{"results": []}',
            ),
        ]
        prompt = build_prompt(
            system_prompt="Test",
            history=history,
            tool_manifests=[],
            user_message="msg",
        )
        # Tool messages should still use standard format
        assert "[Tool Call]" in prompt
        assert "[Tool Result]" in prompt


# ===================================================================
# Multi-user interleaving scenario
# ===================================================================


class TestMultiUserInterleaving:
    def test_two_users_interleaved(self):
        """Two users' messages correctly attributed and interleaved."""
        from app.core.agent.session import build_prompt

        history = [
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="Start feature X",
                sender_user_id="alice",
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.AGENT,
                content="Working on feature X...",
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="Add tests too",
                sender_user_id="bob",
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.AGENT,
                content="Added tests for feature X.",
            ),
        ]
        prompt = build_prompt(
            system_prompt="You are a coding assistant.",
            history=history,
            tool_manifests=[],
            user_message="Looks good",
        )
        # Both users' messages have attribution
        assert "(alice)" in prompt
        assert "(bob)" in prompt
        # Order preserved
        alice_pos = prompt.index("(alice)")
        bob_pos = prompt.index("(bob)")
        assert alice_pos < bob_pos

    def test_mixed_sender_and_no_sender(self):
        """History can contain messages with and without sender_user_id."""
        from app.core.agent.session import build_prompt

        history = [
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="old message",
                # No sender (pre-P0-25 message)
            ),
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.USER,
                content="new message",
                sender_user_id="carol",
            ),
        ]
        prompt = build_prompt(
            system_prompt="Test",
            history=history,
            tool_manifests=[],
            user_message="end",
        )
        assert "[User] old message" in prompt
        assert "[User (carol)] new message" in prompt
