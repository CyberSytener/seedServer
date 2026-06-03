from __future__ import annotations

import asyncio
import os
import uuid

from app.core.blocks import build_default_registry
from app.core.realtime.sagas.flows.dynamic_saga import DynamicSaga
from app.infrastructure.db.pgvector_store import PgvectorStore
from app.infrastructure.db.postgres import AsyncPGDatabase
from app.services.job.scanner import JobScanner
from app.services.job.scorer import JobScorer
from app.services.job.sources import RemotiveJobSource


class SimpleEngine:
    def __init__(self, db, adapters):
        self.db = db
        self.adapters = adapters

    async def execute_step_plan(
        self,
        *,
        saga_id,
        saga_type,
        payload,
        steps,
        step_plan,
        correlation_id=None,
        trace_id=None,
    ):
        result_payload = {}
        for step_def in step_plan:
            step_result = await step_def.execute()
            if step_result and step_result.result:
                result_payload.update(step_result.result)
        return {"status": "succeeded", "result": result_payload, "steps": steps}


async def run_once() -> None:
    dsn = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL") or "postgresql://localhost/seed_server"
    print(f"Using DB: {dsn}")
    db = await AsyncPGDatabase.create(dsn)
    try:
        user_id = str(uuid.uuid4())
        persona = {
            "keywords": ["python"],
            "location": "",
            "remote_only": False,
        }

        sources = [RemotiveJobSource(limit=10, timeout_sec=10)]
        scanner = JobScanner(sources)
        scorer = JobScorer(vector_store=PgvectorStore(db), db=db)

        engine = SimpleEngine(
            db=db,
            adapters={
                "job_scanner": scanner,
                "job_scorer": scorer,
                "job_sources": sources,
            },
        )

        blueprint = [
            {
                "name": "scan_jobs",
                "block": "market_scanner",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                },
            },
            {
                "name": "score_jobs",
                "block": "job_scorer",
                "inputs": {
                    "user_id": {"from": "user_id"},
                    "persona": {"from": "persona"},
                    "jobs": {"from": "jobs"},
                    "scan_id": {"from": "scan_id"},
                    "persist": True,
                },
            },
        ]

        saga = DynamicSaga(engine, blueprint=blueprint, registry=build_default_registry())
        result = await saga.run(
            saga_id=str(uuid.uuid4()),
            payload={"user_id": user_id, "request": {"user_id": user_id, "persona": persona}},
            steps=[],
        )
        print("Dynamic saga result:", result)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_once())
