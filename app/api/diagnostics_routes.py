from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request

from app.core.auth import authenticate
from app.core.dto_transforms import transform_diagnostic_item_to_v1
from app.infrastructure.db.sqlite import DB
from app.models.api import (
    DiagnosticAttemptRequest,
    DiagnosticAttemptResponseV1,
    DiagnosticFinishRequest,
    DiagnosticFinishResponse,
    DiagnosticGenerateRequest,
    DiagnosticNextRequest,
    DiagnosticNextResponseV1,
    DiagnosticResponse,
    DiagnosticStartRequest,
    DiagnosticStartResponseV1,
)
from app.settings import Settings


def build_diagnostics_router(
    *,
    db: DB,
    settings: Settings,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/v1/diagnostics/generate",
        response_model=DiagnosticResponse,
        tags=["diagnostics"],
    )
    async def generate_diagnostic_items(req: DiagnosticGenerateRequest, request: Request):
        """
        Generate diagnostic test items based on blueprint.

        Returns structured diagnostic items following the diagnostic schema.
        Each item includes choices, answers, tags, and distractor reasons.
        """
        from app.services.diagnostic import engine as diagnostic_engine

        ctx = authenticate(request, db)
        start_time = time.perf_counter()
        trace_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")

        try:
            response = diagnostic_engine.generate_diagnostic_items(
                request=req,
                user_id=ctx.user_id,
                persona_id_override=req.persona_id,
                optimize_mode=settings.optimize_mode,
                trace_id=trace_id,
                session_id=None,
                job_id=None,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.info(
                "[DIAGNOSTIC] Items generated",
                extra={
                    "user_id": ctx.user_id,
                    "native_lang": req.native_lang,
                    "target_lang": req.target_lang,
                    "item_count": len(response.diagnostic_set.items),
                    "total_cost_usd": response.total_cost_usd,
                    "total_credits_charged": response.total_credits_charged,
                    "persona_id_requested": req.persona_id,
                    "persona_id_used": response.persona_id_used,
                    "fallback_reason": response.fallback_reason,
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            return response

        except ValueError as exc:
            error_msg = str(exc)
            logging.error(
                "Diagnostic generation failed",
                extra={
                    "user_id": ctx.user_id,
                    "error": error_msg,
                    "persona_id_requested": req.persona_id,
                },
            )
            raise HTTPException(status_code=502, detail=error_msg)
        except Exception as exc:
            logging.error(f"Unexpected error in diagnostic generation: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.get("/v1/diagnostics/specialized/tests", tags=["diagnostics"])
    async def list_specialized_tests(request: Request):
        """
        List all available specialized diagnostic tests.

        Returns available test types like business_english, medical_english, etc.
        """
        ctx = authenticate(request, db)
        _ = ctx

        from app import specialized_tests

        tests = specialized_tests.get_available_tests()
        test_info = {}

        for test_type in tests:
            info = specialized_tests.get_test_info(test_type)
            if info:
                test_info[test_type] = {
                    "title": info.get("title", test_type),
                    "description": info.get("description", ""),
                    "target_audience": info.get("target_audience", ""),
                    "item_count": len(info.get("blueprint", [])),
                }

        return {
            "available_tests": tests,
            "test_details": test_info,
            "domains": specialized_tests.list_domains(),
            "dialects": specialized_tests.list_dialects(),
        }

    @router.post(
        "/v1/diagnostics/specialized/{test_type}",
        response_model=DiagnosticResponse,
        tags=["diagnostics"],
    )
    async def generate_specialized_test(test_type: str, request: Request):
        """
        Generate a specialized diagnostic test for specific domain or dialect.

        Available test types:
        - business_english: Professional communication skills
        - medical_english: Healthcare terminology and communication
        - academic_english: University-level academic writing
        - technical_english: Engineering and IT terminology
        - british_vs_american: Dialect differences assessment
        """
        from app import specialized_tests
        from app.services.diagnostic import engine as diagnostic_engine

        ctx = authenticate(request, db)
        start_time = time.perf_counter()
        trace_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        logging.info(f"SPECIALIZED TEST ENDPOINT: {test_type}")

        try:
            logging.info(f"Creating specialized blueprint for: {test_type}")
            blueprint = specialized_tests.create_specialized_blueprint(test_type)
            logging.info(f"Blueprint created with {len(blueprint)} items")

            logging.info("Creating DiagnosticGenerateRequest")
            specialized_request = DiagnosticGenerateRequest(
                native_lang="Russian",
                target_lang="English",
                blueprint=blueprint,
            )
            logging.info("Request object created")

            logging.info("Calling diagnostic_engine.generate_diagnostic_items")
            response = diagnostic_engine.generate_diagnostic_items(
                request=specialized_request,
                user_id=ctx.user_id,
                persona_id_override=None,
                optimize_mode=True,
                trace_id=trace_id,
                session_id=None,
                job_id=None,
            )

            end_time = time.perf_counter()
            logging.info(f"Generated specialized test '{test_type}' in {end_time - start_time:.2f}s")

            return response

        except ValueError as exc:
            logging.error(f"Invalid specialized test request: {exc}")
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logging.error(f"Specialized test generation failed: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="specialized_test_generation_failed")

    @router.post(
        "/v1/learning/diagnostic/start",
        response_model=DiagnosticStartResponseV1,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def start_diagnostic_session(req: DiagnosticStartRequest, request: Request):
        """
        Start a new diagnostic placement test session.

        Creates session, generates 25 items from blueprint, stores them.
        Returns session ID and first item in Client V1 format.

        **Performance Note:** This endpoint generates 25 diagnostic items using LLM,
        which typically takes 30-45 seconds. The request will timeout at 45 seconds.
        Consider showing a loading indicator in the UI.

        **Client V1 Changes:**
        - nextItem uses itemId (not id), content.*, and metadata structure
        - Backward compatible with legacy field names for 1 week

        **Backward Compatibility (1 week):**
        - Accepts language names (e.g., "English") or codes (e.g., "en")
        - Accepts old level names (e.g., "beginner") or CEFR codes (e.g., "A1")
        """
        from app import diagnostic_session
        from app.core.compat import normalize_language_code, normalize_level_guess
        from app.core.rate_limit import check_rate_limits

        ctx = authenticate(request, db)
        _redis = getattr(getattr(request.app.state, "seed", None), "redis", None)
        if _redis is not None:
            await check_rate_limits(
                r=_redis,
                namespace=settings.redis_namespace,
                user_id=ctx.user_id,
                ip=request.client.host if request.client else "unknown",
                soft_rpm=10,
                hard_rpm=settings.hard_rpm_default,
                hard_rps=settings.hard_rps_default,
            )

        start_time = time.perf_counter()

        original_native = req.native_language
        original_target = req.target_language
        original_level = req.start_level_guess

        req.native_language = normalize_language_code(req.native_language)
        req.target_language = normalize_language_code(req.target_language)
        req.start_level_guess = normalize_level_guess(req.start_level_guess or "A2")

        logging.info(
            "[DIAGNOSTIC] start payload",
            extra={
                "native_language": req.native_language,
                "target_language": req.target_language,
                "start_level_guess": req.start_level_guess,
                "user_id": ctx.user_id,
                "normalized": (
                    original_native != req.native_language
                    or original_target != req.target_language
                    or original_level != req.start_level_guess
                ),
                "original_native": original_native if original_native != req.native_language else None,
                "original_target": original_target if original_target != req.target_language else None,
                "original_level": original_level if original_level != req.start_level_guess else None,
            },
        )

        try:
            session_id, items = diagnostic_session.create_diagnostic_session(
                db=db,
                user_id=ctx.user_id,
                request=req,
                persona_id=None,
                use_adaptive=req.use_adaptive,
                optimize_mode=settings.optimize_mode,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.info(
                "[DIAGNOSTIC] Session started",
                extra={
                    "session_id": session_id,
                    "user_id": ctx.user_id,
                    "native_lang": req.native_language,
                    "target_lang": req.target_language,
                    "items_count": len(items),
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            first_item_v1 = transform_diagnostic_item_to_v1(items[0])

            item_dict = first_item_v1.model_dump(by_alias=True)
            logging.info(
                "[DIAGNOSTIC] item serialize",
                extra={
                    "item_id": item_dict.get("itemId"),
                    "task_type": item_dict.get("taskType"),
                    "has_content": "content" in item_dict,
                    "has_metadata": "metadata" in item_dict,
                    "content_keys": list(item_dict.get("content", {}).keys()),
                    "metadata_keys": list(item_dict.get("metadata", {}).keys()),
                },
            )

            return DiagnosticStartResponseV1(
                sessionId=session_id,
                totalItems=len(items),
                nextItem=first_item_v1,
            )

        except ValueError as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            error_msg = str(exc)

            logging.error(
                "[DIAGNOSTIC] Session creation failed - validation error",
                extra={
                    "user_id": ctx.user_id,
                    "native_lang": req.native_language,
                    "target_lang": req.target_language,
                    "error": error_msg,
                    "duration_ms": duration_ms,
                    "error_type": "validation",
                },
            )
            raise HTTPException(status_code=502, detail=f"item_generation_failed: {error_msg}")

        except TimeoutError as exc:
            _ = exc
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.error(
                "[DIAGNOSTIC] Session creation failed - timeout",
                extra={
                    "user_id": ctx.user_id,
                    "native_lang": req.native_language,
                    "target_lang": req.target_language,
                    "duration_ms": duration_ms,
                    "error_type": "timeout",
                },
            )
            raise HTTPException(status_code=504, detail="item_generation_timeout")

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            import traceback

            logging.error(
                f"[DIAGNOSTIC] Session creation failed - unexpected error: {type(exc).__name__}",
                extra={
                    "user_id": ctx.user_id,
                    "native_lang": req.native_language,
                    "target_lang": req.target_language,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "duration_ms": duration_ms,
                    "traceback": traceback.format_exc(),
                },
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.post(
        "/v1/learning/diagnostic/attempt",
        response_model=DiagnosticAttemptResponseV1,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def submit_diagnostic_attempt(req: DiagnosticAttemptRequest, request: Request):
        """
        Submit an answer for a diagnostic item.

        Evaluates correctness, stores attempt, returns feedback.

        **Client V1 Changes:**
        - Returns 'correct' instead of 'isCorrect'
        - Includes optional feedback and attemptId fields
        """
        from app import diagnostic_session

        ctx = authenticate(request, db)
        start_time = time.perf_counter()

        logging.info(
            "[DIAGNOSTIC] /attempt RECEIVED DATA",
            extra={
                "session_id": req.session_id,
                "item_id": req.item_id,
                "user_answer_raw": req.user_answer_raw,
                "response_time_ms": req.response_time_ms,
                "user_id": ctx.user_id,
            },
        )

        logging.info(
            "[DIAGNOSTIC] /attempt request",
            extra={
                "session_id": req.session_id,
                "item_id": req.item_id,
                "user_id": ctx.user_id,
            },
        )

        try:
            session = diagnostic_session.get_session_info(db, req.session_id, ctx.user_id)
            if not session:
                any_session = db.fetchone(
                    "SELECT id, user_id, status FROM diagnostic_sessions WHERE id = ?",
                    (req.session_id,),
                )
                if any_session:
                    logging.warning(
                        "[DIAGNOSTIC] Session found but belongs to different user",
                        extra={
                            "requested_session_id": req.session_id,
                            "requesting_user_id": ctx.user_id,
                            "actual_session_owner": any_session["user_id"],
                        },
                    )
                else:
                    logging.warning(
                        "[DIAGNOSTIC] Session does not exist in database",
                        extra={
                            "requested_session_id": req.session_id,
                            "requesting_user_id": ctx.user_id,
                        },
                    )
                raise HTTPException(status_code=404, detail="session_not_found")

            if session["status"] != "running":
                raise HTTPException(status_code=400, detail="session_not_running")

            item = diagnostic_session.get_session_item(db, req.session_id, req.item_id)
            if not item:
                raise HTTPException(status_code=404, detail="item_not_found")

            is_correct, correct_answer = diagnostic_session.evaluate_answer(item, req.user_answer_raw)

            tags_json = item.tags.model_dump_json()
            diagnostic_session.store_attempt(
                db=db,
                session_id=req.session_id,
                item_id=req.item_id,
                user_answer=req.user_answer_raw,
                is_correct=is_correct,
                response_time_ms=req.response_time_ms,
                tags_json=tags_json,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.info(
                "[DIAGNOSTIC] Attempt submitted",
                extra={
                    "session_id": req.session_id,
                    "item_id": req.item_id,
                    "is_correct": is_correct,
                    "user_answer": req.user_answer_raw,
                    "correct_answer": correct_answer,
                    "response_time_ms": req.response_time_ms,
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            return DiagnosticAttemptResponseV1(
                ok=True,
                correct=is_correct,
                correctAnswer=correct_answer,
                feedback=None,
                attemptId=None,
            )

        except HTTPException:
            raise
        except Exception as exc:
            logging.error(f"Error recording diagnostic attempt: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.post(
        "/v1/learning/diagnostic/next",
        response_model=DiagnosticNextResponseV1,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def get_next_diagnostic_item(req: DiagnosticNextRequest, request: Request):
        """
        Get next unanswered item in diagnostic session.

        Returns next item or completion status if all items answered.

        **Client V1 Changes:**
        - nextItem uses itemId, content.*, and metadata structure
        """
        from app import diagnostic_session

        ctx = authenticate(request, db)
        start_time = time.perf_counter()

        logging.info(
            "[DIAGNOSTIC] /next request",
            extra={
                "session_id": req.session_id,
                "user_id": ctx.user_id,
            },
        )

        try:
            session = diagnostic_session.get_session_info(db, req.session_id, ctx.user_id)
            if not session:
                any_session = db.fetchone(
                    "SELECT id, user_id, status FROM diagnostic_sessions WHERE id = ?",
                    (req.session_id,),
                )
                if any_session:
                    logging.warning(
                        "[DIAGNOSTIC] Session found but belongs to different user",
                        extra={
                            "requested_session_id": req.session_id,
                            "requesting_user_id": ctx.user_id,
                            "actual_session_owner": any_session["user_id"],
                            "session_status": any_session["status"],
                        },
                    )
                else:
                    logging.warning(
                        "[DIAGNOSTIC] Session does not exist in database",
                        extra={
                            "requested_session_id": req.session_id,
                            "requesting_user_id": ctx.user_id,
                        },
                    )
                raise HTTPException(status_code=404, detail="session_not_found")

            result = diagnostic_session.get_next_unanswered_item(db, req.session_id)

            if result is None:
                logging.info(
                    "[DIAGNOSTIC] Session complete - all items answered",
                    extra={
                        "session_id": req.session_id,
                        "user_id": ctx.user_id,
                        "status": "ok",
                    },
                )
                return DiagnosticNextResponseV1(complete=True)

            item, index, total_items = result
            item_v1 = transform_diagnostic_item_to_v1(item)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.info(
                "[DIAGNOSTIC] Next item: sessionId={}, itemIndex={}/{}".format(
                    req.session_id, index, total_items
                ),
                extra={
                    "session_id": req.session_id,
                    "item_id": item.id,
                    "task_type": item.task_type,
                    "index": index,
                    "total_items": total_items,
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            return DiagnosticNextResponseV1(
                complete=False,
                item=item_v1,
                index=index,
                totalItems=total_items,
            )

        except HTTPException:
            raise
        except Exception as exc:
            logging.error(f"Error getting next diagnostic item: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    @router.post(
        "/v1/learning/diagnostic/finish",
        response_model=DiagnosticFinishResponse,
        response_model_by_alias=True,
        tags=["learning"],
    )
    async def finish_diagnostic_session(req: DiagnosticFinishRequest, request: Request):
        """
        Finish diagnostic session and get results.

        Calculates CEFR estimate, skill scores, weak areas.
        Marks session as finished.

        **Client V1 Changes:**
        - skillScores maintained as map (Dict[str, int]) for consistency
        - Added detailed logging of finish payload
        """
        from app import diagnostic_session

        ctx = authenticate(request, db)
        start_time = time.perf_counter()

        try:
            session = diagnostic_session.get_session_info(db, req.session_id, ctx.user_id)
            if not session:
                raise HTTPException(status_code=404, detail="session_not_found")

            results = diagnostic_session.finish_session(db, req.session_id)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logging.info(
                "[DIAGNOSTIC] finish payload",
                extra={
                    "session_id": req.session_id,
                    "user_id": ctx.user_id,
                    "estimated_cefr": results["estimated_cefr"],
                    "skill_scores": results["skill_scores"],
                    "weak_subskills_count": len(results["weak_subskills"]),
                    "attempts_count": results["attempts_count"],
                    "items_count": results["items_count"],
                    "accuracy": (
                        results["attempts_count"] / results["items_count"]
                        if results["items_count"] > 0
                        else 0
                    ),
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            logging.info(
                "[DIAGNOSTIC] Session finished: sessionId={}, cefr={}".format(
                    req.session_id, results["estimated_cefr"]
                ),
                extra={
                    "session_id": req.session_id,
                    "user_id": ctx.user_id,
                    "estimated_cefr": results["estimated_cefr"],
                    "attempts_count": results["attempts_count"],
                    "items_count": results["items_count"],
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )

            return DiagnosticFinishResponse(
                estimatedCefr=results["estimated_cefr"],
                skillScores=results["skill_scores"],
                weakSubskills=results["weak_subskills"],
                attemptsCount=results["attempts_count"],
                itemsCount=results["items_count"],
                totalCorrect=results["total_correct"],
                totalAttempts=results["total_attempts"],
                accuracy=results["accuracy"],
            )

        except HTTPException:
            raise
        except Exception as exc:
            logging.error(f"Error finishing diagnostic session: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail="internal_server_error")

    return router
