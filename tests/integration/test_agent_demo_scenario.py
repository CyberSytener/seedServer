"""P7-17: Demo scenario integration test (scripted).

End-to-end test exercising the full agent workflow via HTTP endpoints:
  1. Create session  (persona=seed, budget, tool_scopes)
  2. Push UI context  (3 components, 2 routes, 1 contract)
  3. Send message      → agent builds plan, calls tools, returns artifacts
  4. Persona change    (display_name + voice_id)
  5. Verify persona    → response metadata reflects persona
  6. Get session       → verify stored messages + status
  7. Budget consumed   → consumed > 0 tokens, > 0 tool_calls

Uses StubProvider for LLM (no real API calls).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.agent_routes import build_agent_router
from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentSessionData,
    AgentSessionMessage,
    MessageRole,
    SessionStatus,
)
from app.core.agent.tool_registry import ToolPermissionConfig


# ===================================================================
# Test infrastructure
# ===================================================================

class FakeActionStatus(str, Enum):
    SUCCESS = "success"


@dataclass
class FakeActionResult:
    status: FakeActionStatus = FakeActionStatus.SUCCESS
    result: Any = "ok"
    error: Optional[str] = None


class FakeActionRouter:
    """Records executed actions and returns success."""

    def __init__(self):
        self.executed: List[str] = []

    def execute_action(self, action: Any) -> FakeActionResult:
        self.executed.append(action.name)
        return FakeActionResult(result=f"result_for_{action.name}")


class InMemoryStore:
    """In-memory AgentSessionStore implementation for tests."""

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

    async def delete_session(self, sid: str) -> None:
        self._sessions.pop(sid, None)
        self._messages.pop(sid, None)

    async def cancel_session_tree(self, root_session_id: str) -> List[str]:
        root = self._sessions.get(root_session_id)
        if root is None:
            return []
        cancelled: List[str] = []
        queue = [root_session_id]
        while queue:
            sid = queue.pop(0)
            session = self._sessions.get(sid)
            if session is None:
                continue
            if session.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
                session.status = SessionStatus.COMPLETED
                cancelled.append(session.session_id)
            for s in self._sessions.values():
                if getattr(s, "parent_session_id", None) == sid:
                    queue.append(s.session_id)
        return cancelled

    async def list_child_sessions(self, parent_session_id: str) -> List[AgentSessionData]:
        return [s for s in self._sessions.values()
                if getattr(s, "parent_session_id", None) == parent_session_id]


@dataclass
class FakeAuth:
    user_id: str = "test-user-1"
    scopes: List[str] = field(default_factory=lambda: ["*"])

    def has_scope(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


class ToolRegistryStub:
    """Allows all tools; provides manifests for LLM."""

    def __init__(self):
        self.permissions = ToolPermissionConfig()

    def list_tools_for_llm(self, scopes):
        return [
            {"type": "function", "function": {"name": "recipe_generator", "description": "Generate recipe", "parameters": {}}},
            {"type": "function", "function": {"name": "menu_lookup", "description": "Look up menu", "parameters": {}}},
        ]

    def is_tool_allowed(self, name, scopes):
        return True

    def build_action(self, name, inputs, session_id="", user_id=None):
        from app.models.realtime.actions import Action, ActionMetadata
        return Action(
            name=name,
            id=f"test_{uuid.uuid4().hex[:8]}",
            params=inputs,
            metadata=ActionMetadata(session_id=session_id, user_id=user_id),
        )


class StubLLMService:
    """Deterministic LLM stub returning tool calls on first prompt, then final answer.

    Iteration 0: Returns a plan + one tool call (recipe_generator)
    Iteration 1: Returns a final answer referencing tool results
    Subsequent: Returns conversational responses
    """

    def __init__(self):
        self.call_count = 0

    async def agenerate_with_metadata(self, **kw):
        self.call_count += 1

        if self.call_count == 1:
            # First call: plan + tool call
            return StubGenResult(
                text=(
                    "I'll create an MVP screen for inventory → recipe suggestion.\n"
                    "Step 1: Generate a recipe based on inventory.\n\n"
                    '<tool_call>{"name": "recipe_generator", "arguments": {"inventory": ["tomato", "pasta"]}}</tool_call>'
                ),
            )
        elif self.call_count == 2:
            # After tool: final answer with artifacts
            return StubGenResult(
                text=(
                    "Here's your MVP screen specification:\n\n"
                    "## Inventory → Recipe Suggestion\n"
                    "- Component: RecipeCard (uses existing InventoryList)\n"
                    "- Route: /recipes/suggest\n"
                    "- Contract: RecipeSuggestionContract\n\n"
                    "The screen reads from inventory and suggests recipes based on available items."
                ),
            )
        else:
            # Persona verification / follow-up
            return StubGenResult(
                text="Yes, I confirm — you can call me Никита. How else can I help?",
            )


@dataclass
class StubGenResult:
    text: str = ""
    tokens_in: int = 100
    tokens_out: int = 150
    cost_usd: float = 0.002
    provider: str = "stub"
    model: str = "stub-model"


def _fake_auth_provider(request, scope):
    return FakeAuth()


# ===================================================================
# Fixture: full test app
# ===================================================================

@pytest.fixture
def demo_app():
    """Build a FastAPI test app with all agent endpoints wired to stubs."""
    store = InMemoryStore()
    llm = StubLLMService()
    action_router = FakeActionRouter()
    tool_registry = ToolRegistryStub()

    router = build_agent_router(
        session_store=store,
        tool_registry=tool_registry,
        action_router=action_router,
        llm_service=llm,
        auth_provider=_fake_auth_provider,
    )
    app = FastAPI()
    app.include_router(router)

    return {
        "client": TestClient(app),
        "store": store,
        "llm": llm,
        "action_router": action_router,
    }


# ===================================================================
# Demo Scenario Test
# ===================================================================

class TestDemoScenario:
    """End-to-end demo scenario: 60-second agent workflow."""

    def test_full_demo_flow(self, demo_app):
        client = demo_app["client"]
        store = demo_app["store"]
        action_router = demo_app["action_router"]

        # ----------------------------------------------------------
        # Step 1: Create session
        # ----------------------------------------------------------
        r1 = client.post("/v1/agent/sessions", json={
            "persona_id": "seed",
            "budget": {
                "max_tokens": 10000,
                "max_tool_calls": 10,
                "max_wall_time_seconds": 60,
            },
            "tool_scopes": ["*"],
        })
        assert r1.status_code == 200, r1.text
        data1 = r1.json()
        session_id = data1["session_id"]
        assert data1["status"] == "active"
        assert data1["persona_id"] == "seed"
        assert session_id  # non-empty

        # ----------------------------------------------------------
        # Step 2: Push UI context pack
        # ----------------------------------------------------------
        ui_context = {
            "source": "saga-console",
            "framework": "react",
            "components": [
                {"name": "InventoryList", "file_path": "src/components/InventoryList.tsx", "props": ["items", "onSelect"]},
                {"name": "RecipeCard", "file_path": "src/components/RecipeCard.tsx", "props": ["recipe", "onCook"]},
                {"name": "Header", "file_path": "src/components/Header.tsx", "props": ["title"]},
            ],
            "routes": [
                {"path": "/inventory", "component": "InventoryList"},
                {"path": "/recipes", "component": "RecipeCard"},
            ],
            "contracts": [
                {
                    "name": "InventoryItem",
                    "contract_schema": '{"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}}',
                },
            ],
        }
        r2 = client.post(f"/v1/agent/sessions/{session_id}/context", json=ui_context)
        assert r2.status_code == 200, r2.text
        data2 = r2.json()
        assert data2["components_count"] == 3
        assert data2["routes_count"] == 2
        assert data2["source"] == "saga-console"

        # ----------------------------------------------------------
        # Step 3: Send message (agent builds plan, executes tools)
        # ----------------------------------------------------------
        r3 = client.post(f"/v1/agent/sessions/{session_id}/messages", json={
            "message": "Сделай мне MVP экран: inventory → recipe suggestion. Учти текущую верстку и контракты.",
        })
        assert r3.status_code == 200, r3.text
        data3 = r3.json()

        # Agent should have produced text with plan
        assert len(data3["text"]) > 0
        assert "recipe" in data3["text"].lower() or "mvp" in data3["text"].lower()

        # Budget should have consumed something
        snap = data3["budget_snapshot"]
        assert snap["consumed_tokens"] > 0
        assert snap["consumed_tool_calls"] >= 1

        # Trace should contain tool execution steps
        trace = data3["trace"]
        tool_steps = [t for t in trace if t.get("step") in ("tool_executed", "tool_executed_sandbox")]
        assert len(tool_steps) >= 1, f"Expected tool execution in trace, got: {trace}"

        # recipe_generator should have been called
        assert "recipe_generator" in action_router.executed

        # Persona metadata should be present
        assert "persona_id" in data3.get("persona_meta", {})

        # ----------------------------------------------------------
        # Step 4: Persona change
        # ----------------------------------------------------------
        r4 = client.post(f"/v1/agent/sessions/{session_id}/persona", json={
            "name": "Никита",
            "voice": "warm_male_ru",
        })
        assert r4.status_code == 200, r4.text
        data4 = r4.json()
        assert data4["persona_overrides"]["display_name"] == "Никита"
        assert data4["persona_overrides"]["voice_id"] == "warm_male_ru"

        # ----------------------------------------------------------
        # Step 5: Verify persona applied in next message
        # ----------------------------------------------------------
        r5 = client.post(f"/v1/agent/sessions/{session_id}/messages", json={
            "message": "Ок, подтверди что ты меня зовешь Никита.",
        })
        assert r5.status_code == 200, r5.text
        data5 = r5.json()
        meta = data5.get("persona_meta", {})
        assert meta.get("display_name") == "Никита"
        assert meta.get("voice_id") == "warm_male_ru"

        # ----------------------------------------------------------
        # Step 6: Get session details — verify stored messages & status
        # ----------------------------------------------------------
        r6 = client.get(f"/v1/agent/sessions/{session_id}")
        assert r6.status_code == 200, r6.text
        data6 = r6.json()
        assert data6["status"] == "active"
        assert data6["persona_id"] == "seed"
        assert len(data6["messages"]) > 0

        # Should contain at least: context message + user message + agent response
        roles = [m["role"] for m in data6["messages"]]
        assert "context" in roles
        assert "user" in roles
        assert "agent" in roles

    # ----------------------------------------------------------
    # Focused sub-tests for specific scenario aspects
    # ----------------------------------------------------------

    def test_create_session_returns_uuid(self, demo_app):
        """Session ID looks like a UUID."""
        r = demo_app["client"].post("/v1/agent/sessions", json={
            "persona_id": "seed",
            "tool_scopes": ["*"],
        })
        sid = r.json()["session_id"]
        # Should be a valid UUID
        uuid.UUID(sid)  # raises if invalid

    def test_context_persisted_as_message(self, demo_app):
        """UI context is stored as a 'context' role message."""
        client = demo_app["client"]
        r1 = client.post("/v1/agent/sessions", json={"persona_id": "seed", "tool_scopes": ["*"]})
        sid = r1.json()["session_id"]

        client.post(f"/v1/agent/sessions/{sid}/context", json={
            "source": "test",
            "framework": "react",
            "components": [{"name": "A", "file_path": "a.tsx"}],
            "routes": [],
            "contracts": [],
        })

        r3 = client.get(f"/v1/agent/sessions/{sid}")
        messages = r3.json()["messages"]
        context_msgs = [m for m in messages if m["role"] == "context"]
        assert len(context_msgs) == 1

    def test_budget_non_negative(self, demo_app):
        """Budget consumed values are never negative."""
        client = demo_app["client"]
        r1 = client.post("/v1/agent/sessions", json={
            "persona_id": "seed",
            "budget": {"max_tokens": 50000, "max_tool_calls": 10},
            "tool_scopes": ["*"],
        })
        sid = r1.json()["session_id"]

        r2 = client.post(f"/v1/agent/sessions/{sid}/messages", json={
            "message": "Hello",
        })
        snap = r2.json()["budget_snapshot"]
        assert snap["consumed_tokens"] >= 0
        assert snap["consumed_tool_calls"] >= 0
        assert snap.get("consumed_cost_units", 0) >= 0

    def test_persona_update_returns_overrides(self, demo_app):
        """Persona update endpoint returns the stored overrides."""
        client = demo_app["client"]
        r1 = client.post("/v1/agent/sessions", json={"persona_id": "seed", "tool_scopes": ["*"]})
        sid = r1.json()["session_id"]

        r2 = client.post(f"/v1/agent/sessions/{sid}/persona", json={
            "name": "Alex",
            "voice": "calm_female",
            "system_prompt": "You are Alex.",
        })
        data = r2.json()
        assert data["persona_overrides"]["display_name"] == "Alex"
        assert data["persona_overrides"]["voice_id"] == "calm_female"
        assert data["persona_overrides"]["system_prompt"] == "You are Alex."

    def test_session_not_found(self, demo_app):
        """Non-existent session returns 404."""
        r = demo_app["client"].get("/v1/agent/sessions/nonexistent-id")
        assert r.status_code == 404

    def test_delete_session(self, demo_app):
        """Deleting a session marks it completed."""
        client = demo_app["client"]
        r1 = client.post("/v1/agent/sessions", json={"persona_id": "seed", "tool_scopes": ["*"]})
        sid = r1.json()["session_id"]

        r2 = client.delete(f"/v1/agent/sessions/{sid}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "completed"
