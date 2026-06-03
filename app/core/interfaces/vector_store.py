from __future__ import annotations

from typing import Any, Protocol


class VectorStoreProtocol(Protocol):
    async def upsert_embedding(
        self,
        *,
        entity_type: str,
        entity_id: str,
        text: str,
        embedding: list[float],
        model: str,
    ) -> None: ...

    async def query_similar(
        self,
        *,
        embedding: list[float],
        top_k: int = 10,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]: ...
