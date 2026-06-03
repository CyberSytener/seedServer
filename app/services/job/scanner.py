from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any, Iterable

from app.services.job.cache import PostgresScanCache
from app.services.job.sources.base import JobSource
from app.services.job.types import JobQuery, RawJob, ScanResult


class JobScanner:
    """Orchestrates multiple job sources and deduplicates results."""

    def __init__(self, sources: Iterable[JobSource], *, cache: PostgresScanCache | None = None):
        self._sources = list(sources)
        self._cache = cache

        self._logger = logging.getLogger(__name__)

    async def scan_for_user(self, user_id: str, persona: dict[str, Any]) -> ScanResult:
        query = self._build_query_from_persona(user_id=user_id, persona=persona)
        return await self.scan(query)

    async def scan(self, query: JobQuery) -> ScanResult:
        if self._cache:
            cached = await self._cache.get(query)
            if cached:
                return cached
        jobs: list[RawJob] = []
        source_counts: Counter[str] = Counter()

        sources = [
            source
            for source in self._sources
            if not query.sources or source.source_id in query.sources
        ]
        tasks = [source.search(query) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for source, result in zip(sources, results):
            if isinstance(result, Exception):
                self._logger.warning("Job source %s failed: %s", source.source_id, result)
                continue
            jobs.extend(result)
            source_counts[source.source_id] += len(result)

        deduped = self._dedupe(jobs)
        result = ScanResult(
            user_id=query.user_id,
            query=query,
            jobs=deduped,
            source_counts=dict(source_counts),
        )
        if self._cache:
            await self._cache.set(result)
        return result

    def _build_query_from_persona(self, *, user_id: str, persona: dict[str, Any]) -> JobQuery:
        raw_keywords = persona.get("keywords") or persona.get("skills") or []
        if isinstance(raw_keywords, str):
            keywords = [value for value in raw_keywords.split() if value]
        else:
            keywords = list(raw_keywords)

        sources = persona.get("sources", []) or []
        if isinstance(sources, str):
            sources = [value for value in sources.split(",") if value]

        return JobQuery(
            user_id=user_id,
            keywords=keywords,
            location=persona.get("location", ""),
            remote_only=bool(persona.get("remote_only", False)),
            salary_min=persona.get("salary_min"),
            sources=list(sources),
        )

    def _dedupe(self, jobs: list[RawJob]) -> list[RawJob]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[RawJob] = []
        for job in jobs:
            key = (
                job.title.strip().lower(),
                (job.company or "").strip().lower(),
                (job.location or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped
