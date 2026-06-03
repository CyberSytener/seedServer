from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.core.gemini_client import GeminiClient
from app.core.interfaces.database import AsyncDatabaseProtocol
from app.core.interfaces.vector_store import VectorStoreProtocol
from app.services.job.types import RawJob, ScoredJob

logger = logging.getLogger(__name__)


@dataclass
class ScoringConfig:
    top_k: int = 10
    embedding_model: str = "stub-embedding-1536"
    freshness_ttl_seconds: int = 24 * 60 * 60


class DeterministicEmbedder:
    def __init__(self, *, dimensions: int = 1536):
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = _Random(seed)
        return [rng.random() for _ in range(self._dimensions)]


class GeminiEmbedder:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-004",
        dimensions: int | None = None,
    ) -> None:
        self._gemini = GeminiClient(api_key=api_key, default_model=model)
        self._model = model
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        try:
            embedding = self._gemini.embed_content(
                model=self._model,
                content=text,
                task_type="retrieval_document",
            )
            if isinstance(embedding, list):
                if self._dimensions:
                    return embedding[: self._dimensions]
                return embedding
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini embed failed: %s", exc)
        return []


class JobScorer:
    """Scores jobs using vector similarity plus simple heuristics."""

    def __init__(
        self,
        *,
        vector_store: VectorStoreProtocol,
        db: AsyncDatabaseProtocol,
        config: ScoringConfig | None = None,
        embedder: Any | None = None,
    ):
        self._vector_store = vector_store
        self._db = db
        self._config = config or ScoringConfig()
        self._embedder = embedder or DeterministicEmbedder()

    async def score_batch(
        self,
        *,
        user_id: str,
        jobs: list[RawJob],
        persona: dict[str, Any],
        scan_id: str | None = None,
        persist: bool = True,
    ) -> list[ScoredJob]:
        if scan_id is None:
            scan_id = str(uuid.uuid4())

        persona_skills = persona.get("skills", [])
        if isinstance(persona_skills, str):
            persona_skills = [persona_skills]
        persona_embedding = self._embedder.embed(" ".join(persona_skills))
        if not persona_embedding:
            persona_embedding = DeterministicEmbedder().embed(" ".join(persona_skills))

        fresh_keys = set()
        if persist and jobs:
            fresh_keys = await self._fetch_fresh_keys(
                user_id=user_id,
                jobs=jobs,
                ttl_seconds=self._config.freshness_ttl_seconds,
            )

        scored_jobs: list[ScoredJob] = []
        lead_rows: list[tuple[Any, ...]] = []
        embedding_rows: list[tuple[Any, ...]] = []

        for job in jobs:
            external_id = job.external_id or job.id
            if persist and (job.source, external_id) in fresh_keys:
                continue

            job_embedding = self._embedder.embed(self._job_text(job))
            if not job_embedding:
                job_embedding = DeterministicEmbedder().embed(self._job_text(job))
            similarity = _cosine_similarity(job_embedding, persona_embedding)
            scores = self._build_scores(job, persona, similarity)
            scored = ScoredJob.from_raw(
                job,
                scores=scores,
                score_stage=1,
            )
            scored_jobs.append(scored)

            if persist:
                lead_id = self._ensure_uuid(scored.id)
                embedding_rows.append(
                    (
                        "job_description",
                        job.id,
                        job.description,
                        job_embedding,
                        self._config.embedding_model,
                    )
                )
                lead_rows.append(
                    (
                        lead_id,
                        user_id,
                        scored.source,
                        external_id,
                        scored.title,
                        scored.company,
                        scored.location,
                        scored.salary_range,
                        scored.description,
                        scored.skills,
                        job_embedding,
                        self._config.embedding_model,
                        scored.scores,
                        scored.score_stage,
                        scored.match_reason,
                        "new",
                        scan_id,
                    )
                )

        if persist and scored_jobs:
            await asyncio.gather(
                self._upsert_embeddings_batch(embedding_rows),
                self._upsert_job_leads_batch(lead_rows),
            )

        return scored_jobs

    async def _upsert_job_lead(
        self,
        *,
        user_id: str,
        scan_id: str,
        scored: ScoredJob,
        embedding: list[float],
    ) -> None:
        external_id = scored.external_id or scored.id
        lead_id = self._ensure_uuid(scored.id)
        await self._db.execute(
            """
            INSERT INTO job_leads (
                id,
                user_id,
                source,
                external_id,
                title,
                company,
                location,
                salary_range,
                description,
                skills,
                embedding,
                embedding_model,
                embedding_updated_at,
                scores,
                score_stage,
                match_reason,
                status,
                scan_id
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,now(),$13,$14,$15,$16,$17)
            ON CONFLICT (user_id, source, external_id) DO UPDATE
            SET title = EXCLUDED.title,
                company = EXCLUDED.company,
                location = EXCLUDED.location,
                salary_range = EXCLUDED.salary_range,
                description = EXCLUDED.description,
                skills = EXCLUDED.skills,
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model,
                embedding_updated_at = EXCLUDED.embedding_updated_at,
                scores = EXCLUDED.scores,
                score_stage = EXCLUDED.score_stage,
                match_reason = EXCLUDED.match_reason,
                status = EXCLUDED.status,
                scan_id = EXCLUDED.scan_id
            """,
            lead_id,
            user_id,
            scored.source,
            external_id,
            scored.title,
            scored.company,
            scored.location,
            scored.salary_range,
            scored.description,
            scored.skills,
            embedding,
            self._config.embedding_model,
            scored.scores,
            scored.score_stage,
            scored.match_reason,
            "new",
            scan_id,
        )

    async def _upsert_job_leads_batch(self, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return

        (
            ids,
            user_ids,
            sources,
            external_ids,
            titles,
            companies,
            locations,
            salary_ranges,
            descriptions,
            skills_list,
            embeddings,
            embedding_models,
            scores_list,
            score_stages,
            match_reasons,
            statuses,
            scan_ids,
        ) = zip(*rows)

        embedding_texts = [self._embedding_to_text(value) for value in embeddings]
        salary_texts = [json.dumps(value) if value is not None else None for value in salary_ranges]
        skills_texts = [json.dumps(value) if value is not None else None for value in skills_list]
        scores_texts = [json.dumps(value) if value is not None else None for value in scores_list]

        await self._db.execute(
            """
            INSERT INTO job_leads (
                id,
                user_id,
                source,
                external_id,
                title,
                company,
                location,
                salary_range,
                description,
                skills,
                embedding,
                embedding_model,
                embedding_updated_at,
                scores,
                score_stage,
                match_reason,
                status,
                scan_id
            )
            SELECT
                t.id,
                t.user_id,
                t.source,
                t.external_id,
                t.title,
                t.company,
                t.location,
                t.salary_range::jsonb,
                t.description,
                t.skills::jsonb,
                t.embedding::vector,
                t.embedding_model,
                now(),
                t.scores::jsonb,
                t.score_stage,
                t.match_reason,
                t.status,
                t.scan_id
            FROM UNNEST(
                $1::uuid[],
                $2::uuid[],
                $3::text[],
                $4::text[],
                $5::text[],
                $6::text[],
                $7::text[],
                $8::text[],
                $9::text[],
                $10::text[],
                $11::text[],
                $12::text[],
                $13::text[],
                $14::smallint[],
                $15::text[],
                $16::text[],
                $17::uuid[]
            ) AS t(
                id,
                user_id,
                source,
                external_id,
                title,
                company,
                location,
                salary_range,
                description,
                skills,
                embedding,
                embedding_model,
                scores,
                score_stage,
                match_reason,
                status,
                scan_id
            )
            ON CONFLICT (user_id, source, external_id) DO UPDATE
            SET title = EXCLUDED.title,
                company = EXCLUDED.company,
                location = EXCLUDED.location,
                salary_range = EXCLUDED.salary_range,
                description = EXCLUDED.description,
                skills = EXCLUDED.skills,
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model,
                embedding_updated_at = EXCLUDED.embedding_updated_at,
                scores = EXCLUDED.scores,
                score_stage = EXCLUDED.score_stage,
                match_reason = EXCLUDED.match_reason,
                status = EXCLUDED.status,
                scan_id = EXCLUDED.scan_id
            """,
            list(ids),
            list(user_ids),
            list(sources),
            list(external_ids),
            list(titles),
            list(companies),
            list(locations),
            list(salary_texts),
            list(descriptions),
            list(skills_texts),
            list(embedding_texts),
            list(embedding_models),
            list(scores_texts),
            list(score_stages),
            list(match_reasons),
            list(statuses),
            list(scan_ids),
        )

    async def _upsert_embeddings_batch(self, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return

        if hasattr(self._vector_store, "upsert_embeddings"):
            await getattr(self._vector_store, "upsert_embeddings")(rows=rows)
            return

        for row in rows:
            entity_type, entity_id, text, embedding, model = row
            await self._vector_store.upsert_embedding(
                entity_type=entity_type,
                entity_id=entity_id,
                text=text,
                embedding=embedding,
                model=model,
            )
    
    @staticmethod
    def _embedding_to_text(embedding: list[float]) -> str:
        return "[" + ",".join(repr(value) for value in embedding) + "]"

    @staticmethod
    def _ensure_uuid(value: str) -> str:
        try:
            uuid.UUID(value)
            return value
        except ValueError:
            return str(uuid.uuid4())

    async def _fetch_fresh_keys(
        self,
        *,
        user_id: str,
        jobs: list[RawJob],
        ttl_seconds: int,
    ) -> set[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for job in jobs:
            external_id = job.external_id or job.id
            if external_id:
                pairs.append((job.source, external_id))

        if not pairs:
            return set()

        sources = [pair[0] for pair in pairs]
        external_ids = [pair[1] for pair in pairs]
        rows = await self._db.fetch(
            """
            WITH incoming AS (
                SELECT * FROM UNNEST($2::text[], $3::text[]) AS t(source, external_id)
            )
            SELECT jl.source, jl.external_id
            FROM job_leads jl
            JOIN incoming i ON jl.source = i.source AND jl.external_id = i.external_id
            WHERE jl.user_id = $1
              AND jl.embedding_updated_at > NOW() - make_interval(secs => $4)
            """,
            user_id,
            sources,
            external_ids,
            ttl_seconds,
        )
        return {(row["source"], row["external_id"]) for row in rows}

    def _build_scores(self, job: RawJob, persona: dict[str, Any], similarity: float) -> dict[str, float]:
        location_pref = (persona.get("location", "") or "").lower()
        location = (job.location or "").lower()
        location_match = 1.0 if location_pref and location_pref in location else 0.0

        remote_only = bool(persona.get("remote_only", False))
        remote_hit = 1.0 if remote_only and "remote" in location else 0.0

        composite = (similarity * 0.7) + (location_match * 0.2) + (remote_hit * 0.1)
        return {
            "skill_match": round(similarity * 100, 2),
            "location_match": round(location_match * 100, 2),
            "remote_match": round(remote_hit * 100, 2),
            "composite": round(composite * 100, 2),
        }

    @staticmethod
    def _job_text(job: RawJob) -> str:
        parts = [job.title, job.description]
        if job.skills:
            parts.append(" ".join(job.skills))
        return " ".join(p for p in parts if p)


class _Random:
    def __init__(self, seed: int):
        self._state = seed & 0xFFFFFFFFFFFFFFFF

    def random(self) -> float:
        self._state = (6364136223846793005 * self._state + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        return (self._state >> 11) / float(1 << 53)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (math.sqrt(norm_a) * math.sqrt(norm_b))))
