from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.realtime.engine import SagaStepDefinition, SagaStepResult

from .legacy import CareerUpskillingFlow


class UpskillingLoopFlow(CareerUpskillingFlow):
    saga_type = "upskilling_loop"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        request_payload = payload.get("request") or payload.get("params") or payload
        user_skills = request_payload.get("user_skills") or []
        monitored_jobs = request_payload.get("monitored_jobs") or request_payload.get("jobs") or []
        target_role = request_payload.get("target_role")
        duration_weeks = int(request_payload.get("duration_weeks") or 8)
        assessment_mode = request_payload.get("assessment_mode") or "language"

        async def _analyze_gap() -> SagaStepResult:
            from app.services.career.upskilling import build_skill_gap_analysis, build_upskilling_plan

            analysis = build_skill_gap_analysis(
                user_skills=user_skills,
                monitored_jobs=monitored_jobs,
            )
            plan = build_upskilling_plan(
                missing_skills=analysis.missing_skills,
                target_role=target_role,
                duration_weeks=duration_weeks,
            )

            result_payload = {
                "analysis": analysis.to_dict(),
                "upskilling_plan": plan.to_dict(),
                "assessment_mode": assessment_mode,
            }
            meta = {
                "missing_skills": len(analysis.missing_skills),
                "matched_skills": len(analysis.matched_skills),
                "gap_score": analysis.gap_score,
            }

            if analysis.missing_skills:
                return SagaStepResult(meta=meta, result=result_payload, pause=True)

            result_payload["note"] = "No missing skills detected; upskilling not required"
            return SagaStepResult(meta=meta, result=result_payload)

        step_plan = [
            SagaStepDefinition(
                name="analyze_skill_gaps",
                execute=_analyze_gap,
            )
        ]

        return await self.execute_step_plan(
            saga_id=saga_id,
            saga_type=self.saga_type,
            payload=payload,
            steps=steps,
            step_plan=step_plan,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
