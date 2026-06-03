"""Unified LLM provider protocol — the single contract for all LLM backends.

Every LLM backend in the application (Gemini SDK, OpenAI REST, stub, etc.)
must satisfy `LLMProvider`.  Vision-capable backends additionally satisfy
`LLMVisionProvider`.

These are *structural* (duck-typed) protocols — no inheritance required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Structured result — returned by ``*_with_metadata`` methods
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GenerationResult:
    """Structured output from an LLM generation call.

    ``text`` is the raw generated content (same as what ``generate()`` returns).
    The remaining fields carry provider-reported metadata that callers (e.g.
    the saga orchestrator) can use for cost tracking, logging, and analytics.

    Fields default to safe zero-values so partial metadata is acceptable.
    """
    text: str
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Synchronous / async text-generation provider."""

    @property
    def provider_name(self) -> str:
        """Short identifier, e.g. ``"gemini"``, ``"openai"``, ``"stub"``."""
        ...

    @property
    def is_available(self) -> bool:
        """Return *True* when the provider is configured and ready."""
        ...

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
        """Synchronous text generation.  Returns raw text."""
        ...

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
        """Async text generation.  Returns raw text."""
        ...


@runtime_checkable
class LLMVisionProvider(Protocol):
    """Provider that additionally supports image input."""

    @property
    def provider_name(self) -> str: ...

    @property
    def is_available(self) -> bool: ...

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
        """Synchronous vision generation.  Returns raw text."""
        ...

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
        """Async vision generation.  Returns raw text."""
        ...
