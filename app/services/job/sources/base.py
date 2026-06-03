from __future__ import annotations

from typing import Optional, Protocol

from app.services.job.types import JobQuery, RawJob


class JobSource(Protocol):
    source_id: str

    async def search(self, query: JobQuery) -> list[RawJob]: ...

    async def get_details(self, job_id: str) -> Optional[RawJob]: ...

    def estimated_cost_per_query(self) -> float: ...
