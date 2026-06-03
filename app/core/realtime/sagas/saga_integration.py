"""
Saga Integration Layer

Provides a thin integration layer between external action inputs (e.g., ActionRouter,
WebSocket gateway) and the SagaOrchestrator.

Responsibilities:
- Map action_type -> saga_type
- Convert action payloads into saga context
- Start sagas on action input
- Resume sagas on user confirmation
- Expose saga status/audit queries
- Wire saga updates to external emitters
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple
import asyncio
import uuid
import re

from app.models.realtime import SagaStatusResponse
from app.core.realtime.sagas.orchestrator import SagaOrchestrator


UpdateEmitter = Callable[[Dict[str, Any]], Awaitable[None]] | Callable[[Dict[str, Any]], None]
ContextMapper = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class SagaMapping:
    """Mapping of external action type to saga type + context mapper."""

    action_type: str
    saga_type: str
    context_mapper: ContextMapper


class SagaActionRouter:
    """Resolves action types to saga definitions and context."""

    def __init__(self):
        self._mappings: Dict[str, SagaMapping] = {}

    def register_mapping(self, mapping: SagaMapping) -> None:
        self._mappings[mapping.action_type] = mapping

    def resolve(self, action_type: str, payload: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
        mapping = self._mappings.get(action_type)
        if not mapping:
            return None
        context = mapping.context_mapper(payload or {})
        return mapping.saga_type, context

    def list_actions(self) -> Dict[str, str]:
        """Return registered action_type -> saga_type mappings."""
        return {k: v.saga_type for k, v in self._mappings.items()}


class SagaRealtimeIntegration:
    """Primary integration for saga actions and commands."""

    def __init__(
        self,
        orchestrator: SagaOrchestrator,
        action_router: Optional[SagaActionRouter] = None,
        update_emitter: Optional[UpdateEmitter] = None,
    ):
        self.orchestrator = orchestrator
        self.action_router = action_router or SagaActionRouter()
        self.update_emitter = update_emitter

        # Wire saga updates to external emitter if provided
        if update_emitter is not None:
            self.orchestrator.saga_update_handler = update_emitter

    def register_mapping(
        self,
        action_type: str,
        saga_type: str,
        context_mapper: ContextMapper,
    ) -> None:
        self.action_router.register_mapping(
            SagaMapping(
                action_type=action_type,
                saga_type=saga_type,
                context_mapper=context_mapper,
            )
        )

    def register_default_cv_learning_mappings(self) -> None:
        """Register default mappings for CV generation and learning plan."""
        self.register_mapping(
            action_type="create_or_update_cv",
            saga_type="cv_generation",
            context_mapper=lambda data: {"request": data},
        )
        self.register_mapping(
            action_type="generate_learning_plan",
            saga_type="learning_plan",
            context_mapper=lambda data: {"request": data},
        )
        self.register_mapping(
            action_type="start_diagnostic_core",
            saga_type="diagnostic_core",
            context_mapper=lambda data: {"request": data},
        )
        self.register_mapping(
            action_type="career_upskilling",
            saga_type="career_upskilling",
            context_mapper=lambda data: {"request": data},
        )

    def register_career_growth_mapping(self) -> None:
        """Register mapping for the career growth end-to-end saga."""
        self.register_mapping(
            action_type="career_growth_flow",
            saga_type="career_growth_flow",
            context_mapper=lambda data: data or {},
        )

    async def handle_action(
        self,
        action_type: str,
        action_id: str,
        data: Dict[str, Any],
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a saga for the given action.

        Returns a dict with saga_id or error details.
        """
        resolved = self.action_router.resolve(action_type, data)
        if not resolved:
            return {
                "status": "error",
                "error": f"No saga mapping for action_type='{action_type}'",
            }

        saga_type, context = resolved
        saga_id = await self.orchestrator.start_saga(
            action_id=action_id,
            saga_type=saga_type,
            payload=context,
            user_id=user_id or session_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        return {
            "status": "ok",
            "saga_id": saga_id,
            "saga_type": saga_type,
        }

    async def handle_saga_command(
        self,
        command: str,
        saga_id: str,
        data: Optional[Dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle saga commands: confirm | status | audit."""
        data = data or {}

        if command in {"confirm", "status", "audit"}:
            authorized = await self._authorize_saga_access(saga_id, session_id)
            if not authorized:
                return {"status": "error", "error": "forbidden"}

        if command == "confirm":
            result = await self.orchestrator.resume_saga_on_confirm(saga_id, data)
            return {"status": "ok", "result": result}

        if command == "status":
            return await self._get_status_response(saga_id, session_id=session_id)

        if command == "audit":
            audit = await self.orchestrator.get_saga_audit(saga_id)
            return {"status": "ok", "audit": audit}

        return {"status": "error", "error": f"Unknown saga command: {command}"}

    async def handle_status_request(
        self,
        saga_id: str,
        *,
        session_id: Optional[str] = None,
    ) -> SagaStatusResponse:
        """Return a SagaStatusResponse for clients (WS/REST)."""
        return await self._get_status_response(saga_id, session_id=session_id)

    async def _get_status_response(
        self,
        saga_id: str,
        *,
        session_id: Optional[str],
    ) -> SagaStatusResponse:
        state = await self.orchestrator.get_saga_state(saga_id)
        if not state:
            return SagaStatusResponse(
                session_id=session_id or "",
                saga_id=saga_id,
                error="Saga not found",
            )

        if session_id and state.get("user_id") and session_id != state.get("user_id"):
            return SagaStatusResponse(
                session_id=session_id,
                saga_id=saga_id,
                error="Forbidden",
            )

        return SagaStatusResponse(
            session_id=session_id or state.get("user_id") or "",
            saga_id=saga_id,
            saga_type=state.get("saga_type"),
            state=state.get("state"),
            steps=state.get("steps") or [],
            result=state.get("result"),
            updated_at=state.get("updated_at"),
        )

    async def _authorize_saga_access(self, saga_id: str, session_id: Optional[str]) -> bool:
        if not session_id:
            return True
        state = await self.orchestrator.get_saga_state(saga_id)
        if not state:
            return False
        owner = state.get("user_id")
        if owner and owner != session_id:
            return False
        return True


def create_saga_integration(
    orchestrator: SagaOrchestrator,
    *,
    update_emitter: Optional[UpdateEmitter] = None,
) -> SagaRealtimeIntegration:
    """Factory to create SagaRealtimeIntegration with optional update emitter."""
    return SagaRealtimeIntegration(
        orchestrator=orchestrator,
        update_emitter=update_emitter,
    )


class LearningPlanAdapter:
    """Adapter wrapper around app.services.learning_plan.generate_learning_plan()."""

    def __init__(self, db: Any):
        self.db = db

    async def generate_plan(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.learning_plan import generate_learning_plan

        plan_id, profile, plan, first_lesson_request = await asyncio.to_thread(
            generate_learning_plan,
            db=self.db,
            user_id=payload.get("user_id"),
            target_language=payload.get("target_language"),
            native_language=payload.get("native_language"),
            topic=payload.get("topic"),
            session_id=payload.get("session_id"),
            estimated_cefr=payload.get("estimated_cefr"),
            weak_subskills=payload.get("weak_subskills"),
            lesson_length=payload.get("lesson_length", 15),
            persona_id=payload.get("persona_id"),
        )

        return {
            "plan_id": plan_id,
            "profile": profile.model_dump(by_alias=True) if hasattr(profile, "model_dump") else profile,
            "plan": plan.model_dump(by_alias=True) if hasattr(plan, "model_dump") else plan,
            "first_lesson_request": (
                first_lesson_request.model_dump(by_alias=True)
                if hasattr(first_lesson_request, "model_dump")
                else first_lesson_request
            ),
        }


class DiagnosticSessionAdapter:
    """Adapter for starting diagnostic placement test sessions."""

    def __init__(self, db: Any):
        self.db = db

    async def start_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from app.models.api import DiagnosticStartRequest
        from app import diagnostic_session

        request = DiagnosticStartRequest(
            nativeLanguage=payload.get("native_language"),
            targetLanguage=payload.get("target_language"),
            startLevelGuess=payload.get("start_level_guess") or "A2",
            useAdaptive=bool(payload.get("use_adaptive", False)),
        )

        session_id, items = diagnostic_session.create_diagnostic_session(
            db=self.db,
            user_id=payload.get("user_id"),
            request=request,
            persona_id=payload.get("persona_id"),
            use_adaptive=bool(payload.get("use_adaptive", False)),
            optimize_mode=bool(payload.get("optimize_mode", False)),
        )

        first_item = items[0] if items else None
        return {
            "session_id": session_id,
            "total_items": len(items),
            "next_item": first_item.model_dump(by_alias=True) if hasattr(first_item, "model_dump") else first_item,
        }


class PortfolioAnalyzerAdapter:
    """Adapter for portfolio analysis via Diagnostic Core."""

    async def analyze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.diagnostic.core import analyze_portfolio

        provider = payload.get("provider") or "gemini"
        model = payload.get("model") or "gemini-2.0-flash-exp"
        return analyze_portfolio(payload, provider=provider, model=model)


class SkillMatrixAdapter:
    """Adapter for skill matrix persistence."""

    def __init__(self, db: Any):
        self.db = db

    async def update_matrix(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.diagnostic.core import upsert_skill_matrix

        return upsert_skill_matrix(
            self.db,
            user_id=payload.get("user_id"),
            matrix=payload.get("matrix") or {},
            source=payload.get("source") or "diagnostic_core",
        )


class CareerEducationAdapter:
    """Adapter for skill gap analysis + lesson generation + persistence."""

    def __init__(self, db: Any):
        self.db = db

    async def generate_lessons(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        from app.services.career.upskilling import build_skill_gap_analysis, build_upskilling_plan
        from app.services.career.learning import create_analysis, create_track, create_lesson
        from app.models.api import (
            CareerUpskillingRequest,
            UserBaseData,
            MarketGapData,
            CareerLessonCreateRequest,
        )

        user_id = payload.get("user_id")
        user_skills = payload.get("current_skills") or payload.get("user_skills") or []
        target_role = payload.get("target_role") or payload.get("job_title")
        monitored_jobs = payload.get("vacancies") or payload.get("jobs") or []
        experience_years = int(payload.get("experience_years") or 0)
        languages = payload.get("languages") or []

        analysis = build_skill_gap_analysis(
            user_skills=user_skills,
            monitored_jobs=monitored_jobs,
        )

        market_gap = MarketGapData(
            missing_skills=analysis.missing_skills,
            critical_weakness=payload.get("critical_weakness"),
            priority_level=int(payload.get("priority_level") or 3),
        )

        user_base = UserBaseData(
            skills=user_skills,
            experience_years=experience_years,
            target_roles=[target_role] if target_role else [],
            languages=languages,
        )

        req = CareerUpskillingRequest(
            user_base_data=user_base,
            market_gap_data=market_gap,
            target_role=target_role,
            duration_weeks=int(payload.get("duration_weeks") or 8),
            success_threshold=int(payload.get("success_threshold") or 85),
        )

        def _slugify(value: str) -> str:
            cleaned = re.sub(r"[^a-zA-Z0-9\s-]+", "", value).strip().lower()
            return re.sub(r"\s+", "-", cleaned)

        plan = build_upskilling_plan(
            missing_skills=analysis.missing_skills,
            target_role=target_role,
            duration_weeks=req.duration_weeks,
        )

        lessons = []
        track_id = None
        analysis_id = None

        if self.db and user_id:
            def _persist():
                analysis_row = create_analysis(self.db, user_id, req)
                track = create_track(self.db, user_id, analysis_row)
                created_lessons = []
                for module in track.modules:
                    lesson_request = CareerLessonCreateRequest(
                        module_id=module.module_id,
                        title=module.title,
                        content={
                            "summary": "\n".join(module.objectives),
                            "read_more": f"https://example.com/learn/{_slugify(module.title)}",
                            "recommended_activities": module.recommended_activities,
                        },
                    )
                    lesson = create_lesson(self.db, user_id, track.track_id, lesson_request)
                    created_lessons.append(lesson)
                return analysis_row, track, created_lessons

            analysis_row, track, created_lessons = await asyncio.to_thread(_persist)
            analysis_id = analysis_row.analysis_id
            track_id = track.track_id
            for lesson in created_lessons:
                lessons.append(
                    {
                        "lesson_id": lesson.lesson_id,
                        "title": lesson.title,
                        "summary": lesson.content.get("summary"),
                        "read_more": lesson.content.get("read_more"),
                    }
                )
        else:
            for module in plan.modules:
                lessons.append(
                    {
                        "title": module.title,
                        "summary": "\n".join(module.objectives),
                        "read_more": f"https://example.com/learn/{_slugify(module.title)}",
                    }
                )

        return {
            "analysis_id": analysis_id,
            "track_id": track_id,
            "missing_skills": analysis.missing_skills,
            "lessons": lessons,
        }

    async def compensate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "noop", "reason": "lesson_cleanup_not_implemented"}


class JobDiscoveryAdapter:
    """Adapter for job vacancy discovery.

    .. deprecated::
        The IndeedScraper-based implementation has been removed.
        This adapter now returns a stub result.
    """

    def __init__(self, country_code: str = "com"):
        self.country_code = country_code

    async def search_jobs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = payload.get("query") or payload.get("target_role") or payload.get("job_title") or ""
        location = payload.get("location") or ""
        return {
            "query": query,
            "location": location,
            "total_found": 0,
            "vacancies": [],
            "source": "stub (IndeedScraper removed)",
        }

    async def compensate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "noop", "reason": "job_search_compensation_not_required"}


class EmailOutreachAdapter:
    """Adapter for sending outreach emails."""

    def __init__(self, email_client: Optional[Any] = None, default_sender: Optional[str] = None):
        self.email_client = email_client
        self.default_sender = default_sender

    async def send_application(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        to_email = payload.get("to") or payload.get("recipient")
        subject = payload.get("subject") or "Application"
        body = payload.get("body") or ""
        correlation_id = payload.get("correlation_id")
        sender = payload.get("sender") or self.default_sender

        if not self.email_client:
            return {
                "status": "skipped",
                "reason": "email_client_not_configured",
                "correlation_id": correlation_id,
            }

        if not sender or not to_email:
            return {
                "status": "failed",
                "error": "missing_sender_or_recipient",
                "correlation_id": correlation_id,
            }

        idempotency_key = correlation_id or str(uuid.uuid4())
        result = self.email_client.send_email(
            user_id=sender,
            to=[to_email] if isinstance(to_email, str) else to_email,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
        )

        message_id = getattr(result, "message_id", None) or result.get("message_id")
        sent_at = getattr(result, "sent_at", None) or result.get("sent_at")

        return {
            "status": "sent",
            "message_id": message_id,
            "sent_at": sent_at,
            "correlation_id": correlation_id,
        }

    async def send_email(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.send_application(payload)

    async def compensate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "noop", "reason": "email_compensation_not_supported"}


def create_cv_adapter(cv_processor: Any) -> Any:
    """Wrap CVProcessor to ensure generate_cv is available."""
    return cv_processor


def create_learning_plan_adapter(db: Any) -> LearningPlanAdapter:
    """Create a LearningPlanAdapter using the provided DB."""
    return LearningPlanAdapter(db)


def create_diagnostic_adapter(db: Any) -> DiagnosticSessionAdapter:
    """Create a DiagnosticSessionAdapter using the provided DB."""
    return DiagnosticSessionAdapter(db)


def create_portfolio_adapter() -> PortfolioAnalyzerAdapter:
    """Create a PortfolioAnalyzerAdapter."""
    return PortfolioAnalyzerAdapter()


def create_skill_matrix_adapter(db: Any) -> SkillMatrixAdapter:
    """Create a SkillMatrixAdapter using the provided DB."""
    return SkillMatrixAdapter(db)


def create_career_education_adapter(db: Any) -> CareerEducationAdapter:
    """Create a CareerEducationAdapter."""
    return CareerEducationAdapter(db)


def create_job_discovery_adapter(country_code: str = "com") -> JobDiscoveryAdapter:
    """Create a JobDiscoveryAdapter."""
    return JobDiscoveryAdapter(country_code=country_code)


def create_outreach_email_adapter(
    email_client: Optional[Any],
    default_sender: Optional[str],
) -> EmailOutreachAdapter:
    """Create an EmailOutreachAdapter."""
    return EmailOutreachAdapter(email_client=email_client, default_sender=default_sender)



