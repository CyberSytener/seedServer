"""
Career Upskilling - Skill Gap Analysis + Learning Plan scaffolding.

Provides helper functions to:
- extract required skills from monitored job postings
- compare with user skill profile (CV or self-declared)
- build a structured upskilling plan
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.career.gap_analyzer import JobRequirements, Skill, SkillGapAnalyzer


_DEFAULT_SKILL_KEYWORDS = {
    "python", "java", "javascript", "typescript", "node", "react", "angular",
    "c++", "c#", "go", "golang", "rust", "php", "ruby", "swift", "kotlin",
    "sql", "postgresql", "mysql", "mongodb", "redis", "kafka", "docker",
    "kubernetes", "aws", "azure", "gcp", "terraform", "fastapi", "django",
    "flask", "spring", "dotnet", ".net", "linux", "git", "graphql",
}

_SPLIT_RE = re.compile(r"[\n\r,;/•|]+")
_CLEAN_RE = re.compile(r"[^a-zA-Z0-9+#\-_. ]+")


def _normalize_skill(raw: str) -> str:
    cleaned = _CLEAN_RE.sub(" ", raw.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


def _extract_skills_from_items(items: Iterable[str]) -> Set[str]:
    skills: Set[str] = set()
    for item in items:
        if not item:
            continue
        normalized = _normalize_skill(item)
        if 2 <= len(normalized) <= 60:
            skills.add(normalized)
        for token in _SPLIT_RE.split(item):
            token_norm = _normalize_skill(token)
            if 2 <= len(token_norm) <= 40:
                skills.add(token_norm)
    return skills


def _extract_skills_from_description(description: str, skill_hints: Set[str]) -> Set[str]:
    if not description:
        return set()
    text = _normalize_skill(description)
    found = set()
    for skill in skill_hints:
        if skill and skill in text:
            found.add(skill)
    return found


@dataclass
class SkillGapAnalysis:
    required_skills: List[str]
    matched_skills: List[str]
    missing_skills: List[str]
    gap_score: float
    recommended_focus: List[str]
    job_titles: List[str]
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UpskillingModule:
    title: str
    objectives: List[str]
    recommended_activities: List[str]


@dataclass
class UpskillingPlan:
    target_role: Optional[str]
    duration_weeks: int
    modules: List[UpskillingModule]
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_role": self.target_role,
            "duration_weeks": self.duration_weeks,
            "modules": [asdict(m) for m in self.modules],
            "generated_at": self.generated_at,
        }


def build_skill_gap_analysis(
    *,
    user_skills: Optional[List[str]],
    monitored_jobs: Optional[List[Dict[str, Any]]],
) -> SkillGapAnalysis:
    user_skills = user_skills or []
    monitored_jobs = monitored_jobs or []

    normalized_user = {_normalize_skill(skill) for skill in user_skills if skill}

    required_skills: Set[str] = set()
    job_titles: List[str] = []

    skill_hints = set(_DEFAULT_SKILL_KEYWORDS) | normalized_user

    for job in monitored_jobs:
        job_titles.append(str(job.get("title") or ""))
        required_skills |= _extract_skills_from_items(job.get("required_skills") or [])
        required_skills |= _extract_skills_from_items(job.get("requirements") or [])
        required_skills |= _extract_skills_from_items(job.get("responsibilities") or [])
        required_skills |= _extract_skills_from_items(job.get("tech_stack") or [])
        required_skills |= _extract_skills_from_description(
            job.get("full_description") or "",
            skill_hints,
        )

    # Remove empty skills
    required_skills = {s for s in required_skills if s}

    analyzer = SkillGapAnalyzer()
    report = analyzer.analyze(
        user_skills=[Skill(name=skill) for skill in user_skills if skill],
        job_requirements=JobRequirements(
            skills=sorted(required_skills),
            title=job_titles[0] if job_titles else None,
        ),
    )

    matched = report.matched_skills
    missing = [item.name for item in report.missing_skills]

    gap_score = report.gap_score
    recommended_focus = missing[:5] if missing else []

    return SkillGapAnalysis(
        required_skills=sorted(required_skills),
        matched_skills=matched,
        missing_skills=missing,
        gap_score=round(gap_score, 3),
        recommended_focus=recommended_focus,
        job_titles=[title for title in job_titles if title],
        generated_at=report.generated_at,
    )


def build_upskilling_plan(
    *,
    missing_skills: List[str],
    target_role: Optional[str],
    duration_weeks: int = 8,
) -> UpskillingPlan:
    modules: List[UpskillingModule] = []
    for skill in missing_skills[:8]:
        title = f"Boost {skill}"
        objectives = [
            f"Understand core concepts of {skill}",
            f"Apply {skill} in job-relevant tasks",
            f"Build a portfolio example using {skill}",
        ]
        recommended_activities = [
            f"Complete a guided tutorial on {skill}",
            f"Implement a small project showcasing {skill}",
            f"Practice interview questions for {skill}",
        ]
        modules.append(
            UpskillingModule(
                title=title,
                objectives=objectives,
                recommended_activities=recommended_activities,
            )
        )

    return UpskillingPlan(
        target_role=target_role,
        duration_weeks=duration_weeks,
        modules=modules,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
