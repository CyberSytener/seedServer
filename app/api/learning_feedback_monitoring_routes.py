from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import authenticate, require_admin_key
from app.models.api import (
    BugReportRequest,
    BugReportResponse,
    GenerateLearningPlanRequest,
    GenerateLearningPlanResponse,
    GetLearningProfileResponse,
    LearningPreferences,
    LearningProfile,
    PatchLearningProfileRequest,
    UpsertLearningProfileRequest,
    UpsertLearningProfileResponse,
)
from app.services.product_normalize import _now_iso


def build_learning_feedback_monitoring_router(*, db) -> APIRouter:
    """Build router with all learning / feedback / monitoring endpoints.

    Parameters
    ----------
    db : app.infrastructure.db.sqlite.DB
        The shared SQLite database handle created in ``create_app()``.
    """
    router = APIRouter()

    # ========================================================================
    # Learning Profile Endpoints
    # ========================================================================

    @router.get(
        "/v1/learning/profile",
        response_model=GetLearningProfileResponse,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def get_learning_profile(request: Request):
        """
        Get user's learning profile.

        Returns 404 if no profile exists yet.
        """
        ctx = authenticate(request, db)

        try:
            row = db.fetchone(
                "SELECT profile_json, version, updated_at FROM learning_profiles WHERE user_id = ?",
                (ctx.user_id,)
            )

            if not row:
                raise HTTPException(status_code=404, detail="profile_not_found")

            profile_data = json.loads(row["profile_json"])
            profile = LearningProfile.model_validate(profile_data)

            return GetLearningProfileResponse(profile=profile)

        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error getting learning profile: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.post(
        "/v1/learning/profile/upsert",
        response_model=UpsertLearningProfileResponse,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def upsert_learning_profile(req: UpsertLearningProfileRequest, request: Request):
        """
        Upsert (create or update) user's learning profile.

        Stores full profile JSON for AI analysis.
        """
        ctx = authenticate(request, db)

        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            req.profile.updated_at = now_iso

            # Serialize to JSON
            profile_json = req.profile.model_dump_json(by_alias=True)

            # Upsert to database
            db.execute(
                """
                INSERT INTO learning_profiles (user_id, profile_json, version, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (ctx.user_id, profile_json, req.profile.version, now_iso)
            )

            logging.info(
                f"Upserted learning profile for user {ctx.user_id}",
                extra={"user_id": ctx.user_id, "version": req.profile.version}
            )

            return UpsertLearningProfileResponse(ok=True, updatedAt=now_iso)

        except Exception as e:
            logging.error(f"Error upserting learning profile: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.patch(
        "/v1/learning/profile",
        response_model=GetLearningProfileResponse,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def patch_learning_profile(req: PatchLearningProfileRequest, request: Request):
        """
        Patch user's learning profile with updated fields.

        Merges updates into existing profile and returns updated profile.
        Creates new profile if none exists (with defaults).
        """
        ctx = authenticate(request, db)

        try:
            now_iso = datetime.now(timezone.utc).isoformat()

            # Load existing profile or create new one
            row = db.fetchone(
                "SELECT profile_json FROM learning_profiles WHERE user_id = ?",
                (ctx.user_id,)
            )

            if row:
                profile_data = json.loads(row["profile_json"])
                profile = LearningProfile.model_validate(profile_data)
            else:
                # Create new profile with defaults
                profile = LearningProfile(
                    version=1,
                    targetLanguage=req.target_language or "en",
                    nativeLanguage=req.native_language or "en",
                    estimatedCefr="A2",
                    skillScores=[],
                    weakSubskills=[],
                    preferences=LearningPreferences(),
                    updatedAt=now_iso
                )

            # Apply patches
            if req.target_language is not None:
                profile.target_language = req.target_language
            if req.native_language is not None:
                profile.native_language = req.native_language
            if req.preferences is not None:
                profile.preferences = req.preferences

            profile.updated_at = now_iso

            # Save updated profile
            profile_json = profile.model_dump_json(by_alias=True)
            db.execute(
                """
                INSERT INTO learning_profiles (user_id, profile_json, version, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (ctx.user_id, profile_json, profile.version, now_iso)
            )

            logging.info(
                f"Patched learning profile for user {ctx.user_id}",
                extra={"user_id": ctx.user_id}
            )

            return GetLearningProfileResponse(profile=profile)

        except Exception as e:
            logging.error(f"Error patching learning profile: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.get("/v1/learning/recommendations", tags=["learning"])
    async def get_personalized_recommendations_endpoint(request: Request):
        """
        Get personalized learning recommendations based on user's diagnostic history.

        Analyzes user's progression, accuracy trends, and weak areas to provide:
        - Recommended starting level for next diagnostic session
        - Focus areas that need attention
        - Suggested study plan (review/advance/maintain)
        - Progression trend (improving/stable/declining)

        Returns default recommendations for new users with no history.
        """
        from app import diagnostic_session

        ctx = authenticate(request, db)

        try:
            # Get recommendations
            recommendations = diagnostic_session.get_personalized_recommendations(db, ctx.user_id)

            logging.info(
                "[RECOMMENDATIONS] Generated personalized recommendations",
                extra={
                    "user_id": ctx.user_id,
                    "recommended_level": recommendations.get("recommended_level"),
                    "study_plan": recommendations.get("study_plan"),
                    "trend": recommendations.get("trend"),
                    "has_focus_areas": len(recommendations.get("focus_areas", [])) > 0
                }
            )

            return recommendations

        except Exception as e:
            logging.error(f"Error getting recommendations: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    # ========================================================================
    # Learning Plan Generation
    # ========================================================================

    @router.post(
        "/v1/learning/plan/generate",
        response_model=GenerateLearningPlanResponse,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def generate_learning_plan_endpoint(req: GenerateLearningPlanRequest, request: Request):
        """
        Generate structured learning plan from diagnostic results.

        Uses diagnostic results (latest or specified session) to create
        a personalized learning plan with recommended lessons and focus areas.

        Also updates or creates user learning profile.

        **Workflow:**
        1. Resolve diagnostic results (from sessionId, latest session, or defaults)
        2. Generate focus areas from weak subskills
        3. Create 5-7 recommended lesson specs
        4. Update/create learning profile
        5. Return plan + profile + first lesson request

        **Client Usage:**
        After getting the plan, client can call /v1/lessons/generate
        with the provided firstLessonRequest payload to start learning.
        """
        from app.core.compat import normalize_language_code
        from app.services import learning_plan

        ctx = authenticate(request, db)

        try:
            # Normalize languages
            target_lang = normalize_language_code(req.target_language)
            native_lang = normalize_language_code(req.native_language)

            # Generate plan
            plan_id, profile, plan, first_lesson_req = learning_plan.generate_learning_plan(
                db=db,
                user_id=ctx.user_id,
                target_language=target_lang,
                native_language=native_lang,
                topic=req.topic,
                session_id=req.session_id,
                estimated_cefr=req.estimated_cefr,
                weak_subskills=req.weak_subskills,
                lesson_length=req.lesson_length,
                persona_id=req.persona_id
            )

            logging.info(
                f"Generated learning plan for user {ctx.user_id}",
                extra={
                    "user_id": ctx.user_id,
                    "plan_id": plan_id,
                    "cefr": profile.estimated_cefr,
                    "lesson_count": len(plan.recommended_lessons)
                }
            )

            return GenerateLearningPlanResponse(
                planId=plan_id,
                profile=profile,
                plan=plan,
                firstLessonRequest=first_lesson_req
            )

        except Exception as e:
            logging.error(f"Error generating learning plan: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    # ========================================================================
    # Bug Reports / Feedback
    # ========================================================================

    @router.post(
        "/v1/feedback/bug-reports",
        response_model=BugReportResponse,
        response_model_by_alias=True,
        tags=["feedback"],
    )
    async def submit_bug_report(req: BugReportRequest, request: Request):
        """
        Submit a bug report from the client.

        Stores structured bug reports with full context for analysis.
        Reports can include grading mismatches, UI bugs, content issues, etc.

        **Authentication:**
        - Requires valid API key / user context

        **Rate Limiting:**
        - Applied via standard rate limiting (if configured)

        **Payload:**
        - Stores full request JSON for AI-readable debugging
        - Includes context (session, item, task details)
        - Includes client metadata (app version, platform, etc.)
        """
        ctx = authenticate(request, db)
        start_time = time.perf_counter()

        try:
            # Generate unique report ID
            report_id = f"bug_{uuid.uuid4().hex[:16]}"
            received_at = _now_iso()

            # Normalize debug field for backward compatibility
            # Accept both 'captureAt' and 'capturedAt', store as canonical 'captureAt'
            if req.debug:
                debug_normalized = dict(req.debug)
                if "capturedAt" in debug_normalized and "captureAt" not in debug_normalized:
                    debug_normalized["captureAt"] = debug_normalized.pop("capturedAt")
                req.debug = debug_normalized

            # Serialize full payload as JSON for storage (with normalized fields)
            payload_json = req.model_dump_json(by_alias=True)

            # Store in database
            db.execute(
                """
                INSERT INTO bug_reports 
                (id, user_id, kind, severity, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (report_id, ctx.user_id, req.kind.value, req.severity.value, payload_json, received_at)
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.info(
                "[BUG_REPORT] Report received",
                extra={
                    "report_id": report_id,
                    "user_id": ctx.user_id,
                    "kind": req.kind.value,
                    "severity": req.severity.value,
                    "has_user_message": req.user_message is not None,
                    "context_keys": list(req.context.keys()) if req.context else [],
                    "client_keys": list(req.client.keys()) if req.client else [],
                    "duration_ms": duration_ms,
                    "status": "ok"
                }
            )

            return BugReportResponse(
                ok=True,
                reportId=report_id,
                receivedAt=received_at
            )

        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"Error submitting bug report: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    # ========================================================================
    # Performance Monitoring & Production Readiness Endpoints
    # ========================================================================

    @router.get("/v1/monitoring/performance", tags=["monitoring"])
    async def get_performance_metrics(
        request: Request,
        hours: int = 24,
        operation: Optional[str] = None
    ):
        """
        Get performance metrics snapshot.

        Query params:
        - hours: Time window in hours (default: 24)
        - operation: Filter by operation type (optional)
        """
        from app.performance_monitor import PerformanceMonitor

        require_admin_key(request)

        monitor = PerformanceMonitor(db)
        snapshot = monitor.get_snapshot(hours=hours, operation=operation)

        return {
            "period_start": snapshot.period_start,
            "period_end": snapshot.period_end,
            "metrics": {
                "total_operations": snapshot.total_operations,
                "successful": snapshot.successful_operations,
                "failed": snapshot.failed_operations,
                "success_rate_pct": (snapshot.successful_operations / snapshot.total_operations * 100) if snapshot.total_operations > 0 else 0
            },
            "performance": {
                "avg_duration_ms": round(snapshot.avg_duration_ms, 2),
                "p50_duration_ms": round(snapshot.p50_duration_ms, 2),
                "p95_duration_ms": round(snapshot.p95_duration_ms, 2),
                "p99_duration_ms": round(snapshot.p99_duration_ms, 2)
            },
            "tokens": {
                "total": snapshot.total_tokens,
                "avg_per_operation": round(snapshot.avg_tokens_per_operation, 2)
            },
            "operations_by_type": snapshot.operations_by_type
        }

    @router.get("/v1/monitoring/health", tags=["monitoring"])
    async def check_system_health(request: Request):
        """
        Check overall system health and detect degradation.
        """
        from app.performance_monitor import PerformanceMonitor

        require_admin_key(request)

        monitor = PerformanceMonitor(db)

        # Compare last 1 hour vs last 24 hours
        current_snapshot = monitor.get_snapshot(hours=1)
        baseline_snapshot = monitor.get_snapshot(hours=24)

        alerts = monitor.check_degradation(current_snapshot, baseline_snapshot)

        return {
            "status": "degraded" if alerts['has_alerts'] else "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_metrics": {
                "avg_duration_ms": round(current_snapshot.avg_duration_ms, 2),
                "avg_tokens": round(current_snapshot.avg_tokens_per_operation, 2),
                "error_rate_pct": (current_snapshot.failed_operations / current_snapshot.total_operations * 100) if current_snapshot.total_operations > 0 else 0
            },
            "baseline_metrics": {
                "avg_duration_ms": round(baseline_snapshot.avg_duration_ms, 2),
                "avg_tokens": round(baseline_snapshot.avg_tokens_per_operation, 2)
            },
            "alerts": alerts
        }

    @router.get("/v1/monitoring/slo", tags=["monitoring"])
    async def get_slo_status(request: Request):
        """
        Get current SLO (Service Level Objectives) compliance status.
        """
        from app.infrastructure.monitoring.slo_monitor import SLOMonitor

        require_admin_key(request)

        monitor = SLOMonitor(db)
        report = monitor.get_full_report()

        return {
            "timestamp": report.timestamp,
            "overall_compliance": report.overall_compliance,
            "summary": {
                "total_slos": report.slo_count,
                "compliant": report.compliant_count,
                "non_compliant": report.non_compliant_count
            },
            "slos": [
                {
                    "name": s.name,
                    "target": s.target,
                    "current": s.current,
                    "is_compliant": s.is_compliant,
                    "window": s.window,
                    "details": s.details
                }
                for s in report.statuses
            ]
        }

    @router.get("/v1/monitoring/slo/{slo_name}/history", tags=["monitoring"])
    async def get_slo_history(request: Request, slo_name: str, hours: int = 168):
        """
        Get historical SLO measurements for a specific SLO.

        Query params:
        - hours: Time window in hours (default: 168 = 7 days)
        """
        from app.infrastructure.monitoring.slo_monitor import SLOMonitor

        require_admin_key(request)

        monitor = SLOMonitor(db)
        history = monitor.get_slo_history(slo_name, hours)

        return {
            "slo_name": slo_name,
            "window_hours": hours,
            "measurement_count": len(history),
            "measurements": history
        }

    return router
