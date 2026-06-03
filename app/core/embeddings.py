from __future__ import annotations

from typing import Protocol


class SimpleEmbeddingService(Protocol):
    """Core embedding service interface (stub-friendly)."""

    async def embed_text(self, text: str) -> list[float]: ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
