from __future__ import annotations

import uuid

from app.services.job.sources.base import JobSource
from app.services.job.types import JobQuery, RawJob


class MockJobSource(JobSource):
    source_id = "mock"

    async def search(self, query: JobQuery) -> list[RawJob]:
        keywords = query.keywords or ["Software Engineer"]
        location = query.location or "Remote"
        jobs: list[RawJob] = []
        for idx, keyword in enumerate(keywords[:5]):
            job_id = str(uuid.uuid4())
            external_id = self._external_id_variant(idx)
            salary_range = self._salary_range(idx)
            jobs.append(
                RawJob(
                    id=job_id,
                    source=self.source_id,
                    title=f"{keyword} ({idx + 1})",
                    company="Mock Co",
                    location=location,
                    description=f"Work on {keyword} systems with a small team.",
                    skills=[keyword, "Python", "Postgres"],
                    salary_range=salary_range,
                    url=f"https://example.com/jobs/{job_id}",
                    external_id=external_id,
                )
            )
        return jobs

    async def get_details(self, job_id: str) -> RawJob | None:
        return None

    def estimated_cost_per_query(self) -> float:
        return 0.0

    @staticmethod
    def _external_id_variant(idx: int) -> str:
        variants = [
            f"mock-{idx + 1}",
            f"MOCK:{idx + 1:04d}",
            f"mock/{idx + 1}",
            f"mock_{idx + 1}_dev",
        ]
        return variants[idx % len(variants)]

    @staticmethod
    def _salary_range(idx: int) -> dict[str, int | str]:
        base = 55000 + (idx * 3000)
        return {
            "min": base,
            "max": base + 15000,
            "currency": "USD",
        }
