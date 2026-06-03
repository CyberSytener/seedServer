from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Callable

from fastapi import APIRouter, Header, HTTPException, Request

from app.core import persona_prompts
from app.core.auth import authenticate
from app.infrastructure.db.sqlite import (
    DB,
    delete_lesson,
    get_lesson_attempts,
    get_lesson_by_id,
    get_user_lessons,
)
from app.models.api import (
    CompleteNodeRequest,
    CompleteNodeResponse,
    GetLearningPathResponse,
    GradeResponse,
    Lesson,
    LessonAttemptInfo,
    LessonDeleteResponse,
    LessonGenerateRequest,
    LessonGetResponse,
    LessonListItem,
    LessonListResponse,
    LessonResponse,
    LessonSubmitRequest,
    NodeStatus,
    StartNodeRequest,
    StartNodeResponse,
)
from app.settings import Settings


LESSON_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")


def build_lessons_router(
    *,
    db: DB,
    settings: Settings,
    now_iso: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    @router.post("/v1/lessons/generate", response_model=LessonResponse)
    async def generate_lesson(req: LessonGenerateRequest, request: Request) -> LessonResponse:
        """
        Generate a new language learning lesson using Pipeline with Exercise Diversity.
        """
        import app.lesson_engine_pipeline as lesson_engine_pipeline
        from app.core.rate_limit import check_rate_limits

        ctx = authenticate(request, db)
        _redis = getattr(getattr(request.app.state, "seed", None), "redis", None)
        if _redis is not None:
            await check_rate_limits(
                r=_redis,
                namespace=settings.redis_namespace,
                user_id=ctx.user_id,
                ip=request.client.host if request.client else "unknown",
                soft_rpm=5,
                hard_rpm=settings.hard_rpm_default,
                hard_rps=settings.hard_rps_default,
            )

        start_time = time.perf_counter()
        lesson_id = f"lesson_{str(uuid.uuid4())[:12]}"
        trace_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")

        topic = req.topic
        if req.node_id and not topic:
            from app.services.path import learning as learning_path

            topic = learning_path.get_node_topic(db, ctx.user_id, req.node_id)

        try:
            pipeline_result = await lesson_engine_pipeline.generate_lesson_from_pipeline_async(
                target_lang=req.target_lang,
                native_lang=req.native_lang,
                cefr_level=req.level,
                topic=topic or "General",
                focus="grammar",
                mode=req.mode or "learning_path",
                node_id=req.node_id,
                unit_id=req.unit_id,
                lesson_length=req.lesson_length or 10,
                xp_reward=15,
                trace_id=trace_id,
                session_id=req.unit_id,
                job_id=None,
            )

            logging.info(
                f"Pipeline result: success={pipeline_result.get('success')}, error={pipeline_result.get('error')}"
            )

            if not pipeline_result.get("success"):
                error_msg = "Pipeline validation failed: " + str(
                    pipeline_result.get("error", "unknown")
                )
                raise ValueError(error_msg)

            lesson_content = pipeline_result.get("lesson_content", {})
            lesson = lesson_engine_pipeline.convert_pipeline_lesson_to_model(
                lesson_content=lesson_content,
                lesson_id=lesson_id,
                mode=req.mode,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            lesson_json = lesson.model_dump_json()
            db.execute(
                "INSERT INTO lessons(id, user_id, lesson_json, persona_id_used, node_id, unit_id, xp_reward, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    lesson.lesson_id,
                    ctx.user_id,
                    lesson_json,
                    "pipeline_orchestrator",
                    req.node_id,
                    req.unit_id,
                    15,
                    now_iso(),
                ),
            )

            logging.info(
                "Lesson generated (pipeline)",
                extra={
                    "lesson_id": lesson.lesson_id,
                    "user_id": ctx.user_id,
                    "target_lang": lesson.target_lang,
                    "level": lesson.level,
                    "task_count": len(lesson.tasks),
                    "exercise_diversity": "10 (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)",
                    "total_cost_usd": (pipeline_result.get("cost_summary") or {}).get(
                        "total_cost_usd", 0.0
                    ),
                    "total_credits_charged": (pipeline_result.get("cost_summary") or {}).get(
                        "total_credits_charged", 0
                    ),
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            cost_summary = pipeline_result.get("cost_summary") or {}
            return LessonResponse(
                lesson=lesson,
                persona_id_used="pipeline_orchestrator",
                fallback_reason=None,
                node_id=req.node_id,
                unit_id=req.unit_id,
                xp_reward=15,
                total_cost_usd=float(cost_summary.get("total_cost_usd") or 0.0),
                total_credits_charged=int(cost_summary.get("total_credits_charged") or 0),
                cost_breakdown=list(cost_summary.get("cost_breakdown") or []),
                cost_totals_by_session=dict(cost_summary.get("totals_by_session") or {}),
                cost_totals_by_job=dict(cost_summary.get("totals_by_job") or {}),
            )

        except ValueError as exc:
            error_msg = str(exc)
            logging.error(
                "Pipeline lesson generation failed",
                extra={
                    "user_id": ctx.user_id,
                    "error": error_msg,
                    "target_lang": req.target_lang,
                    "level": req.level,
                },
            )
            raise HTTPException(status_code=502, detail=error_msg)
        except Exception as exc:
            logging.error("Unexpected error in pipeline lesson generation", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.get("/v1/lessons/health", tags=["debug"])
    async def lessons_health():
        return {
            "status": "ok",
            "lesson_generation": "pipeline_orchestrator",
            "exercise_diversity": "10 (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)",
        }

    @router.get(
        "/v1/user/learning-path",
        response_model=GetLearningPathResponse,
        tags=["learning-path"],
    )
    async def get_learning_path(
        request: Request,
        target_lang: str = "Russian",
        native_lang: str = "English",
    ) -> GetLearningPathResponse:
        from app.services.path import learning as learning_path

        ctx = authenticate(request, db)
        user_path = learning_path.get_or_create_user_path(
            db=db,
            user_id=ctx.user_id,
            target_lang=target_lang,
            native_lang=native_lang,
        )
        return GetLearningPathResponse(path=user_path)

    @router.post(
        "/v1/user/start-node",
        response_model=StartNodeResponse,
        tags=["learning-path"],
    )
    async def start_node(req: StartNodeRequest, request: Request) -> StartNodeResponse:
        from app.services.path import learning as learning_path

        ctx = authenticate(request, db)
        learning_path.update_node_status(
            db=db,
            user_id=ctx.user_id,
            node_id=req.node_id,
            status=NodeStatus.in_progress,
        )
        return StartNodeResponse(node_id=req.node_id, status=NodeStatus.in_progress)

    @router.post(
        "/v1/user/complete-node",
        response_model=CompleteNodeResponse,
        tags=["learning-path"],
    )
    async def complete_node_endpoint(
        req: CompleteNodeRequest,
        request: Request,
    ) -> CompleteNodeResponse:
        from app.services.path import learning as learning_path

        ctx = authenticate(request, db)
        return learning_path.complete_node(
            db=db,
            user_id=ctx.user_id,
            node_id=req.node_id,
            unit_id=req.unit_id,
            score=req.score,
        )

    @router.post("/v1/lessons/submit", response_model=GradeResponse)
    async def submit_lesson_answer(req: LessonSubmitRequest, request: Request) -> GradeResponse:
        import app.lesson_engine as lesson_engine

        ctx = authenticate(request, db)
        lesson_row = db.fetchone("SELECT * FROM lessons WHERE id=?", (req.lesson_id,))
        if not lesson_row:
            raise HTTPException(status_code=404, detail="lesson_not_found")
        if lesson_row["user_id"] != ctx.user_id:
            raise HTTPException(status_code=403, detail="forbidden")

        lesson_data = json.loads(lesson_row["lesson_json"])
        lesson = Lesson.model_validate(lesson_data)
        task = next((t for t in lesson.tasks if t.id == req.task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail="task_not_found")

        persona_result = persona_prompts.get_persona_prompt(req.persona_id)
        persona_id_used = persona_result.persona_id_used
        fallback_reason = persona_result.fallback_reason
        persona_prompt = persona_result.prompt_text

        start_time = time.perf_counter()
        try:
            grade = lesson_engine.grade_submission(
                task=task,
                user_answer=req.user_answer,
                persona_prompt=persona_prompt,
                provider=settings.default_provider_fast or "gemini",
                model=settings.gemini_model_fast or "gemini-2.0-flash-exp",
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            db.execute(
                "INSERT INTO lesson_attempts(lesson_id, task_id, user_answer, correct, score, created_at) VALUES(?,?,?,?,?,?)",
                (
                    req.lesson_id,
                    req.task_id,
                    req.user_answer,
                    int(grade.correct),
                    grade.score,
                    now_iso(),
                ),
            )

            attempts_rows = db.fetchall(
                "SELECT task_id, correct, score FROM lesson_attempts WHERE lesson_id=? ORDER BY created_at",
                (req.lesson_id,),
            )
            completed_task_ids = {row["task_id"] for row in attempts_rows}
            all_task_ids = {t.id for t in lesson.tasks}

            summary = None
            if completed_task_ids == all_task_ids:
                attempts = [(row["task_id"], bool(row["correct"]), row["score"]) for row in attempts_rows]
                summary = lesson_engine.generate_lesson_summary(
                    lesson=lesson,
                    attempts=attempts,
                    persona_prompt=persona_prompt,
                    provider=settings.default_provider_fast or "gemini",
                    model=settings.gemini_model_fast or "gemini-2.0-flash-exp",
                )

            logging.info(
                "Task graded",
                extra={
                    "lesson_id": req.lesson_id,
                    "task_id": req.task_id,
                    "user_id": ctx.user_id,
                    "correct": grade.correct,
                    "score": grade.score,
                    "completed": summary is not None,
                    "persona_id_requested": req.persona_id,
                    "persona_id_used": persona_id_used,
                    "fallback_reason": fallback_reason,
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            return GradeResponse(
                grade=grade,
                summary=summary,
                persona_id_used=persona_id_used,
                fallback_reason=fallback_reason,
            )
        except ValueError as exc:
            error_msg = str(exc)
            logging.error(
                "Grading failed",
                extra={
                    "lesson_id": req.lesson_id,
                    "task_id": req.task_id,
                    "user_id": ctx.user_id,
                    "error": error_msg,
                    "persona_id_requested": req.persona_id,
                    "persona_id_used": persona_id_used,
                },
            )
            raise HTTPException(status_code=502, detail=error_msg)
        except Exception as exc:
            logging.error(f"Unexpected error in grading: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.get("/v1/lessons", response_model=LessonListResponse, tags=["lessons"])
    async def list_lessons(request: Request, authorization: str = Header(None)):
        ctx = authenticate(request, db)
        start_time = time.perf_counter()
        trace_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        _ = trace_id  # keep compatibility with previous tracing extraction

        try:
            rows = get_user_lessons(db, ctx.user_id)
            lessons = []
            for row in rows:
                lesson_data = json.loads(row["lesson_json"])
                lesson = Lesson.model_validate(lesson_data)
                lessons.append(
                    LessonListItem(
                        lesson_id=lesson.lesson_id,
                        title=lesson.title or "Untitled Lesson",
                        native_lang=lesson.native_lang,
                        target_lang=lesson.target_lang,
                        level=lesson.level,
                        mode=lesson.mode,
                        created_at=row["created_at"],
                        persona_id_used=row["persona_id_used"],
                        tasks_count=len(lesson.tasks),
                        completed_count=row["completed_count"],
                    )
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logging.info(
                "Lessons listed",
                extra={
                    "user_id": ctx.user_id,
                    "lessons_count": len(lessons),
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )
            return LessonListResponse(lessons=lessons, total=len(lessons))
        except Exception as exc:
            logging.error(f"Error listing lessons: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.get("/v1/lessons/{lesson_id}", response_model=LessonGetResponse, tags=["lessons"])
    async def get_lesson(lesson_id: str, request: Request, authorization: str = Header(None)):
        if not LESSON_ID_PATTERN.match(lesson_id):
            raise HTTPException(status_code=400, detail="invalid_lesson_id")

        ctx = authenticate(request, db)
        start_time = time.perf_counter()
        try:
            lesson_row = get_lesson_by_id(db, lesson_id, ctx.user_id)
            if not lesson_row:
                raise HTTPException(status_code=404, detail="lesson_not_found")

            lesson_data = json.loads(lesson_row["lesson_json"])
            lesson = Lesson.model_validate(lesson_data)

            attempts_rows = get_lesson_attempts(db, lesson_id)
            attempts = [
                LessonAttemptInfo(
                    task_id=row["task_id"],
                    user_answer=row["user_answer"],
                    correct=bool(row["correct"]),
                    score=int(row["score"]),
                    created_at=row["created_at"],
                )
                for row in attempts_rows
            ]
            completed_task_ids = {row["task_id"] for row in attempts_rows if row["correct"]}
            total_score = sum(row["score"] for row in attempts_rows)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logging.info(
                "Lesson fetched",
                extra={
                    "user_id": ctx.user_id,
                    "lesson_id": lesson_id,
                    "persona_id_used": lesson_row["persona_id_used"],
                    "attempts_count": len(attempts),
                    "completed_count": len(completed_task_ids),
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            return LessonGetResponse(
                lesson=lesson,
                attempts=attempts,
                total_attempts=len(attempts),
                completed_count=len(completed_task_ids),
                total_score=total_score,
                persona_id_used=lesson_row["persona_id_used"],
            )
        except HTTPException:
            raise
        except Exception as exc:
            logging.error(f"Error fetching lesson: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.delete("/v1/lessons/{lesson_id}", response_model=LessonDeleteResponse, tags=["lessons"])
    async def delete_lesson_endpoint(
        lesson_id: str,
        request: Request,
        authorization: str = Header(None),
    ):
        if not LESSON_ID_PATTERN.match(lesson_id):
            raise HTTPException(status_code=400, detail="invalid_lesson_id")

        ctx = authenticate(request, db)
        start_time = time.perf_counter()
        try:
            lesson_row = get_lesson_by_id(db, lesson_id, ctx.user_id)
            if not lesson_row:
                raise HTTPException(status_code=404, detail="lesson_not_found")

            persona_id_used = lesson_row.get("persona_id_used")
            deleted = delete_lesson(db, lesson_id, ctx.user_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="lesson_not_found")

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logging.info(
                "Lesson deleted",
                extra={
                    "user_id": ctx.user_id,
                    "lesson_id": lesson_id,
                    "persona_id_used": persona_id_used,
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )
            return LessonDeleteResponse(deleted=True, lesson_id=lesson_id)
        except HTTPException:
            raise
        except Exception as exc:
            logging.error(f"Error deleting lesson: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    return router
