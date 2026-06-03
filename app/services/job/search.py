"""
Job search data models.

The scraping-based IndeedScraper and JobAggregator have been **removed** as part
of Phase 3 (async correctness / dead-code cleanup).  Only the data-class
contracts remain so that existing references keep working.

A proper job-board API integration is planned for a future phase.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class JobVacancy:
    """Represents a single job vacancy."""

    title: str
    company: str
    location: str
    description: str
    required_skills: list[str]
    salary_range: Optional[str] = None
    url: Optional[str] = None
    posted_date: Optional[datetime] = None
    experience_years: Optional[int] = None


@dataclass
class JobSearchResult:
    """Results from job search query."""

    query: str
    location: str
    total_found: int
    vacancies: list[JobVacancy]
    source: str
