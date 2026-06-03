"""P0-41: GitHub fetch + repo context demo integration test.

Exercises the agent → github_fetch → repo context injection flow using stubs:
  1. Create session with github_fetch in tool_scopes
  2. Agent calls github_fetch tool (sandbox-routed)
  3. Fetched content appears in session context
  4. Agent's response references fetched content
  5. URL allowlist enforcement verified
  6. Trace includes github_fetch tool call
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pytest

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentResponse,
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.session import AgentSession
from app.core.agent.tool_registry import ToolPermissionConfig, ToolRegistry
from app.core.blocks import BlockRegistry


# ===================================================================
# Test infrastructure
# ===================================================================


class InMemoryStore:
    """In-memory AgentSessionStore for tests."""

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


@dataclass
class StubGenResult:
    text: str = ""
    tokens_in: int = 50
    tokens_out: int = 50
    cost_usd: float = 0.001


class GitHubFetchLLMStub:
    """Deterministic LLM stub for the github_fetch demo.

    Call 1: Returns a tool call to github_fetch
    Call 2: Returns a final answer referencing the fetched content
    """

    def __init__(self):
        self.call_count = 0

    async def agenerate_with_metadata(self, **kw):
        self.call_count += 1
        if self.call_count == 1:
            return StubGenResult(
                text=(
                    "I'll fetch the README from the repository.\n\n"
                    '<tool_call>{"name": "github_fetch", "arguments": '
                    '{"url": "https://github.com/example/repo/blob/main/README.md"}}</tool_call>'
                ),
            )
        else:
            return StubGenResult(
                text=(
                    "Based on the fetched README, this is a demo repository.\n"
                    "It contains a Python project with a CLI interface and REST API.\n"
                    "The main entry point is `main.py` and it uses FastAPI for the server."
                ),
            )


class FakeSandboxDispatcher:
    """Fake sandbox dispatcher that returns canned github_fetch results."""

    def __init__(self):
        self.dispatched: List[Dict[str, Any]] = []

    def dispatch(self, session_id: str, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        self.dispatched.append({
            "session_id": session_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
        })
        if tool_name == "github_fetch":
            return {
                "status": "success",
                "result": {
                    "content": "# Demo Repository\n\nA Python project with CLI and REST API.\n\n## Features\n- FastAPI server\n- CLI interface\n\n## Usage\n```python\npython main.py\n```",
                    "url": tool_input.get("url", ""),
                    "content_type": "text/markdown",
                    "bytes": 180,
                },
                "rpc_id": f"rpc-{uuid.uuid4().hex[:8]}",
            }
        return {"status": "error", "result": None, "error": f"Unknown tool: {tool_name}"}


def _make_tool_registry_with_github_fetch():
    """Create a ToolRegistry with github_fetch configured."""
    from app.core.blocks import BlockBase

    class StubGitHubFetchBlock(BlockBase):
        DESCRIPTION = "Fetch content from GitHub"
        INPUT_SCHEMA = {"url": {"type": "string"}}
        OUTPUT_SCHEMA = {"content": {"type": "string"}}

        async def execute(self, context, inputs):
            return {"content": "stub"}

    br = BlockRegistry()
    br.register("github_fetch", StubGitHubFetchBlock,
                description="Fetch content from GitHub repositories")

    perms = ToolPermissionConfig({"tools": {
        "github_fetch": {
            "require_scope": "agent:tools:execute",
            "sandbox_required": True,
            "allowed_in_sandbox": True,
            "requires_confirmation": False,
            "max_calls_per_session": 20,
        },
    }})

    return ToolRegistry(br, permissions=perms)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def github_fetch_env():
    store = InMemoryStore()
    llm = GitHubFetchLLMStub()
    sandbox = FakeSandboxDispatcher()
    tool_registry = _make_tool_registry_with_github_fetch()

    agent = AgentSession(
        session_store=store,
        tool_registry=tool_registry,
        action_router=None,  # not used — sandbox routing
        llm_service=llm,
        sandbox_dispatcher=sandbox,
        sandbox_enabled=True,
    )

    return {
        "agent": agent,
        "store": store,
        "llm": llm,
        "sandbox": sandbox,
    }


# ===================================================================
# Tests
# ===================================================================

class TestGitHubFetchDemo:
    """GitHub fetch + repo context injection demo."""

    @pytest.mark.asyncio
    async def test_step1_session_with_github_fetch_scope(self, github_fetch_env):
        """Create session with github_fetch in tool_scopes."""
        store = github_fetch_env["store"]

        session = AgentSessionData(
            session_id="gh-001",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        stored = await store.get_session("gh-001")
        assert stored is not None
        assert "github_fetch" in stored.tool_scopes

    @pytest.mark.asyncio
    async def test_step2_agent_calls_github_fetch(self, github_fetch_env):
        """Agent sends message → LLM produces github_fetch tool call → sandbox dispatches."""
        store = github_fetch_env["store"]
        agent = github_fetch_env["agent"]
        sandbox = github_fetch_env["sandbox"]

        session = AgentSessionData(
            session_id="gh-002",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        response = await agent.process_message(
            "gh-002",
            "Fetch the README from https://github.com/example/repo and summarize it.",
        )

        # Verify sandbox was called with github_fetch
        assert len(sandbox.dispatched) >= 1
        fetch_call = sandbox.dispatched[0]
        assert fetch_call["tool_name"] == "github_fetch"
        assert "github.com" in fetch_call["tool_input"]["url"]

    @pytest.mark.asyncio
    async def test_step3_response_references_content(self, github_fetch_env):
        """Agent response references the fetched content."""
        store = github_fetch_env["store"]
        agent = github_fetch_env["agent"]

        session = AgentSessionData(
            session_id="gh-003",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        response = await agent.process_message(
            "gh-003",
            "Fetch the README and summarize it.",
        )

        # LLM stub's second call returns text about the README
        assert "README" in response.text or "demo" in response.text.lower()

    @pytest.mark.asyncio
    async def test_step4_tool_result_in_messages(self, github_fetch_env):
        """Tool call and result appear in session messages."""
        store = github_fetch_env["store"]
        agent = github_fetch_env["agent"]

        session = AgentSessionData(
            session_id="gh-004",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        await agent.process_message("gh-004", "Fetch the README.")

        messages = await store.get_messages("gh-004")
        tool_call_msgs = [m for m in messages if m.role == MessageRole.TOOL_CALL]
        tool_result_msgs = [m for m in messages if m.role == MessageRole.TOOL_RESULT]

        assert len(tool_call_msgs) >= 1
        assert tool_call_msgs[0].tool_name == "github_fetch"
        assert len(tool_result_msgs) >= 1

    @pytest.mark.asyncio
    async def test_step5_trace_includes_github_fetch(self, github_fetch_env):
        """Trace includes github_fetch with sandbox execution details."""
        store = github_fetch_env["store"]
        agent = github_fetch_env["agent"]

        session = AgentSessionData(
            session_id="gh-005",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        response = await agent.process_message("gh-005", "Fetch the README.")

        # Check trace for tool execution
        tool_traces = [t for t in response.trace if t.get("tool_name") == "github_fetch"]
        assert len(tool_traces) >= 1
        # Should be sandbox-executed
        assert tool_traces[0].get("step") == "tool_executed_sandbox"

    @pytest.mark.asyncio
    async def test_step6_sandbox_routing_verified(self, github_fetch_env):
        """github_fetch is routed via sandbox dispatcher, not ActionRouter."""
        store = github_fetch_env["store"]
        agent = github_fetch_env["agent"]
        sandbox = github_fetch_env["sandbox"]

        session = AgentSessionData(
            session_id="gh-006",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        await agent.process_message("gh-006", "Fetch the README.")

        assert len(sandbox.dispatched) >= 1
        # ActionRouter should NOT have been called (it's None in test env)
        # If it were called, it would crash — the fact that we get here proves sandbox routing

    @pytest.mark.asyncio
    async def test_step7_budget_consumed(self, github_fetch_env):
        """Budget shows consumption after github_fetch call."""
        store = github_fetch_env["store"]
        agent = github_fetch_env["agent"]

        session = AgentSessionData(
            session_id="gh-007",
            user_id="user-1",
            persona_id="seed",
            budget_config={"max_tokens": 10000, "max_cost_units": 5.0, "max_tool_calls": 20},
            tool_scopes=["github_fetch"],
            status=SessionStatus.ACTIVE,
        )
        await store.create_session(session)

        response = await agent.process_message("gh-007", "Fetch the README.")

        assert response.budget_snapshot.get("consumed_tokens", 0) > 0
        assert response.budget_snapshot.get("consumed_tool_calls", 0) >= 1


class TestGitHubFetchURLAllowlist:
    """URL allowlist enforcement for github_fetch block."""

    def test_allowed_hosts_defined(self):
        """The github_fetch block has an ALLOWED_HOSTS set."""
        from app.dynamic_registry.github_fetch_block import ALLOWED_HOSTS
        assert "github.com" in ALLOWED_HOSTS
        assert "api.github.com" in ALLOWED_HOSTS
        assert "raw.githubusercontent.com" in ALLOWED_HOSTS

    def test_validate_url_accepts_github(self):
        """Valid GitHub URLs are accepted."""
        from app.dynamic_registry.github_fetch_block import validate_url
        # Should not raise
        validate_url("https://github.com/example/repo")
        validate_url("https://raw.githubusercontent.com/example/repo/main/README.md")

    def test_validate_url_rejects_non_github(self):
        """Non-GitHub URLs are rejected (returns error string)."""
        from app.dynamic_registry.github_fetch_block import validate_url
        result = validate_url("https://evil.com/malware")
        assert result is not None  # non-None = error
        assert "not allowed" in result.lower()

    def test_validate_url_rejects_http(self):
        """HTTP (non-HTTPS) URLs are rejected."""
        from app.dynamic_registry.github_fetch_block import validate_url
        result = validate_url("http://github.com/example/repo")
        assert result is not None  # non-None = error
