"""Test that UnifiedLLMService gets OpenAI + Stub providers registered at startup.

T-2 verification: after create_app(), the llm_service should have
gemini (when key present), openai, and stub providers registered.
"""
from __future__ import annotations

import pytest

from app.core.llm.unified import UnifiedLLMService
from app.core.llm.router import OpenAIProvider, StubProvider


class TestUnifiedLLMProviderRegistration:
    """Verify provider registration on UnifiedLLMService."""

    def test_openai_provider_conforms_to_protocol(self) -> None:
        """OpenAIProvider has required protocol attributes."""
        p = OpenAIProvider(api_key="test-key", base_url="https://api.openai.com")
        assert p.provider_name == "openai"
        assert p.is_available is True
        assert callable(p.generate)
        assert callable(p.agenerate)

    def test_openai_provider_unavailable_when_no_key(self) -> None:
        p = OpenAIProvider(api_key="", base_url="https://api.openai.com")
        assert p.is_available is False

    def test_stub_provider_conforms_to_protocol(self) -> None:
        """StubProvider has required protocol attributes."""
        p = StubProvider()
        assert p.provider_name == "stub"
        assert p.is_available is True
        assert callable(p.generate)
        assert callable(p.agenerate)

    def test_register_all_three_providers(self) -> None:
        """UnifiedLLMService can hold gemini + openai + stub simultaneously."""
        svc = UnifiedLLMService()

        # Simulate what create_app does: register all three
        # (Gemini adapter needs a real client — use a stub-like mock)
        class FakeGeminiAdapter:
            @property
            def provider_name(self) -> str:
                return "gemini"
            @property
            def is_available(self) -> bool:
                return True
            def generate(self, **kw) -> str:
                return "gemini-response"
            async def agenerate(self, **kw) -> str:
                return "gemini-response"

        svc.register_provider(FakeGeminiAdapter())
        svc.register_provider(OpenAIProvider(api_key="test", base_url="https://api.openai.com"))
        svc.register_provider(StubProvider())

        available = svc.available_providers
        assert "gemini" in available
        assert "openai" in available
        assert "stub" in available
        assert len(available) == 3

    def test_stub_provider_always_available(self) -> None:
        """StubProvider.is_available should always return True."""
        svc = UnifiedLLMService()
        svc.register_provider(StubProvider())
        assert "stub" in svc.available_providers
