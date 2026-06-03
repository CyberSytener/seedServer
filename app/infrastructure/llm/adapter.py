from __future__ import annotations

from typing import Any

from app.core.interfaces.llm_client import LLMClientProtocol
from .client import AsyncLLMClient


class LLMClientAdapter(LLMClientProtocol):
    """Adapter exposing AsyncLLMClient through the Core LLMClient protocol."""

    def __init__(self, client: AsyncLLMClient):
        self._client = client

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        provider: str = "gemini",
        model: str | None = None,
        max_tokens: int = 12000,
        timeout_sec: int = 60,
        max_retries: int = 3,
    ) -> Any:
        return await self._client.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )
