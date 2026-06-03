"""Unified LLM service — single entry-point for all LLM calls.

``UnifiedLLMService`` is a facade that holds registered ``LLMProvider``
instances and routes ``generate`` / ``agenerate`` requests to the correct
backend.

``GeminiClientAdapter`` wraps the existing ``GeminiClient`` so that NeoEats
code (``LLMEngine``) can go through the same protocol as the general-purpose
router.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.core.llm.protocol import LLMProvider, LLMVisionProvider, GenerationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GeminiClientAdapter — adapts GeminiClient → LLMProvider + LLMVisionProvider
# ---------------------------------------------------------------------------

class GeminiClientAdapter:
    """Adapts :class:`app.core.gemini_client.GeminiClient` to the
    ``LLMProvider`` **and** ``LLMVisionProvider`` protocols.

    The adapter is intentionally thin: all heavy lifting (SDK negotiation,
    retry, base64 encoding) stays inside ``GeminiClient``.
    """

    def __init__(self, gemini_client: Any, *, default_model: str = "gemini-1.5-flash") -> None:
        self._client = gemini_client
        self._default_model = default_model

    # -- LLMProvider properties ------------------------------------------------

    @property
    def provider_name(self) -> str:  # noqa: D401 — protocol
        return "gemini"

    @property
    def is_available(self) -> bool:  # noqa: D401 — protocol
        return self._client is not None

    # -- LLMProvider.generate --------------------------------------------------

    def generate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Synchronous text generation via ``GeminiClient.generate_content``."""
        if not self._client:
            return ""
        full_prompt = f"{system_instruction}\n\n{prompt}".strip() if system_instruction else prompt
        gen_config: Dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            gen_config["temperature"] = temperature
        return self._client.generate_content(
            full_prompt,
            model=model or self._default_model,
            generation_config=gen_config,
        )

    # -- LLMProvider.agenerate -------------------------------------------------

    async def agenerate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Async text generation via ``GeminiClient.generate_content_async``."""
        if not self._client:
            return ""
        full_prompt = f"{system_instruction}\n\n{prompt}".strip() if system_instruction else prompt
        gen_config: Dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            gen_config["temperature"] = temperature
        return await self._client.generate_content_async(
            full_prompt,
            model=model or self._default_model,
            generation_config=gen_config,
        )

    # -- LLMVisionProvider.generate_with_image ---------------------------------

    def generate_with_image(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 4096,
    ) -> str:
        if not self._client:
            return ""
        contents = [
            prompt,
            {"mime_type": mime_type, "data": image_bytes},
        ]
        gen_config: Dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            gen_config["temperature"] = temperature
        return self._client.generate_content(
            contents,
            model=model or self._default_model,
            generation_config=gen_config,
        )

    # -- LLMVisionProvider.agenerate_with_image --------------------------------

    async def agenerate_with_image(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int = 4096,
    ) -> str:
        if not self._client:
            return ""
        contents = [
            prompt,
            {"mime_type": mime_type, "data": image_bytes},
        ]
        gen_config: Dict[str, Any] = {"maxOutputTokens": max_tokens}
        if temperature is not None:
            gen_config["temperature"] = temperature
        return await self._client.generate_content_async(
            contents,
            model=model or self._default_model,
            generation_config=gen_config,
        )


# ---------------------------------------------------------------------------
# UnifiedLLMService
# ---------------------------------------------------------------------------

class UnifiedLLMService:
    """Central LLM service that routes requests to the appropriate provider.

    This is the **single entry point** for all LLM calls in the application.
    Replaces direct usage of ``GeminiClient`` or individual providers.

    Usage::

        svc = UnifiedLLMService()
        svc.register_provider(my_adapter)
        text = svc.generate(prompt="Hello")
    """

    def __init__(self, settings: Any = None) -> None:
        self._providers: Dict[str, LLMProvider] = {}
        self._default_provider: str = "gemini"
        self._settings = settings

    # -- registration ----------------------------------------------------------

    def register_provider(self, provider: LLMProvider) -> None:
        """Register *provider* under its ``provider_name``."""
        name = provider.provider_name
        self._providers[name] = provider
        logger.info("UnifiedLLMService: registered provider %r", name)

    @property
    def available_providers(self) -> list[str]:
        return [n for n, p in self._providers.items() if p.is_available]

    @property
    def default_provider(self) -> str:
        return self._default_provider

    @default_provider.setter
    def default_provider(self, name: str) -> None:
        self._default_provider = name

    # -- provider lookup -------------------------------------------------------

    def get_provider(self, name: str = "default") -> LLMProvider:
        """Return the provider registered under *name* (or the default)."""
        if name == "default":
            name = self._default_provider
        provider = self._providers.get(name)
        if provider is None:
            raise KeyError(f"No LLM provider registered under {name!r}. "
                           f"Available: {list(self._providers)}")
        return provider

    # -- convenience wrappers --------------------------------------------------

    def generate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        provider: str = "default",
        **kwargs: Any,
    ) -> str:
        """Synchronous generation via the named (or default) provider."""
        return self.get_provider(provider).generate(
            prompt=prompt,
            system_instruction=system_instruction,
            **kwargs,
        )

    async def agenerate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        provider: str = "default",
        **kwargs: Any,
    ) -> str:
        """Async generation via the named (or default) provider."""
        return await self.get_provider(provider).agenerate(
            prompt=prompt,
            system_instruction=system_instruction,
            **kwargs,
        )

    # -- metadata-rich wrappers ------------------------------------------------

    def generate_with_metadata(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        provider: str = "default",
        model: str | None = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """Like :meth:`generate`, but returns a :class:`GenerationResult`.

        Token counts are not yet populated by individual providers (they
        return plain ``str``), so ``tokens_in`` / ``tokens_out`` default to 0.
        The wrapper still records *provider* and *model* so that callers can
        start building cost-tracking / analytics pipelines.
        """
        p = self.get_provider(provider)
        text = p.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            model=model,
            **kwargs,
        )
        return GenerationResult(
            text=text,
            provider=p.provider_name,
            model=model or "",
        )

    async def agenerate_with_metadata(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        provider: str = "default",
        model: str | None = None,
        **kwargs: Any,
    ) -> GenerationResult:
        """Async version of :meth:`generate_with_metadata`."""
        p = self.get_provider(provider)
        text = await p.agenerate(
            prompt=prompt,
            system_instruction=system_instruction,
            model=model,
            **kwargs,
        )
        return GenerationResult(
            text=text,
            provider=p.provider_name,
            model=model or "",
        )
