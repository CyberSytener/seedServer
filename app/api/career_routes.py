from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import authenticate
from app.infrastructure.db.sqlite import DB
from app.models.api import (
    CareerAnalysisPatchRequest,
    CareerAnalysisResponse,
    CareerLearningTrack,
    CareerLesson,
    CareerLessonCreateRequest,
    CareerLessonListResponse,
    CareerUpskillingRequest,
    CareerUpskillingResponse,
    LearningPlanContract,
)


def build_career_router(
    *,
    db: DB,
    job_id_factory: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/career/upskilling/plan", response_model=CareerUpskillingResponse, tags=["career"])
    async def generate_career_upskilling_plan(req: CareerUpskillingRequest):
        """
        Generate an upskilling plan from user base data + market gap data.

        Uses:
        - UserBaseData (CV + profile)
        - MarketGapData (job search monitoring)
        - Optional PlacementResults
        """
        from app.services.career.upskilling import build_upskilling_plan

        target_role = req.target_role or (
            req.user_base_data.target_roles[0] if req.user_base_data.target_roles else None
        )

        plan = build_upskilling_plan(
            missing_skills=req.market_gap_data.missing_skills,
            target_role=target_role,
            duration_weeks=req.duration_weeks,
        )

        curriculum_id = f"curr_{job_id_factory()}"
        learning_plan = LearningPlanContract(
            curriculum_id=curriculum_id,
            modules=plan.to_dict().get("modules", []),
            success_threshold=req.success_threshold,
        )

        return CareerUpskillingResponse(
            learning_plan=learning_plan,
            missing_skills=req.market_gap_data.missing_skills,
            critical_weakness=req.market_gap_data.critical_weakness,
            priority_level=req.market_gap_data.priority_level,
        )

    @router.post("/v1/career/analysis", response_model=CareerAnalysisResponse, tags=["career-learning"])
    async def create_career_analysis(req: CareerUpskillingRequest, request: Request):
        """Create and store an editable career analysis for the user."""
        from app import career_learning

        ctx = authenticate(request, db)
        return career_learning.create_analysis(db, ctx.user_id, req)

    @router.get("/v1/career/analysis/{analysis_id}", response_model=CareerAnalysisResponse, tags=["career-learning"])
    async def get_career_analysis(analysis_id: str, request: Request):
        """Get a stored career analysis for viewing and editing."""
        from app import career_learning

        ctx = authenticate(request, db)
        analysis = career_learning.get_analysis(db, ctx.user_id, analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="analysis_not_found")
        return analysis

    @router.patch("/v1/career/analysis/{analysis_id}", response_model=CareerAnalysisResponse, tags=["career-learning"])
    async def patch_career_analysis(analysis_id: str, req: CareerAnalysisPatchRequest, request: Request):
        """Patch an existing analysis (user edits)."""
        from app import career_learning

        ctx = authenticate(request, db)
        updated = career_learning.patch_analysis(db, ctx.user_id, analysis_id, req)
        if not updated:
            raise HTTPException(status_code=404, detail="analysis_not_found")
        return updated

    @router.post("/v1/career/analysis/{analysis_id}/track", response_model=CareerLearningTrack, tags=["career-learning"])
    async def create_career_track(analysis_id: str, request: Request):
        """Create a learning track from an existing analysis."""
        from app import career_learning

        ctx = authenticate(request, db)
        analysis = career_learning.get_analysis(db, ctx.user_id, analysis_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="analysis_not_found")
        return career_learning.create_track(db, ctx.user_id, analysis)

    @router.get("/v1/career/tracks", response_model=list[CareerLearningTrack], tags=["career-learning"])
    async def list_career_tracks(request: Request):
        """List career learning tracks for the user."""
        from app import career_learning

        ctx = authenticate(request, db)
        return career_learning.list_tracks(db, ctx.user_id)

    @router.get("/v1/career/tracks/{track_id}", response_model=CareerLearningTrack, tags=["career-learning"])
    async def get_career_track(track_id: str, request: Request):
        """Get a specific career learning track with progress."""
        from app import career_learning

        ctx = authenticate(request, db)
        track = career_learning.get_track(db, ctx.user_id, track_id)
        if not track:
            raise HTTPException(status_code=404, detail="track_not_found")
        return track

    @router.patch("/v1/career/tracks/{track_id}/modules/{module_id}", response_model=CareerLearningTrack, tags=["career-learning"])
    async def update_career_module_status(track_id: str, module_id: str, status: str, request: Request):
        """Update module status (planned|in_progress|completed) and recompute progress."""
        from app import career_learning

        ctx = authenticate(request, db)
        updated = career_learning.set_module_status(db, ctx.user_id, track_id, module_id, status)
        if not updated:
            raise HTTPException(status_code=404, detail="track_or_module_not_found")
        return updated

    @router.post("/v1/career/tracks/{track_id}/lessons", response_model=CareerLesson, tags=["career-learning"])
    async def create_career_lesson(track_id: str, req: CareerLessonCreateRequest, request: Request):
        """Create a background lesson for a module (user can open later)."""
        from app import career_learning

        ctx = authenticate(request, db)
        track = career_learning.get_track(db, ctx.user_id, track_id)
        if not track:
            raise HTTPException(status_code=404, detail="track_not_found")
        return career_learning.create_lesson(db, ctx.user_id, track_id, req)

    @router.get("/v1/career/lessons", response_model=CareerLessonListResponse, tags=["career-learning"])
    async def list_career_lessons(request: Request, status: Optional[str] = None):
        """List background career lessons (optionally filter by status)."""
        from app import career_learning

        ctx = authenticate(request, db)
        lessons = career_learning.list_lessons(db, ctx.user_id, status=status)
        return CareerLessonListResponse(lessons=lessons, total=len(lessons))

    @router.patch("/v1/career/lessons/{lesson_id}", response_model=CareerLesson, tags=["career-learning"])
    async def update_career_lesson_status(lesson_id: str, status: str, request: Request):
        """Update background lesson status (ready|in_progress|completed)."""
        from app import career_learning

        ctx = authenticate(request, db)
        updated = career_learning.update_lesson_status(db, ctx.user_id, lesson_id, status)
        if not updated:
            raise HTTPException(status_code=404, detail="lesson_not_found")
        return updated

    return router
