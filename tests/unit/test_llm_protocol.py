"""Tests for the unified LLM protocol layer.

Covers:
- Protocol conformance (structural typing checks)
- UnifiedLLMService provider registration and routing
- GeminiClientAdapter satisfies LLMProvider + LLMVisionProvider
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from app.core.llm.protocol import LLMProvider, LLMVisionProvider
from app.core.llm.unified import GeminiClientAdapter, UnifiedLLMService


# ---------------------------------------------------------------------------
# Helpers — tiny fake GeminiClient to test the adapter
# ---------------------------------------------------------------------------

class _FakeGeminiClient:
    """Minimal stand-in for GeminiClient used in adapter tests."""

    def __init__(self, text: str = "fake-response") -> None:
        self._text = text
        self.last_call: Dict[str, Any] = {}

    def generate_content(
        self,
        contents: Any,
        *,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.last_call = {
            "method": "generate_content",
            "contents": contents,
            "model": model,
            "generation_config": generation_config,
        }
        return self._text

    async def generate_content_async(
        self,
        contents: Any,
        *,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.last_call = {
            "method": "generate_content_async",
            "contents": contents,
            "model": model,
            "generation_config": generation_config,
        }
        return self._text


# ---------------------------------------------------------------------------
# 1. Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    """Verify that adapters satisfy the runtime-checkable protocols."""

    def test_gemini_client_adapter_is_llm_provider(self) -> None:
        adapter = GeminiClientAdapter(_FakeGeminiClient())
        assert isinstance(adapter, LLMProvider)

    def test_gemini_client_adapter_is_vision_provider(self) -> None:
        adapter = GeminiClientAdapter(_FakeGeminiClient())
        assert isinstance(adapter, LLMVisionProvider)

    def test_adapter_provider_name(self) -> None:
        adapter = GeminiClientAdapter(_FakeGeminiClient())
        assert adapter.provider_name == "gemini"

    def test_adapter_is_available_true(self) -> None:
        adapter = GeminiClientAdapter(_FakeGeminiClient())
        assert adapter.is_available is True

    def test_adapter_is_available_false_when_client_none(self) -> None:
        adapter = GeminiClientAdapter(None)  # type: ignore[arg-type]
        assert adapter.is_available is False


# ---------------------------------------------------------------------------
# 2. GeminiClientAdapter generate / agenerate
# ---------------------------------------------------------------------------

class TestGeminiClientAdapter:

    def test_generate_returns_text(self) -> None:
        client = _FakeGeminiClient("hello world")
        adapter = GeminiClientAdapter(client, default_model="test-model")
        result = adapter.generate(prompt="Say hi")
        assert result == "hello world"
        assert client.last_call["model"] == "test-model"

    def test_generate_with_system_instruction(self) -> None:
        client = _FakeGeminiClient("ok")
        adapter = GeminiClientAdapter(client)
        adapter.generate(prompt="question", system_instruction="You are helpful")
        contents = client.last_call["contents"]
        assert "You are helpful" in contents
        assert "question" in contents

    def test_generate_with_custom_model(self) -> None:
        client = _FakeGeminiClient("ok")
        adapter = GeminiClientAdapter(client)
        adapter.generate(prompt="test", model="gemini-pro")
        assert client.last_call["model"] == "gemini-pro"

    @pytest.mark.asyncio
    async def test_agenerate_returns_text(self) -> None:
        client = _FakeGeminiClient("async-response")
        adapter = GeminiClientAdapter(client, default_model="atest")
        result = await adapter.agenerate(prompt="Hi async")
        assert result == "async-response"
        assert client.last_call["method"] == "generate_content_async"

    def test_generate_returns_empty_when_no_client(self) -> None:
        adapter = GeminiClientAdapter(None)  # type: ignore[arg-type]
        assert adapter.generate(prompt="hello") == ""

    @pytest.mark.asyncio
    async def test_agenerate_returns_empty_when_no_client(self) -> None:
        adapter = GeminiClientAdapter(None)  # type: ignore[arg-type]
        assert await adapter.agenerate(prompt="hello") == ""

    def test_generate_with_image(self) -> None:
        client = _FakeGeminiClient("vision-result")
        adapter = GeminiClientAdapter(client)
        result = adapter.generate_with_image(
            prompt="What is this?",
            image_bytes=b"\x89PNG",
            mime_type="image/png",
        )
        assert result == "vision-result"
        # Contents should be a list with prompt + image dict
        contents = client.last_call["contents"]
        assert isinstance(contents, list)
        assert len(contents) == 2


# ---------------------------------------------------------------------------
# 3. UnifiedLLMService registration & routing
# ---------------------------------------------------------------------------

class _StubProvider:
    """Minimal provider for service-level tests."""

    def __init__(self, name: str = "stub", text: str = "stub-text") -> None:
        self._name = name
        self._text = text

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return True

    def generate(self, *, prompt: str, **kw: Any) -> str:
        return self._text

    async def agenerate(self, *, prompt: str, **kw: Any) -> str:
        return self._text


class TestUnifiedLLMService:

    def test_register_and_get_provider(self) -> None:
        svc = UnifiedLLMService()
        prov = _StubProvider("alpha", "a-text")
        svc.register_provider(prov)
        assert svc.get_provider("alpha") is prov

    def test_get_default_provider(self) -> None:
        svc = UnifiedLLMService()
        prov = _StubProvider("gemini", "g-text")
        svc.register_provider(prov)
        svc.default_provider = "gemini"
        assert svc.get_provider("default") is prov

    def test_get_unknown_provider_raises(self) -> None:
        svc = UnifiedLLMService()
        with pytest.raises(KeyError, match="no_such"):
            svc.get_provider("no_such")

    def test_available_providers(self) -> None:
        svc = UnifiedLLMService()
        svc.register_provider(_StubProvider("a"))
        svc.register_provider(_StubProvider("b"))
        assert set(svc.available_providers) == {"a", "b"}

    def test_generate_routes_to_provider(self) -> None:
        svc = UnifiedLLMService()
        svc.register_provider(_StubProvider("gemini", "routed"))
        svc.default_provider = "gemini"
        assert svc.generate(prompt="hi") == "routed"

    def test_generate_with_named_provider(self) -> None:
        svc = UnifiedLLMService()
        svc.register_provider(_StubProvider("alpha", "a-out"))
        svc.register_provider(_StubProvider("beta", "b-out"))
        assert svc.generate(prompt="x", provider="alpha") == "a-out"
        assert svc.generate(prompt="x", provider="beta") == "b-out"

    @pytest.mark.asyncio
    async def test_agenerate_routes_to_provider(self) -> None:
        svc = UnifiedLLMService()
        svc.register_provider(_StubProvider("gemini", "async-routed"))
        svc.default_provider = "gemini"
        result = await svc.agenerate(prompt="hi")
        assert result == "async-routed"

    def test_multiple_providers_coexist(self) -> None:
        svc = UnifiedLLMService()
        svc.register_provider(_StubProvider("gemini", "g"))
        svc.register_provider(_StubProvider("openai", "o"))
        svc.register_provider(_StubProvider("stub", "s"))
        assert svc.generate(prompt="", provider="gemini") == "g"
        assert svc.generate(prompt="", provider="openai") == "o"
        assert svc.generate(prompt="", provider="stub") == "s"


# ---------------------------------------------------------------------------
# 4. Router providers satisfy LLMProvider protocol
# ---------------------------------------------------------------------------

class TestRouterProviderProtocol:
    """Ensure GeminiProvider / OpenAIProvider / StubProvider from router.py
    satisfy the ``LLMProvider`` runtime-checkable protocol."""

    def test_gemini_provider_is_llm_provider(self) -> None:
        from app.core.llm.router import GeminiProvider
        p = GeminiProvider(api_key="fake")
        assert isinstance(p, LLMProvider)
        assert p.provider_name == "gemini"
        assert p.is_available is True

    def test_openai_provider_is_llm_provider(self) -> None:
        from app.core.llm.router import OpenAIProvider
        p = OpenAIProvider(api_key="fake")
        assert isinstance(p, LLMProvider)
        assert p.provider_name == "openai"
        assert p.is_available is True

    def test_stub_provider_is_llm_provider(self) -> None:
        from app.core.llm.router import StubProvider
        p = StubProvider()
        assert isinstance(p, LLMProvider)
        assert p.provider_name == "stub"
        assert p.is_available is True

    def test_openai_not_available_without_key(self) -> None:
        from app.core.llm.router import OpenAIProvider
        p = OpenAIProvider(api_key="")
        assert p.is_available is False

    def test_gemini_not_available_without_key(self) -> None:
        from app.core.llm.router import GeminiProvider
        p = GeminiProvider(api_key="")
        assert p.is_available is False
