from __future__ import annotations

from typing import Any, Protocol


class LLMClientProtocol(Protocol):
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        provider: str = "gemini",
        model: str | None = None,
        max_tokens: int = 12000,
        timeout_sec: int = 60,
        max_retries: int = 3,
    ) -> Any: ...
