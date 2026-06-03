from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.services.job.sources.base import JobSource
from app.services.job.types import JobQuery, RawJob


logger = logging.getLogger(__name__)


class RemotiveJobSource(JobSource):
    source_id = "remotive"

    def __init__(self, *, category: str = "software-dev", limit: int = 25, timeout_sec: int = 10):
        self._category = category
        self._limit = limit
        self._timeout_sec = timeout_sec

    async def search(self, query: JobQuery) -> list[RawJob]:
        keywords = " ".join(query.keywords) if query.keywords else ""
        location = query.location or ""
        params = {
            "category": self._category,
            "limit": self._limit,
        }
        if keywords:
            params["search"] = keywords
        if location:
            params["location"] = location
        url = "https://remotive.com/api/remote-jobs"
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
            logger.warning("Remotive search failed: %s", exc)
            return []

        jobs: list[RawJob] = []
        for item in payload.get("jobs", [])[: self._limit]:
            job_id = str(item.get("id") or "")
            title = item.get("title") or ""
            company = item.get("company_name") or ""
            description = item.get("description") or ""
            location = item.get("candidate_required_location") or "Remote"
            tags = item.get("tags") or []
            external_id = job_id or item.get("url") or ""
            jobs.append(
                RawJob(
                    id=job_id or external_id,
                    source=self.source_id,
                    title=title,
                    company=company,
                    description=description,
                    location=location,
                    skills=[str(tag) for tag in tags],
                    url=item.get("url"),
                    external_id=external_id,
                )
            )

        return jobs

    async def get_details(self, job_id: str) -> Optional[RawJob]:
        return None

    def estimated_cost_per_query(self) -> float:
        return 0.0
