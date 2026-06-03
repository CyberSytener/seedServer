"""Deprecated endpoint stubs — extracted from app.main.

These endpoints return 501 until proper API integrations are added.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.api import (
    JobSearchRequest,
    JobSearchResponse,
    MarketAnalysisRequest,
    MarketAnalysisResponse,
)

router = APIRouter()


@router.post("/v1/job/search", response_model=JobSearchResponse, tags=["job_search"])
async def search_jobs(req: JobSearchRequest):
    """
    Search for job vacancies.

    .. deprecated::
        The scraping-based implementation has been removed.
        This endpoint now returns 501 until a proper job-board API
        integration is implemented.
    """
    raise HTTPException(
        status_code=501,
        detail="Job search scraping is deprecated. A proper API integration is planned.",
    )


@router.post("/v1/job/market-analysis", response_model=MarketAnalysisResponse, tags=["job_search"])
async def analyze_job_market(req: MarketAnalysisRequest):
    """
    Analyze job market demand for a specific role.

    .. deprecated::
        The scraping-based implementation has been removed.
        This endpoint now returns 501 until a proper job-board API
        integration is implemented.
    """
    raise HTTPException(
        status_code=501,
        detail="Market analysis scraping is deprecated. A proper API integration is planned.",
    )
