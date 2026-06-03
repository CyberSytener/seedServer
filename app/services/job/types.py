from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class JobQuery:
    user_id: str
    keywords: list[str] = field(default_factory=list)
    location: str = ""
    remote_only: bool = False
    salary_min: Optional[int] = None
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RawJob:
    id: str
    source: str
    title: str
    description: str
    company: Optional[str] = None
    location: Optional[str] = None
    skills: list[str] = field(default_factory=list)
    salary_range: Optional[dict[str, int | str]] = None
    url: Optional[str] = None
    external_id: Optional[str] = None


@dataclass(frozen=True)
class ScoredJob:
    id: str
    source: str
    title: str
    description: str
    company: Optional[str]
    location: Optional[str]
    skills: list[str]
    salary_range: Optional[dict[str, int | str]]
    url: Optional[str]
    external_id: Optional[str]
    scores: dict[str, float]
    score_stage: int
    match_reason: Optional[str] = None

    @classmethod
    def from_raw(
        cls,
        raw: RawJob,
        *,
        scores: dict[str, float],
        score_stage: int,
        match_reason: Optional[str] = None,
    ) -> "ScoredJob":
        return cls(
            id=raw.id,
            source=raw.source,
            title=raw.title,
            description=raw.description,
            company=raw.company,
            location=raw.location,
            skills=list(raw.skills),
            salary_range=raw.salary_range,
            url=raw.url,
            external_id=raw.external_id,
            scores=scores,
            score_stage=score_stage,
            match_reason=match_reason,
        )


@dataclass(frozen=True)
class ScanResult:
    user_id: str
    query: JobQuery
    jobs: list[RawJob]
    source_counts: dict[str, int] = field(default_factory=dict)
