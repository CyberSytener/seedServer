from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.services.job.sources.base import JobSource
from app.services.job.types import JobQuery, RawJob


logger = logging.getLogger(__name__)


class ArbetsformedlingenSource(JobSource):
    source_id = "arbetsformedlingen"

    def __init__(self, *, limit: int = 25, timeout_sec: int = 10):
        self._limit = limit
        self._timeout_sec = timeout_sec

    async def search(self, query: JobQuery) -> list[RawJob]:
        keywords = " ".join(query.keywords) if query.keywords else ""
        location = query.location or ""
        query_text = " ".join(part for part in [keywords, location] if part)
        params = {
            "q": query_text,
            "limit": self._limit,
        }
        url = "https://links.api.arbetsformedlingen.se/jobsearch/v1/search"
        headers = {
            "Accept": "application/json",
            "User-Agent": "seed-server-market-watcher/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            payload = response.json()
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
            logger.warning("Arbetsformedlingen search failed: %s", exc)
            return []

        jobs: list[RawJob] = []
        for item in payload.get("hits", [])[: self._limit]:
            job_id = str(item.get("id") or "")
            title = item.get("headline") or item.get("occupation") or ""
            company = item.get("employer") or item.get("employer_name") or ""
            description = item.get("description") or ""
            location = self._extract_location(item)
            external_id = job_id
            jobs.append(
                RawJob(
                    id=job_id or external_id,
                    source=self.source_id,
                    title=title,
                    company=company,
                    description=description,
                    location=location,
                    skills=[],
                    url=item.get("webpage_url"),
                    external_id=external_id,
                )
            )

        return jobs

    async def get_details(self, job_id: str) -> Optional[RawJob]:
        return None

    def estimated_cost_per_query(self) -> float:
        return 0.0

    @staticmethod
    def _extract_location(item: dict) -> str:
        address = item.get("workplace_address") or {}
        fields = [
            address.get("municipality"),
            address.get("city"),
            address.get("country"),
        ]
        return ", ".join([value for value in fields if value]) or ""
