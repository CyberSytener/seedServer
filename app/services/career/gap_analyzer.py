"""Skill gap analysis for Phase 3 upskilling workflows."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_skill(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_many(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        if not value:
            continue
        norm = _normalize_skill(value)
        if norm:
            normalized.append(norm)
    return normalized


@dataclass(frozen=True)
class Skill:
    name: str
    level: Optional[str] = None


@dataclass(frozen=True)
class JobRequirements:
    skills: List[str]
    title: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class SkillGapItem:
    name: str
    severity: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SkillGapReport:
    matched_skills: List[str]
    missing_skills: List[SkillGapItem]
    transferable_skills: List[str]
    gap_score: float
    generated_at: str

    @property
    def has_actionable_gaps(self) -> bool:
        return bool(self.missing_skills)

    def to_dict(self) -> dict:
        return {
            "matched_skills": self.matched_skills,
            "missing_skills": [item.to_dict() for item in self.missing_skills],
            "transferable_skills": self.transferable_skills,
            "gap_score": self.gap_score,
            "generated_at": self.generated_at,
        }


class SkillGapAnalyzer:
    """
    Heuristic skill gap analyzer for Phase 3.

    This intentionally avoids LLM calls and can be replaced with
    an LLM-backed implementation once the data contract stabilizes.
    """

    def analyze(
        self,
        user_skills: List[Skill],
        job_requirements: JobRequirements,
    ) -> SkillGapReport:
        user_set = set(_normalize_many([skill.name for skill in user_skills]))
        required_set = set(_normalize_many(job_requirements.skills))

        matched = sorted(required_set & user_set)
        missing = sorted(required_set - user_set)

        missing_items = [
            SkillGapItem(name=item, severity=1.0)
            for item in missing
        ]

        gap_score = (len(missing) / len(required_set)) if required_set else 0.0

        return SkillGapReport(
            matched_skills=matched,
            missing_skills=missing_items,
            transferable_skills=[],
            gap_score=round(gap_score, 3),
            generated_at=_now_iso(),
        )
