"""Tests for GenerationResult and *_with_metadata methods on UnifiedLLMService.

T-3 verification: structured metadata wrappers return GenerationResult
while existing generate()/agenerate() still return str.
"""
from __future__ import annotations

import pytest

from app.core.llm.protocol import GenerationResult
from app.core.llm.unified import UnifiedLLMService


class _FakeProvider:
    """Minimal LLMProvider stub for testing."""
    def __init__(self, name: str = "fake", text: str = "hello"):
        self._name = name
        self._text = text

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return True

    def generate(self, *, prompt: str, system_instruction: str = "", model=None, **kw) -> str:
        return self._text

    async def agenerate(self, *, prompt: str, system_instruction: str = "", model=None, **kw) -> str:
        return self._text


class TestGenerationResult:
    """Verify the GenerationResult dataclass."""

    def test_defaults(self) -> None:
        r = GenerationResult(text="hi")
        assert r.text == "hi"
        assert r.provider == ""
        assert r.model == ""
        assert r.tokens_in == 0
        assert r.tokens_out == 0
        assert r.cost_usd == 0.0
        assert r.extra == {}

    def test_frozen(self) -> None:
        r = GenerationResult(text="hi")
        with pytest.raises(AttributeError):
            r.text = "bye"  # type: ignore[misc]

    def test_full_construction(self) -> None:
        r = GenerationResult(
            text="output",
            provider="openai",
            model="gpt-4o",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.002,
            extra={"finish_reason": "stop"},
        )
        assert r.provider == "openai"
        assert r.tokens_in == 100
        assert r.extra["finish_reason"] == "stop"


class TestGenerateWithMetadata:
    """Verify generate_with_metadata / agenerate_with_metadata."""

    def _make_svc(self) -> UnifiedLLMService:
        svc = UnifiedLLMService()
        svc.register_provider(_FakeProvider(name="fake", text="response-text"))
        svc._default_provider = "fake"
        return svc

    def test_generate_with_metadata_returns_result(self) -> None:
        svc = self._make_svc()
        result = svc.generate_with_metadata(prompt="hi", provider="fake")
        assert isinstance(result, GenerationResult)
        assert result.text == "response-text"
        assert result.provider == "fake"

    def test_generate_with_metadata_model_passthrough(self) -> None:
        svc = self._make_svc()
        result = svc.generate_with_metadata(prompt="hi", model="gpt-4o")
        assert result.model == "gpt-4o"

    def test_generate_with_metadata_model_defaults_to_empty(self) -> None:
        svc = self._make_svc()
        result = svc.generate_with_metadata(prompt="hi")
        assert result.model == ""

    @pytest.mark.asyncio
    async def test_agenerate_with_metadata_returns_result(self) -> None:
        svc = self._make_svc()
        result = await svc.agenerate_with_metadata(prompt="hi", provider="fake")
        assert isinstance(result, GenerationResult)
        assert result.text == "response-text"
        assert result.provider == "fake"

    def test_original_generate_still_returns_str(self) -> None:
        """Backward compat: generate() must still return a plain str."""
        svc = self._make_svc()
        result = svc.generate(prompt="hi")
        assert isinstance(result, str)
        assert result == "response-text"

    @pytest.mark.asyncio
    async def test_original_agenerate_still_returns_str(self) -> None:
        """Backward compat: agenerate() must still return a plain str."""
        svc = self._make_svc()
        result = await svc.agenerate(prompt="hi")
        assert isinstance(result, str)
        assert result == "response-text"
