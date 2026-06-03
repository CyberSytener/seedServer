from __future__ import annotations

import hashlib
from typing import List

from app.core.embeddings import SimpleEmbeddingService


class StubEmbeddingService(SimpleEmbeddingService):
    """Deterministic stub embedding service for tests/dev."""

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    async def embed_text(self, text: str) -> list[float]:
        return self._hash_to_vector(text)

    async def embed_texts(self, texts: List[str]) -> list[list[float]]:
        return [self._hash_to_vector(text) for text in texts]

    def _hash_to_vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
        values = [b / 255.0 for b in digest]
        vec = (values * ((self.dimension // len(values)) + 1))[: self.dimension]
        return vec
