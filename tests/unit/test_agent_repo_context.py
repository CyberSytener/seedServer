"""Unit tests for repo context injection into agent sessions (P0-30).

Tests cover:
  • RepoContextPack model (validation, serialization, prompt section)
  • RepoFile model
  • RepoFileCache (put, get, limits, to_pack)
  • build_prompt integration with repo_context parameter
  • Repo context endpoint (POST /sessions/{id}/repo-context)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from app.core.agent.repo_context import (
    MAX_FILE_ENTRIES,
    MAX_TOTAL_CONTENT_BYTES,
    MAX_TREE_BYTES,
    RepoContextPack,
    RepoFile,
    RepoFileCache,
)
from app.core.agent.session import build_prompt
from app.core.agent.models import AgentSessionMessage, MessageRole


# ---------------------------------------------------------------------------
# RepoFile tests
# ---------------------------------------------------------------------------


class TestRepoFile:
    def test_to_dict(self):
        f = RepoFile(path="src/main.py", content="print('hello')", language="python")
        d = f.to_dict()
        assert d["path"] == "src/main.py"
        assert d["content"] == "print('hello')"
        assert d["language"] == "python"

    def test_from_dict(self):
        f = RepoFile.from_dict({"path": "a.rs", "content": "fn main() {}", "language": "rust"})
        assert f.path == "a.rs"
        assert f.language == "rust"

    def test_from_dict_defaults(self):
        f = RepoFile.from_dict({"path": "x.txt", "content": "hi"})
        assert f.language == ""

    def test_roundtrip(self):
        original = RepoFile(path="f.js", content="const x=1", language="javascript")
        restored = RepoFile.from_dict(original.to_dict())
        assert restored.path == original.path
        assert restored.content == original.content
        assert restored.language == original.language


# ---------------------------------------------------------------------------
# RepoContextPack tests
# ---------------------------------------------------------------------------


class TestRepoContextPack:
    def test_basic_creation(self):
        pack = RepoContextPack(repo_url="https://github.com/user/repo")
        assert pack.repo_url == "https://github.com/user/repo"
        assert len(pack.files) == 0
        assert pack.fetched_at  # auto-filled

    def test_with_files(self):
        files = [
            RepoFile(path="README.md", content="# Hello", language="markdown"),
            RepoFile(path="main.py", content="print(1)", language="python"),
        ]
        pack = RepoContextPack(repo_url="https://github.com/u/r", files=files)
        assert len(pack.files) == 2

    def test_with_tree(self):
        pack = RepoContextPack(
            repo_url="https://github.com/u/r",
            tree="src/\n  main.py\n  utils.py",
        )
        assert "src/" in pack.tree

    def test_empty_repo_url_raises(self):
        with pytest.raises(ValueError, match="repo_url is required"):
            RepoContextPack(repo_url="")

    def test_too_many_files_raises(self):
        files = [RepoFile(path=f"f{i}.txt", content="x") for i in range(MAX_FILE_ENTRIES + 1)]
        with pytest.raises(ValueError, match="Too many files"):
            RepoContextPack(repo_url="https://github.com/u/r", files=files)

    def test_total_content_too_large_raises(self):
        big_content = "x" * (MAX_TOTAL_CONTENT_BYTES + 1)
        files = [RepoFile(path="big.txt", content=big_content)]
        with pytest.raises(ValueError, match="too large"):
            RepoContextPack(repo_url="https://github.com/u/r", files=files)

    def test_tree_too_large_raises(self):
        big_tree = "x" * (MAX_TREE_BYTES + 1)
        with pytest.raises(ValueError, match="Tree too large"):
            RepoContextPack(repo_url="https://github.com/u/r", tree=big_tree)

    def test_to_dict_roundtrip(self):
        files = [RepoFile(path="a.py", content="pass", language="python")]
        pack = RepoContextPack(repo_url="https://github.com/u/r", files=files, tree="a.py")
        d = pack.to_dict()
        assert d["type"] == "repo"
        restored = RepoContextPack.from_dict(d)
        assert restored.repo_url == pack.repo_url
        assert len(restored.files) == 1
        assert restored.tree == "a.py"

    def test_to_dict_type_field(self):
        pack = RepoContextPack(repo_url="https://github.com/u/r")
        assert pack.to_dict()["type"] == "repo"


# ---------------------------------------------------------------------------
# Prompt section tests
# ---------------------------------------------------------------------------


class TestToPromptSection:
    def test_header(self):
        pack = RepoContextPack(repo_url="https://github.com/user/repo")
        section = pack.to_prompt_section()
        assert "=== Repository Context ===" in section
        assert "https://github.com/user/repo" in section

    def test_includes_file_content(self):
        files = [RepoFile(path="src/main.py", content="print(42)", language="python")]
        pack = RepoContextPack(repo_url="https://github.com/u/r", files=files)
        section = pack.to_prompt_section()
        assert "--- src/main.py [python] ---" in section
        assert "print(42)" in section

    def test_includes_tree(self):
        pack = RepoContextPack(
            repo_url="https://github.com/u/r",
            tree="src/\n  main.py",
        )
        section = pack.to_prompt_section()
        assert "File tree:" in section
        assert "src/" in section

    def test_truncates_many_files(self):
        files = [RepoFile(path=f"f{i}.txt", content="x") for i in range(40)]
        pack = RepoContextPack(repo_url="https://github.com/u/r", files=files)
        section = pack.to_prompt_section()
        assert "more file(s) available" in section

    def test_empty_files(self):
        pack = RepoContextPack(repo_url="https://github.com/u/r")
        section = pack.to_prompt_section()
        assert "=== Repository Context ===" in section
        assert "Files" not in section  # no files section


# ---------------------------------------------------------------------------
# RepoFileCache tests
# ---------------------------------------------------------------------------


class TestRepoFileCache:
    def test_put_and_get(self):
        cache = RepoFileCache()
        f = RepoFile(path="a.py", content="pass")
        assert cache.put("a.py", f) is True
        assert cache.get("a.py") is f

    def test_has(self):
        cache = RepoFileCache()
        assert cache.has("x") is False
        cache.put("x", RepoFile(path="x", content=""))
        assert cache.has("x") is True

    def test_count(self):
        cache = RepoFileCache()
        assert cache.count == 0
        cache.put("a", RepoFile(path="a", content="x"))
        cache.put("b", RepoFile(path="b", content="y"))
        assert cache.count == 2

    def test_total_bytes(self):
        cache = RepoFileCache()
        cache.put("a", RepoFile(path="a", content="hello"))  # 5 bytes
        assert cache.total_bytes == 5
        cache.put("b", RepoFile(path="b", content="world!"))  # 6 bytes
        assert cache.total_bytes == 11

    def test_exceeds_limit_returns_false(self):
        cache = RepoFileCache(max_bytes=10)
        f = RepoFile(path="big", content="x" * 20)
        assert cache.put("big", f) is False
        assert cache.count == 0

    def test_replace_existing_key(self):
        cache = RepoFileCache(max_bytes=100)
        cache.put("a", RepoFile(path="a", content="short"))
        assert cache.total_bytes == 5
        cache.put("a", RepoFile(path="a", content="longer text"))
        assert cache.total_bytes == 11
        assert cache.count == 1

    def test_all_files(self):
        cache = RepoFileCache()
        cache.put("a", RepoFile(path="a", content="1"))
        cache.put("b", RepoFile(path="b", content="2"))
        files = cache.all_files()
        assert len(files) == 2

    def test_to_pack(self):
        cache = RepoFileCache()
        cache.put("a", RepoFile(path="a.py", content="pass", language="python"))
        pack = cache.to_pack("https://github.com/u/r", tree="a.py")
        assert pack.repo_url == "https://github.com/u/r"
        assert len(pack.files) == 1
        assert pack.tree == "a.py"

    def test_cache_prevents_refetch(self):
        """Cache hit should return same object — no re-fetch needed."""
        cache = RepoFileCache()
        f = RepoFile(path="a.py", content="pass")
        cache.put("https://raw.githubusercontent.com/u/r/main/a.py", f)
        hit = cache.get("https://raw.githubusercontent.com/u/r/main/a.py")
        assert hit is f


# ---------------------------------------------------------------------------
# build_prompt integration
# ---------------------------------------------------------------------------


class TestBuildPromptRepoContext:
    def test_repo_context_included(self):
        prompt = build_prompt(
            system_prompt="You are an agent.",
            history=[],
            tool_manifests=[],
            user_message="Explain the code.",
            repo_context="=== Repository Context ===\nRepo: https://github.com/u/r",
        )
        assert "=== Repository Context ===" in prompt
        assert "https://github.com/u/r" in prompt

    def test_repo_context_none_excluded(self):
        prompt = build_prompt(
            system_prompt="You are an agent.",
            history=[],
            tool_manifests=[],
            user_message="Hello.",
            repo_context=None,
        )
        assert "Repository Context" not in prompt

    def test_both_ui_and_repo_context(self):
        prompt = build_prompt(
            system_prompt="You are an agent.",
            history=[],
            tool_manifests=[],
            user_message="Help.",
            ui_context="=== UI Context ===\nFramework: react",
            repo_context="=== Repository Context ===\nRepo: https://github.com/u/r",
        )
        assert "UI Context" in prompt
        assert "Repository Context" in prompt

    def test_repo_context_before_history(self):
        """Repo context should appear before conversation history."""
        history = [
            AgentSessionMessage(
                session_id="s1",
                role=MessageRole.AGENT,
                content="Previous response",
            ),
        ]
        prompt = build_prompt(
            system_prompt="You are an agent.",
            history=history,
            tool_manifests=[],
            user_message="New question.",
            repo_context="=== Repository Context ===",
        )
        repo_idx = prompt.index("Repository Context")
        history_idx = prompt.index("Previous response")
        assert repo_idx < history_idx


# ---------------------------------------------------------------------------
# Repo context endpoint (via agent_routes)
# ---------------------------------------------------------------------------


class TestRepoContextEndpoint:
    """Test the POST /sessions/{id}/repo-context endpoint."""

    @pytest.fixture
    def app_client(self):
        """Create a test client with the agent routes."""
        from starlette.testclient import TestClient
        from app.api.agent_routes import build_agent_router
        from app.core.agent.session_store import AgentSessionStore
        from app.core.agent.models import AgentSessionData
        from app.core.agent.tool_registry import ToolRegistry
        from app.core.blocks import build_default_registry
        from fastapi import FastAPI, HTTPException

        # Fake auth context
        class FakeAuthContext:
            def __init__(self, user_id, scopes):
                self.user_id = user_id
                self.scopes = scopes
            def has_scope(self, scope):
                return scope in self.scopes or "*" in self.scopes

        def _auth_provider(request, scope):
            ctx = FakeAuthContext(
                user_id="user-1",
                scopes=["agent:sessions", "agent:tools:read", "agent:context:read"],
            )
            if not ctx.has_scope(scope):
                raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")
            return ctx

        # Minimal in-memory session store
        class InMemorySessionStore(AgentSessionStore):
            def __init__(self):
                self.sessions: Dict[str, AgentSessionData] = {}
                self.messages: Dict[str, List[AgentSessionMessage]] = {}

            async def create_session(self, session: AgentSessionData) -> AgentSessionData:
                self.sessions[session.session_id] = session
                self.messages[session.session_id] = []
                return session

            async def get_session(self, session_id: str) -> Optional[AgentSessionData]:
                return self.sessions.get(session_id)

            async def update_session(self, session: AgentSessionData) -> AgentSessionData:
                self.sessions[session.session_id] = session
                return session

            async def list_sessions(self, user_id: str) -> List[AgentSessionData]:
                return [s for s in self.sessions.values() if s.user_id == user_id]

            async def delete_session(self, session_id: str) -> bool:
                return self.sessions.pop(session_id, None) is not None

            async def append_message(self, message: AgentSessionMessage) -> AgentSessionMessage:
                sid = message.session_id
                if sid not in self.messages:
                    self.messages[sid] = []
                self.messages[sid].append(message)
                return message

            async def get_messages(self, session_id: str) -> List[AgentSessionMessage]:
                return self.messages.get(session_id, [])

            async def find_children(self, parent_session_id: str) -> List[AgentSessionData]:
                return []

            async def add_participant(self, session_id, user_id, role, tool_scopes=None, invited_by=None):
                pass

            async def remove_participant(self, session_id, user_id):
                return True

            async def get_participant(self, session_id, user_id):
                return None

            async def list_participants(self, session_id, include_left=False):
                return []

        store = InMemorySessionStore()
        registry = build_default_registry()
        tool_reg = ToolRegistry(registry)

        app = FastAPI()
        router = build_agent_router(
            session_store=store,
            tool_registry=tool_reg,
            action_router=mock.MagicMock(),
            llm_service=mock.MagicMock(),
            auth_provider=_auth_provider,
        )
        app.include_router(router, prefix="/api/agent")

        # Seed a session
        import asyncio
        loop = asyncio.new_event_loop()
        session = AgentSessionData(
            session_id="test-session",
            user_id="user-1",
            persona_id="default",
            status="active",
        )
        loop.run_until_complete(store.create_session(session))
        loop.close()

        client = TestClient(app)
        yield client, store

    def test_ingest_repo_context_success(self, app_client):
        client, store = app_client
        body = {
            "repo_url": "https://github.com/user/repo",
            "files": [
                {"path": "README.md", "content": "# Hello", "language": "markdown"},
            ],
            "tree": "README.md",
        }
        resp = client.post(
            "/api/agent/v1/agent/sessions/test-session/repo-context",
            json=body,
            headers={"Authorization": "Bearer test", "X-User-Id": "user-1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_url"] == "https://github.com/user/repo"
        assert data["files_count"] == 1

    def test_ingest_repo_context_persisted_as_message(self, app_client):
        client, store = app_client
        body = {
            "repo_url": "https://github.com/user/repo",
            "files": [{"path": "a.py", "content": "pass"}],
        }
        client.post(
            "/api/agent/v1/agent/sessions/test-session/repo-context",
            json=body,
            headers={"Authorization": "Bearer test", "X-User-Id": "user-1"},
        )
        import asyncio
        loop = asyncio.new_event_loop()
        msgs = loop.run_until_complete(store.get_messages("test-session"))
        loop.close()
        assert len(msgs) == 1
        assert msgs[0].role == MessageRole.CONTEXT
        parsed = json.loads(msgs[0].content)
        assert parsed["type"] == "repo"
        assert parsed["repo_url"] == "https://github.com/user/repo"

    def test_ingest_repo_context_invalid_session(self, app_client):
        client, _ = app_client
        body = {"repo_url": "https://github.com/u/r", "files": []}
        resp = client.post(
            "/api/agent/v1/agent/sessions/nonexistent/repo-context",
            json=body,
            headers={"Authorization": "Bearer test", "X-User-Id": "user-1"},
        )
        assert resp.status_code == 404

    def test_ingest_repo_context_empty_url_rejected(self, app_client):
        client, _ = app_client
        body = {"repo_url": "", "files": []}
        resp = client.post(
            "/api/agent/v1/agent/sessions/test-session/repo-context",
            json=body,
            headers={"Authorization": "Bearer test", "X-User-Id": "user-1"},
        )
        assert resp.status_code == 413
