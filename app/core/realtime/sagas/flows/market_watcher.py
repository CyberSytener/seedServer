from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional

from app.core.realtime.engine import BaseSaga, SagaStepDefinition, SagaStepResult
from app.infrastructure.db.pgvector_store import PgvectorStore
from app.services.job.scanner import JobScanner
from app.services.job.scorer import JobScorer
from app.services.job.sources import ArbetsformedlingenSource, RemotiveJobSource


class MarketWatcherFlow(BaseSaga):
    saga_type = "market_watcher"

    async def run(
        self,
        saga_id: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        request_payload = self._normalize_payload(payload)
        user_id = self._resolve_user_id(payload, request_payload)
        persona = self._resolve_persona(request_payload)
        scan_id = self._resolve_scan_id(request_payload)

        scanner = self._resolve_scanner()
        scorer = self._resolve_scorer()

        scan_result = None

        async def _scan_jobs() -> SagaStepResult:
            nonlocal scan_result
            scan_result = await scanner.scan_for_user(user_id, persona)
            meta = {
                "source_counts": scan_result.source_counts,
                "job_count": len(scan_result.jobs),
            }
            return SagaStepResult(meta=meta, result={"scan_id": scan_id})

        async def _score_jobs() -> SagaStepResult:
            if scan_result is None:
                raise RuntimeError("scan_result missing before scoring")
            if not scan_result.jobs:
                return SagaStepResult(meta={"scored_count": 0}, result={"scored_count": 0})
            scored = await scorer.score_batch(
                user_id=user_id,
                jobs=scan_result.jobs,
                persona=persona,
                scan_id=scan_id,
                persist=True,
            )
            meta = {
                "scored_count": len(scored),
            }
            return SagaStepResult(meta=meta, result={"scored_count": len(scored)})

        step_plan = [
            SagaStepDefinition(name="scan_jobs", execute=_scan_jobs),
            SagaStepDefinition(name="score_jobs", execute=_score_jobs),
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

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload.get("request") or payload.get("params") or payload

    @staticmethod
    def _resolve_user_id(payload: Dict[str, Any], request_payload: Dict[str, Any]) -> str:
        user_id = request_payload.get("user_id") or payload.get("user_id")
        if not user_id:
            raise ValueError("market_watcher requires user_id")
        return user_id

    @staticmethod
    def _resolve_persona(request_payload: Dict[str, Any]) -> Dict[str, Any]:
        return request_payload.get("persona") or request_payload

    @staticmethod
    def _resolve_scan_id(request_payload: Dict[str, Any]) -> str:
        scan_id = request_payload.get("scan_id")
        return scan_id or str(uuid.uuid4())

    def _resolve_scanner(self) -> JobScanner:
        scanner = self.adapters.get("job_scanner") if hasattr(self, "adapters") else None
        if scanner:
            return scanner
        return JobScanner(self._resolve_sources())

    def _resolve_sources(self) -> Iterable[object]:
        sources = self.adapters.get("job_sources") if hasattr(self, "adapters") else None
        if sources:
            return sources
        return [
            ArbetsformedlingenSource(),
            RemotiveJobSource(),
        ]

    def _resolve_scorer(self) -> JobScorer:
        scorer = self.adapters.get("job_scorer") if hasattr(self, "adapters") else None
        if scorer:
            return scorer
        vector_store = PgvectorStore(self.db)
        return JobScorer(vector_store=vector_store, db=self.db)
