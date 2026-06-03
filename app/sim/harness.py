from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import sys
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.realtime.sagas.artifact_store import ArtifactStore
from app.infrastructure.redis.worker import process_job
from app.models.api import (
    DiagnosticAnswer,
    DiagnosticContext,
    DiagnosticItem,
    DiagnosticTags,
    GradeResult,
    LessonSummary,
)
from app.sim.contracts import AssertionRecord, ScenarioResult, SimulationReport, utcnow_iso
from app.sim.fake_redis import InMemoryAsyncRedis
from app.sim.llm_stub import create_pipeline_adapter


def _set_sim_env(db_path: Path) -> None:
    os.environ["SEED_DB_PATH"] = str(db_path)
    os.environ["SEED_ADMIN_KEY"] = ""
    os.environ["SEED_API_KEY_PEPPER"] = "pepper"
    os.environ["SEED_DEFAULT_PROVIDER_FAST"] = "stub"
    os.environ["SEED_DEFAULT_PROVIDER_BATCH"] = "stub"
    os.environ["SEED_ENABLE_LEGACY_X_USER_ID"] = "0"
    os.environ["SEED_METRICS_ENABLED"] = "1"
    os.environ["SEED_FAST_TIMEOUT_SEC"] = "0"
    os.environ["SEED_EMBEDDED_WORKERS"] = "0"
    os.environ["SEED_ENABLE_OPENAI"] = "0"
    os.environ["SEED_ENABLE_GEMINI"] = "0"
    os.environ["SEED_ENABLE_STUB"] = "1"


class _RuntimeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute_action(self, action: str, input_text: str, options: Dict[str, Any], mode: str, persona_id: str | None = None):
        from app.core.llm.router import ActionResult

        self.calls += 1
        normalized = " ".join(str(input_text or "").split())
        return ActionResult(
            provider="stub",
            model="sim-stub",
            text=normalized or "simulated response",
            tokens_in=max(1, len(str(input_text or "").split())),
            tokens_out=6,
            cost_usd=0.0,
            persona_id_used=str(persona_id or "classic_tutor"),
        )


class _FakeSagaOrchestrator:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.async_mode = False
        self.db = None

    async def init_async(self) -> None:
        return None

    async def close_async(self) -> None:
        return None

    async def start_saga(self, *, action_id: str, saga_type: str, payload: Dict[str, Any], user_id: str):
        self.calls.append(
            {
                "action_id": action_id,
                "saga_type": saga_type,
                "payload": payload,
                "user_id": user_id,
            }
        )
        return f"sim-saga-{len(self.calls)}"


def _build_diagnostic_item(item_id: str, prompt: str, answer: str) -> DiagnosticItem:
    return DiagnosticItem(
        id=item_id,
        taskType="mcq",
        prompt=prompt,
        context=DiagnosticContext(sentence="I ___ coffee."),
        choices=["drink", "drinks", answer, "drank"],
        answer=DiagnosticAnswer(accepted=[answer]),
        tags=DiagnosticTags(
            skill="grammar",
            subskill="verb_form",
            topic="present_simple",
            difficulty=1.0,
            taskType="mcq",
            cefrBand="A1",
            languagePair="en->en",
        ),
    )


def _stub_create_diagnostic_session(*, db, user_id: str, request, persona_id=None, use_adaptive=False, optimize_mode=False):
    session_id = f"diag_{uuid.uuid4().hex[:12]}"
    db.execute(
        """
        INSERT INTO diagnostic_sessions(id,user_id,native_lang,target_lang,start_level_guess,status,seed,created_at)
        VALUES(?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            session_id,
            user_id,
            request.native_language,
            request.target_language,
            request.start_level_guess or "A2",
            "running",
            42,
        ),
    )

    items = [
        _build_diagnostic_item("diag_item_1", "Choose correct form: I ___ coffee.", "drink"),
        _build_diagnostic_item("diag_item_2", "Choose correct form: She ___ coffee.", "drinks"),
    ]

    for index, item in enumerate(items):
        item_json = item.model_dump_json(by_alias=True)
        tags_json = item.tags.model_dump_json(by_alias=True)
        item_hash = hashlib.sha256(item_json.encode("utf-8")).hexdigest()[:16]
        db.execute(
            """
            INSERT INTO diagnostic_session_items(session_id,item_id,item_json,order_index,tags_json,item_hash)
            VALUES(?,?,?,?,?,?)
            """,
            (session_id, item.id, item_json, index, tags_json, item_hash),
        )

    return session_id, items


async def _stub_generate_lesson_from_pipeline_async(**kwargs: Any) -> Dict[str, Any]:
    return {
        "success": True,
        "error": None,
        "validation": {"recommendation": "APPROVE", "score": 100},
        "lesson_content": {
            "targetLang": kwargs.get("target_lang") or "Spanish",
            "nativeLang": kwargs.get("native_lang") or "English",
            "level": kwargs.get("cefr_level") or "A1",
            "topic": kwargs.get("topic") or "Basics",
            "title": "Simulation Lesson",
            "exercises": [
                {
                    "id": "task_1",
                    "type": "mcq",
                    "prompt": "Select the correct article",
                    "question": "___ casa",
                    "choices": ["el", "la", "los", "las"],
                    "correctChoiceIndex": 1,
                    "skill": "articles",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "la", "correctChoiceIndex": 1, "tip": "Use feminine singular."},
                },
                {
                    "id": "task_2",
                    "type": "translation",
                    "prompt": "Translate to Spanish",
                    "sourceText": "Good morning",
                    "skill": "greetings",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "Buenos días", "acceptedVariants": ["Buen día"], "tip": "Common greeting."},
                },
                {
                    "id": "task_3",
                    "type": "word_bank",
                    "prompt": "Build a sentence",
                    "tokens": ["yo", "soy", "estudiante"],
                    "correctSentence": "yo soy estudiante",
                    "englishSentence": "I am a student",
                    "skill": "word_order",
                    "difficulty": 1,
                    "grading": {"correctAnswer": "yo soy estudiante", "tip": "Subject + verb + noun."},
                },
            ],
        },
    }


def _stub_grade_submission(*, task, user_answer: str, **kwargs: Any) -> GradeResult:
    expected = str(task.grading.correct_answer or "").strip().lower()
    actual = str(user_answer or "").strip().lower()
    correct = bool(expected and actual == expected)
    return GradeResult(
        taskId=task.id,
        correct=correct,
        score=1.0 if correct else 0.0,
        feedback="Correct" if correct else "Try again",
        correctAnswer=task.grading.correct_answer,
    )


def _stub_lesson_summary(*, lesson, attempts, **kwargs: Any) -> LessonSummary:
    total = len(lesson.tasks)
    correct_count = sum(1 for _task_id, is_correct, _score in attempts if is_correct)
    percentage = (correct_count / total * 100.0) if total else 0.0
    return LessonSummary(
        lessonId=lesson.lesson_id,
        totalTasks=total,
        correctCount=correct_count,
        scorePercentage=percentage,
        completed=True,
        encouragement="Keep going",
    )


def _record(assertions: List[AssertionRecord], key: str, passed: bool, message: str, *, expected: Any = None, actual: Any = None) -> None:
    assertions.append(
        AssertionRecord(
            key=key,
            passed=passed,
            message=message,
            expected=expected,
            actual=actual,
        )
    )


def _run_s1(client: TestClient, app, token: str) -> ScenarioResult:
    started = time.perf_counter()
    assertions: List[AssertionRecord] = []
    artifacts: Dict[str, Any] = {}
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "sim-action-idem-1",
            "X-Correlation-ID": "corr-sim-1",
        }
        payload = {
            "action": "ask",
            "text": "hello from simulation",
            "options": {"provider": "stub", "max_output_tokens": 32},
        }

        first = client.post("/v1/actions", headers=headers, json=payload)
        second = client.post("/v1/actions", headers=headers, json=payload)
        _record(assertions, "actions.status", first.status_code == 200, "first action accepted", expected=200, actual=first.status_code)
        _record(assertions, "actions.idempotent", second.status_code == 200, "second action accepted", expected=200, actual=second.status_code)

        first_job_id = first.json().get("job_id") if first.status_code == 200 else None
        second_job_id = second.json().get("job_id") if second.status_code == 200 else None
        _record(
            assertions,
            "actions.idempotent.same_job",
            bool(first_job_id and second_job_id and first_job_id == second_job_id),
            "idempotent replay returned same job id",
            expected=first_job_id,
            actual=second_job_id,
        )

        if not first_job_id:
            raise RuntimeError("missing_job_id")

        before = client.get(f"/v1/jobs/{first_job_id}", headers={"Authorization": f"Bearer {token}"})
        _record(assertions, "jobs.poll.before", before.status_code == 200, "job is retrievable before worker execution")

        executor = _RuntimeExecutor()
        asyncio.run(process_job(db=app.state.seed.db, broker=app.state.seed.broker, job_id=first_job_id, executor=executor, worker_name="sim-worker"))
        asyncio.run(process_job(db=app.state.seed.db, broker=app.state.seed.broker, job_id=first_job_id, executor=executor, worker_name="sim-worker"))

        after = client.get(f"/v1/jobs/{first_job_id}", headers={"Authorization": f"Bearer {token}"})
        row = app.state.seed.db.fetchone(
            "SELECT status,tokens_in_actual,tokens_out_actual,result_text,options_json FROM jobs WHERE id=?",
            (first_job_id,),
        )
        events = app.state.seed.db.fetchall(
            "SELECT event,data_json FROM job_events WHERE job_id=? ORDER BY id ASC",
            (first_job_id,),
        )
        metrics = client.get("/metrics")

        _record(assertions, "jobs.poll.after", after.status_code == 200, "job is retrievable after worker execution")
        _record(assertions, "jobs.done", row is not None and row["status"] == "done", "job reached done state", expected="done", actual=None if row is None else row["status"])
        _record(assertions, "worker.single_claim", executor.calls == 1, "worker claim executes exactly once", expected=1, actual=executor.calls)
        _record(
            assertions,
            "jobs.persistence.output",
            bool(row and row["result_text"]),
            "result persisted in jobs table",
        )
        _record(
            assertions,
            "jobs.persistence.tokens",
            bool(row and row["tokens_in_actual"] is not None and row["tokens_out_actual"] is not None),
            "token usage persisted",
        )

        options = json.loads(row["options_json"] or "{}") if row else {}
        done_event = next((entry for entry in events if entry["event"] == "done"), None)
        done_payload = json.loads(done_event["data_json"] or "{}") if done_event else {}
        _record(assertions, "correlation.job.options", options.get("correlation_id") == "corr-sim-1", "correlation_id stored in job options")
        _record(assertions, "correlation.job.events", done_payload.get("correlation_id") == "corr-sim-1", "correlation_id propagated to job events")
        _record(assertions, "metrics.exposed", metrics.status_code == 200 and "jobs_created" in metrics.text, "prometheus metrics exposed and include jobs_created")

        artifacts["job_id"] = first_job_id
        artifacts["events"] = [
            {"event": entry["event"], "data": json.loads(entry["data_json"] or "{}")}
            for entry in events
        ]

        passed = all(item.passed for item in assertions)
        return ScenarioResult(
            scenario_id="S1",
            title="Chat action path",
            passed=passed,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
        )
    except Exception as error:
        return ScenarioResult(
            scenario_id="S1",
            title="Chat action path",
            passed=False,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
            error=str(error),
        )


def _run_s2(client: TestClient, app, token: str) -> ScenarioResult:
    started = time.perf_counter()
    assertions: List[AssertionRecord] = []
    artifacts: Dict[str, Any] = {}
    try:
        start_resp = client.post(
            "/v1/learning/diagnostic/start",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "nativeLanguage": "English",
                "targetLanguage": "Spanish",
                "startLevelGuess": "A1",
                "useAdaptive": False,
            },
        )
        _record(assertions, "diagnostic.start", start_resp.status_code == 200, "diagnostic session started", expected=200, actual=start_resp.status_code)
        payload = start_resp.json()
        session_id = payload.get("sessionId")
        first_item = payload.get("nextItem") or {}

        attempt_resp = client.post(
            "/v1/learning/diagnostic/attempt",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "sessionId": session_id,
                "itemId": first_item.get("itemId"),
                "userAnswerRaw": "drink",
                "responseTimeMs": 500,
            },
        )
        _record(assertions, "diagnostic.attempt", attempt_resp.status_code == 200, "first attempt accepted")

        other_user = client.post(
            "/v1/users",
            json={"user_id": "sim_user_other", "email": "sim_user_other@seed.local", "meta": {}},
        )
        other_token = other_user.json().get("api_key")
        ownership_resp = client.post(
            "/v1/learning/diagnostic/attempt",
            headers={"Authorization": f"Bearer {other_token}"},
            json={
                "sessionId": session_id,
                "itemId": first_item.get("itemId"),
                "userAnswerRaw": "drink",
                "responseTimeMs": 100,
            },
        )
        _record(assertions, "diagnostic.ownership", ownership_resp.status_code == 404, "ownership checks block another user", expected=404, actual=ownership_resp.status_code)

        next_resp = client.post(
            "/v1/learning/diagnostic/next",
            headers={"Authorization": f"Bearer {token}"},
            json={"sessionId": session_id},
        )
        second_item = next_resp.json().get("item") or {}
        _record(assertions, "diagnostic.next", next_resp.status_code == 200 and not next_resp.json().get("complete"), "next item returned")

        second_attempt = client.post(
            "/v1/learning/diagnostic/attempt",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "sessionId": session_id,
                "itemId": second_item.get("itemId"),
                "userAnswerRaw": "drinks",
                "responseTimeMs": 450,
            },
        )
        _record(assertions, "diagnostic.second_attempt", second_attempt.status_code == 200, "second attempt accepted")

        complete_resp = client.post(
            "/v1/learning/diagnostic/next",
            headers={"Authorization": f"Bearer {token}"},
            json={"sessionId": session_id},
        )
        _record(assertions, "diagnostic.complete", complete_resp.status_code == 200 and bool(complete_resp.json().get("complete")), "session reports completion")

        finish_resp = client.post(
            "/v1/learning/diagnostic/finish",
            headers={"Authorization": f"Bearer {token}"},
            json={"sessionId": session_id},
        )
        finish_payload = finish_resp.json() if finish_resp.status_code == 200 else {}
        _record(assertions, "diagnostic.finish", finish_resp.status_code == 200, "finish endpoint succeeded")
        _record(
            assertions,
            "diagnostic.dto.shape",
            all(key in finish_payload for key in ("estimatedCefr", "skillScores", "weakSubskills", "attemptsCount", "itemsCount")),
            "finish response matches desktop DTO shape",
        )

        artifacts["session_id"] = session_id
        artifacts["finish"] = finish_payload
        passed = all(item.passed for item in assertions)
        return ScenarioResult(
            scenario_id="S2",
            title="Learning diagnostic flow",
            passed=passed,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
        )
    except Exception as error:
        return ScenarioResult(
            scenario_id="S2",
            title="Learning diagnostic flow",
            passed=False,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
            error=str(error),
        )


def _run_s3(client: TestClient, app, token: str) -> ScenarioResult:
    started = time.perf_counter()
    assertions: List[AssertionRecord] = []
    artifacts: Dict[str, Any] = {}
    try:
        generate_resp = client.post(
            "/v1/lessons/generate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "mode": "vocabulary",
                "targetLang": "Spanish",
                "nativeLang": "English",
                "level": "A1",
                "topic": "Greetings",
                "lessonLength": 3,
            },
        )
        _record(assertions, "lessons.generate", generate_resp.status_code == 200, "lesson generated", expected=200, actual=generate_resp.status_code)

        payload = generate_resp.json() if generate_resp.status_code == 200 else {}
        lesson = payload.get("lesson") or {}
        tasks = lesson.get("tasks") or []
        _record(assertions, "lessons.shape", bool(tasks), "lesson contains tasks")

        first_task = tasks[0] if tasks else {}
        submit_resp = client.post(
            "/v1/lessons/submit",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "lessonId": lesson.get("lessonId"),
                "taskId": first_task.get("id"),
                "userAnswer": "la",
            },
        )
        submit_payload = submit_resp.json() if submit_resp.status_code == 200 else {}
        _record(assertions, "lessons.submit", submit_resp.status_code == 200, "lesson answer submitted")
        _record(assertions, "lessons.submit.shape", "grade" in submit_payload and isinstance(submit_payload.get("grade"), dict), "grade response shape valid")

        row = app.state.seed.db.fetchone(
            "SELECT COUNT(*) as cnt FROM lesson_attempts WHERE lesson_id=?",
            (lesson.get("lessonId"),),
        )
        _record(assertions, "lessons.persistence", bool(row and int(row["cnt"] or 0) >= 1), "lesson attempts persisted", expected=">=1", actual=None if row is None else row["cnt"])

        artifacts["lesson_id"] = lesson.get("lessonId")
        artifacts["grade"] = submit_payload.get("grade")

        passed = all(item.passed for item in assertions)
        return ScenarioResult(
            scenario_id="S3",
            title="Lessons generation and submit",
            passed=passed,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
        )
    except Exception as error:
        return ScenarioResult(
            scenario_id="S3",
            title="Lessons generation and submit",
            passed=False,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
            error=str(error),
        )


def _run_s4(
    client: TestClient,
    app,
    token: str,
    report_dir: Path,
    llm_mode: str,
    *,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> ScenarioResult:
    started = time.perf_counter()
    assertions: List[AssertionRecord] = []
    artifacts: Dict[str, Any] = {}
    try:
        mode_resp = client.post(
            "/v1/modes/general_assistant/run",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "control": {
                    "mode": "fast",
                    "requested_capabilities": ["llm.generate"],
                    "idempotency_key": "sim-mode-1",
                },
                "data": {"user_request": "Summarize simulation"},
            },
        )
        _record(assertions, "modes.run", mode_resp.status_code == 200, "mode run accepted", expected=200, actual=mode_resp.status_code)

        orchestrator = app.state.saga_orchestrator
        call = orchestrator.calls[-1] if orchestrator.calls else {}
        payload = call.get("payload") if isinstance(call.get("payload"), dict) else {}
        _record(assertions, "modes.contract.pipeline", call.get("saga_type") == "llm_pipeline", "mode route starts llm_pipeline saga")
        _record(
            assertions,
            "modes.contract.payload",
            all(field in payload for field in ("task_type", "user_request", "module", "control")),
            "mode payload includes expected contract fields",
        )

        artifact_store = ArtifactStore(base_dir=str(report_dir / "mode_artifacts"))
        saga_id = str(mode_resp.json().get("saga_id") or "sim")
        payload_artifact = artifact_store.store(
            saga_id=saga_id,
            step="run",
            kind="mode_payload",
            payload=payload,
        )
        _record(assertions, "modes.artifact.ref", bool(payload_artifact.get("uri") and payload_artifact.get("sha256")), "mode payload stored as artifact ref")

        stage_refs: Dict[str, Dict[str, Any]] = {}
        pipeline_contract: Dict[str, Any] = {}

        async def _build_stage_refs() -> None:
            pipeline_adapter = create_pipeline_adapter(
                llm_mode=llm_mode,
                provider=llm_provider,
                model=llm_model,
            )
            base_inputs = {
                "user_request": payload.get("user_request"),
                "module": payload.get("module"),
                "control": payload.get("control"),
            }
            stage_steps = {
                "candidate": "candidate",
                "validator": "validator",
                "final": "final",
            }

            for stage, step_name in stage_steps.items():
                stage_result = await pipeline_adapter.run_step(
                    {
                        "step": step_name,
                        "task_type": str(payload.get("task_type") or "general"),
                        "mode": str((payload.get("control") or {}).get("mode") or "fast"),
                        "inputs": base_inputs,
                    }
                )
                stage_artifact = artifact_store.store(
                    saga_id=saga_id,
                    step=stage,
                    kind="llm_stage",
                    payload=stage_result,
                )
                model_meta = stage_result.get("model") if isinstance(stage_result.get("model"), dict) else {}
                stage_refs[stage] = {
                    "provider": model_meta.get("provider"),
                    "model": model_meta.get("model"),
                    "usage": stage_result.get("usage") if isinstance(stage_result.get("usage"), dict) else {},
                    "cost": stage_result.get("cost") if isinstance(stage_result.get("cost"), dict) else {},
                    "artifact_ref": {
                        "uri": stage_artifact.get("uri"),
                        "sha256": stage_artifact.get("sha256"),
                    },
                }

        asyncio.run(_build_stage_refs())

        async def _probe_pipeline_contract() -> None:
            from app.core.realtime.sagas.flows import LLMPipelineFlow
            from app.core.realtime.sagas.orchestrator import SagaOrchestrator

            probe_orchestrator = SagaOrchestrator(
                db_connection_string="postgresql://localhost/seed_server",
                adapter_registry={},
                async_mode=True,
            )
            probe_orchestrator._update_saga_state = AsyncMock()

            flow = LLMPipelineFlow(probe_orchestrator)
            probe_payload = {
                "user_request": payload.get("user_request"),
                "task_type": str(payload.get("task_type") or "general"),
                "mode": str((payload.get("control") or {}).get("mode") or payload.get("mode") or "fast"),
                "required_fields": payload.get("required_fields") if isinstance(payload.get("required_fields"), list) else [],
                "output_schema": payload.get("output_schema") if isinstance(payload.get("output_schema"), dict) else {},
                "format_hint": str(payload.get("format_hint") or "json_object"),
                "artifact_store_enabled": True,
            }
            run_result = await flow.run(f"{saga_id}-probe", probe_payload, [])
            final_response = (
                run_result.get("result", {}).get("final_response")
                if isinstance(run_result.get("result"), dict)
                else {}
            )
            final_artifacts = final_response.get("artifacts") if isinstance(final_response.get("artifacts"), dict) else {}

            pipeline_contract.update(
                {
                    "stop_reason": final_response.get("stop_reason"),
                    "budget_snapshot": final_response.get("budget") if isinstance(final_response.get("budget"), dict) else {},
                    "policy_snapshot": final_response.get("policy_snapshot") if isinstance(final_response.get("policy_snapshot"), dict) else {},
                    "pricing_version": final_response.get("pricing_version"),
                    "artifact_refs": {
                        "final_response_ref": final_artifacts.get("final_response_ref"),
                        "policy_snapshot_ref": final_artifacts.get("policy_snapshot_ref"),
                    },
                }
            )

        asyncio.run(_probe_pipeline_contract())

        usage_total_tokens = 0
        usage_total_cost_units = 0.0

        for stage in ("candidate", "validator", "final"):
            stage_payload = stage_refs.get(stage) or {}
            ref_payload = stage_payload.get("artifact_ref") if isinstance(stage_payload.get("artifact_ref"), dict) else {}
            usage_payload = stage_payload.get("usage") if isinstance(stage_payload.get("usage"), dict) else {}
            cost_payload = stage_payload.get("cost") if isinstance(stage_payload.get("cost"), dict) else {}
            usage_total_tokens += int(usage_payload.get("total_tokens") or 0)
            usage_total_cost_units += float(cost_payload.get("units") or 0.0)
            _record(
                assertions,
                f"modes.pipeline.{stage}.artifact_ref",
                bool(ref_payload.get("uri") and ref_payload.get("sha256")),
                f"{stage} stage artifact reference captured",
            )
            _record(
                assertions,
                f"modes.pipeline.{stage}.model_meta",
                bool(stage_payload.get("provider") and stage_payload.get("model")),
                f"{stage} stage includes provider/model metadata",
            )
            _record(
                assertions,
                f"modes.pipeline.{stage}.usage_meta",
                bool(int(usage_payload.get("total_tokens") or 0) >= 0),
                f"{stage} stage includes usage metadata",
            )
            _record(
                assertions,
                f"modes.pipeline.{stage}.cost_meta",
                bool(isinstance(cost_payload.get("units"), (int, float)) and stage_payload.get("provider") and stage_payload.get("model")),
                f"{stage} stage includes cost metadata",
            )

        budget_snapshot = pipeline_contract.get("budget_snapshot") if isinstance(pipeline_contract.get("budget_snapshot"), dict) else {}
        policy_snapshot = pipeline_contract.get("policy_snapshot") if isinstance(pipeline_contract.get("policy_snapshot"), dict) else {}
        pipeline_artifact_refs = pipeline_contract.get("artifact_refs") if isinstance(pipeline_contract.get("artifact_refs"), dict) else {}
        final_response_ref = (
            pipeline_artifact_refs.get("final_response_ref")
            if isinstance(pipeline_artifact_refs.get("final_response_ref"), dict)
            else {}
        )
        policy_snapshot_ref = (
            pipeline_artifact_refs.get("policy_snapshot_ref")
            if isinstance(pipeline_artifact_refs.get("policy_snapshot_ref"), dict)
            else {}
        )

        _record(
            assertions,
            "modes.pipeline.final.budget_snapshot",
            bool("consumed_tokens" in budget_snapshot and "consumed_cost_units" in budget_snapshot),
            "llm_pipeline final response includes budget snapshot",
        )
        _record(
            assertions,
            "modes.pipeline.final.policy_snapshot",
            bool(
                str(policy_snapshot.get("policy_version") or "").strip()
                and str(policy_snapshot.get("pricing_version") or "").strip()
                and str(policy_snapshot.get("fingerprint") or "").strip()
            ),
            "llm_pipeline final response includes versioned policy snapshot",
        )
        _record(
            assertions,
            "modes.pipeline.final.artifact_ref",
            bool(final_response_ref.get("uri") and final_response_ref.get("sha256")),
            "llm_pipeline final response artifact reference captured",
        )
        _record(
            assertions,
            "modes.pipeline.final.policy_artifact_ref",
            bool(policy_snapshot_ref.get("uri") and policy_snapshot_ref.get("sha256")),
            "llm_pipeline policy snapshot artifact reference captured",
        )
        _record(
            assertions,
            "modes.pipeline.parity.usage_budget",
            bool(usage_total_tokens >= 0 and "consumed_tokens" in budget_snapshot),
            "simulation captures both stage usage totals and pipeline budget snapshot",
            expected="usage+budget_metadata_present",
            actual={
                "stage_total_tokens": usage_total_tokens,
                "budget_consumed_tokens": budget_snapshot.get("consumed_tokens"),
            },
        )
        _record(
            assertions,
            "modes.pipeline.parity.cost_credits",
            bool(usage_total_cost_units >= 0.0 and "consumed_cost_units" in budget_snapshot),
            "simulation captures cost/credits parity metadata",
            expected="cost+credits_metadata_present",
            actual={
                "stage_total_cost_units": round(usage_total_cost_units, 6),
                "budget_consumed_cost_units": budget_snapshot.get("consumed_cost_units"),
            },
        )

        artifacts["mode_response"] = mode_resp.json() if mode_resp.status_code == 200 else {}
        artifacts["mode_payload_artifact"] = payload_artifact
        artifacts["pipeline_stage_refs"] = stage_refs
        artifacts["pipeline_budget_snapshot"] = budget_snapshot
        artifacts["pipeline_policy_snapshot"] = policy_snapshot
        artifacts["pipeline_artifact_refs"] = pipeline_artifact_refs
        artifacts["pipeline_usage_totals"] = {
            "total_tokens": usage_total_tokens,
            "total_cost_units": round(usage_total_cost_units, 6),
        }
        artifacts["pipeline_credit_totals"] = {
            "estimated_credits": round(usage_total_cost_units, 6),
            "pricing_version": pipeline_contract.get("pricing_version"),
        }
        artifacts["llm_mode"] = llm_mode
        artifacts["llm_provider"] = llm_provider
        artifacts["llm_model"] = llm_model

        passed = all(item.passed for item in assertions)
        return ScenarioResult(
            scenario_id="S4",
            title="Modes registry run path",
            passed=passed,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
        )
    except Exception as error:
        return ScenarioResult(
            scenario_id="S4",
            title="Modes registry run path",
            passed=False,
            started_at=utcnow_iso(),
            finished_at=utcnow_iso(),
            duration_ms=int((time.perf_counter() - started) * 1000),
            assertions=assertions,
            artifacts=artifacts,
            error=str(error),
        )


def run_simulation(
    *,
    output_dir: str | Path,
    include_modes: bool = True,
    llm_mode: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> SimulationReport:
    run_started = time.perf_counter()
    started_at = utcnow_iso()
    run_id = f"sim-{uuid.uuid4().hex[:10]}"
    effective_llm_mode = str(llm_mode or os.getenv("SIM_LLM_MODE", "stub")).strip().lower()
    if effective_llm_mode not in ("stub", "real"):
        effective_llm_mode = "stub"
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"{run_id}.db"

    _set_sim_env(db_path)
    fake_redis = InMemoryAsyncRedis()

    with ExitStack() as stack:
        stack.enter_context(patch("app.main.init_metrics", lambda *args, **kwargs: None))
        stack.enter_context(patch("app.infrastructure.monitoring.monitoring.metrics.init_metrics", lambda *args, **kwargs: None))
        stack.enter_context(patch("app.main.redis.from_url", return_value=fake_redis))
        stack.enter_context(patch("app.diagnostic_session.create_diagnostic_session", side_effect=_stub_create_diagnostic_session))
        stack.enter_context(patch("app.lesson_engine_pipeline.generate_lesson_from_pipeline_async", side_effect=_stub_generate_lesson_from_pipeline_async))
        stack.enter_context(patch("app.lesson_engine.grade_submission", side_effect=_stub_grade_submission))
        stack.enter_context(patch("app.lesson_engine.generate_lesson_summary", side_effect=_stub_lesson_summary))

        from app.main import create_app

        app = create_app()
        app.state.saga_orchestrator = _FakeSagaOrchestrator()
        app.state.saga_event_bus_consumer_factory = None
        app.state.saga_waiting_confirm_archiver_factory = None
        app.state.saga_recovery_worker_factory = None
        app.state.saga_dlq_maintenance_factory = None

        with TestClient(app) as client:
            user_resp = client.post(
                "/v1/users",
                json={"user_id": "sim_user", "email": "sim_user@seed.local", "meta": {}},
            )
            token = user_resp.json().get("api_key") if user_resp.status_code == 200 else ""

            scenarios = [
                _run_s1(client, app, token),
                _run_s2(client, app, token),
                _run_s3(client, app, token),
            ]
            if include_modes:
                scenarios.append(
                    _run_s4(
                        client,
                        app,
                        token,
                        out_dir,
                        effective_llm_mode,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                    )
                )

    passed_count = sum(1 for item in scenarios if item.passed)
    failed_count = len(scenarios) - passed_count
    report = SimulationReport(
        run_id=run_id,
        started_at=started_at,
        finished_at=utcnow_iso(),
        duration_ms=int((time.perf_counter() - run_started) * 1000),
        passed=failed_count == 0,
        scenario_count=len(scenarios),
        passed_count=passed_count,
        failed_count=failed_count,
        scenarios=scenarios,
        metadata={
            "db_path": str(db_path),
            "redis_mode": "in_memory",
            "include_modes": include_modes,
            "llm_mode": effective_llm_mode,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
        },
        run_metadata={
            "harness_version": "2.0",
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "runner": "app.sim.run",
            "cwd": str(Path.cwd()),
            "output_dir": str(out_dir),
            "include_modes": include_modes,
            "llm_mode": effective_llm_mode,
            "llm_provider": llm_provider,
            "llm_model": llm_model,
            "argv": list(sys.argv),
            "seed_db_path": str(db_path),
        },
    )
    return report
