from __future__ import annotations

from typing import Any

from app.core.interfaces.database import AsyncDatabaseProtocol
from app.core.interfaces.vector_store import VectorStoreProtocol


class PgvectorStore(VectorStoreProtocol):
    """pgvector-backed vector store for semantic similarity search."""

    def __init__(self, db: AsyncDatabaseProtocol, *, table: str = "skill_embeddings"):
        self._db = db
        self._table = table

    async def upsert_embedding(
        self,
        *,
        entity_type: str,
        entity_id: str,
        text: str,
        embedding: list[float],
        model: str,
    ) -> None:
        await self._db.execute(
            f"""
            INSERT INTO {self._table} (entity_type, entity_id, text, embedding, model)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (entity_type, entity_id) DO UPDATE
            SET text = EXCLUDED.text,
                embedding = EXCLUDED.embedding,
                model = EXCLUDED.model,
                created_at = NOW()
            """,
            entity_type,
            entity_id,
            text,
            embedding,
            model,
        )

    async def upsert_embeddings(self, *, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return

        entity_types, entity_ids, texts, embeddings, models = zip(*rows)
        embedding_texts = [self._embedding_to_text(value) for value in embeddings]
        await self._db.execute(
            f"""
            INSERT INTO {self._table} (entity_type, entity_id, text, embedding, model)
            SELECT
                t.entity_type,
                t.entity_id,
                t.text,
                t.embedding::vector,
                t.model
            FROM UNNEST(
                $1::text[],
                $2::text[],
                $3::text[],
                $4::text[],
                $5::text[]
            ) AS t(entity_type, entity_id, text, embedding, model)
            ON CONFLICT (entity_type, entity_id) DO UPDATE
            SET text = EXCLUDED.text,
                embedding = EXCLUDED.embedding,
                model = EXCLUDED.model,
                created_at = NOW()
            """,
            list(entity_types),
            list(entity_ids),
            list(texts),
            list(embedding_texts),
            list(models),
        )

    @staticmethod
    def _embedding_to_text(embedding: list[float]) -> str:
        return "[" + ",".join(repr(value) for value in embedding) + "]"

    async def query_similar(
        self,
        *,
        embedding: list[float],
        top_k: int = 10,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if entity_type:
            rows = await self._db.fetch(
                f"""
                SELECT entity_id, entity_type, text, model,
                       1 - (embedding <=> $1) AS similarity
                FROM {self._table}
                WHERE entity_type = $2
                ORDER BY embedding <=> $1
                LIMIT $3
                """,
                embedding,
                entity_type,
                top_k,
            )
        else:
            rows = await self._db.fetch(
                f"""
                SELECT entity_id, entity_type, text, model,
                       1 - (embedding <=> $1) AS similarity
                FROM {self._table}
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                embedding,
                top_k,
            )

        return [dict(row) for row in rows]
