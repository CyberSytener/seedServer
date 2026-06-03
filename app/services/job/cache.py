from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.infrastructure.db.postgres import AsyncPGDatabase
from app.services.job.types import JobQuery, RawJob, ScanResult


class PostgresScanCache:
    def __init__(self, db: AsyncPGDatabase, *, ttl_seconds: int = 300) -> None:
        self._db = db
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._ready = False

    async def _ensure_table(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS saga_job_scan_cache (
                    cache_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    query JSONB NOT NULL,
                    jobs JSONB NOT NULL,
                    source_counts JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                """
            )
            self._ready = True

    async def get(self, query: JobQuery) -> ScanResult | None:
        await self._ensure_table()
        cache_key = self._build_key(query)
        row = await self._db.fetchrow(
            """
            SELECT query, jobs, source_counts, created_at
            FROM saga_job_scan_cache
            WHERE cache_key = $1
            """,
            cache_key,
        )
        if not row:
            return None

        created_at = row.get("created_at")
        if created_at and isinstance(created_at, datetime):
            if created_at < datetime.now(timezone.utc) - timedelta(seconds=self._ttl_seconds):
                return None

        jobs_raw = row.get("jobs") or []
        jobs = [self._raw_job_from_dict(item) for item in jobs_raw]
        return ScanResult(
            user_id=query.user_id,
            query=query,
            jobs=jobs,
            source_counts=row.get("source_counts") or {},
        )

    async def set(self, result: ScanResult) -> None:
        await self._ensure_table()
        cache_key = self._build_key(result.query)
        jobs = [self._raw_job_to_dict(job) for job in result.jobs]
        await self._db.execute(
            """
            INSERT INTO saga_job_scan_cache (cache_key, user_id, query, jobs, source_counts, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (cache_key) DO UPDATE
            SET jobs = EXCLUDED.jobs,
                source_counts = EXCLUDED.source_counts,
                created_at = EXCLUDED.created_at
            """,
            cache_key,
            result.user_id,
            json.dumps(dataclasses.asdict(result.query)),
            json.dumps(jobs),
            json.dumps(result.source_counts),
            datetime.now(timezone.utc),
        )

    def _build_key(self, query: JobQuery) -> str:
        payload = dataclasses.asdict(query)
        packed = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(packed.encode("utf-8")).hexdigest()

    @staticmethod
    def _raw_job_to_dict(job: RawJob) -> dict[str, Any]:
        return dataclasses.asdict(job)

    @staticmethod
    def _raw_job_from_dict(data: dict[str, Any]) -> RawJob:
        return RawJob(
            id=str(data.get("id") or ""),
            source=str(data.get("source") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            company=data.get("company"),
            location=data.get("location"),
            skills=list(data.get("skills") or []),
            salary_range=data.get("salary_range"),
            url=data.get("url"),
            external_id=data.get("external_id"),
        )
