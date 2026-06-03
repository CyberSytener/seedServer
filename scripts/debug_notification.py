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
from app.services.job.sources import MockJobSource


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


BLUEPRINT = [
    {
        "id": "scanner_step",
        "block": "market_scanner",
        "inputs": {
            "user_id": {"from": "request.user_id"},
            "persona": {"from": "request.persona"},
        },
    },
    {
        "id": "scorer_step",
        "block": "job_scorer",
        "inputs": {
            "jobs": {"from": "scanner_step.jobs"},
            "persona": {"from": "request.persona"},
            "user_id": {"from": "request.user_id"},
            "scan_id": {"from": "scan_id"},
            "persist": True,
        },
    },
    {
        "id": "notify_step",
        "block": "notification_block",
        "params": {
            "top_n": 3,
            "template": "{title} at {company} ({location}) score={score}",
        },
        "inputs": {
            "items": {"from": "scorer_step.scored_jobs"},
            "recipient_info": {"from": "request.recipient"},
        },
    },
]


async def run_notification_test() -> None:
    dsn = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL") or "postgresql://localhost/seed_server"
    print(f"Using DB: {dsn}")
    db = await AsyncPGDatabase.create(dsn)
    try:
        sources = [MockJobSource()]
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

        payload = {
            "request": {
                "user_id": str(uuid.uuid4()),
                "persona": {
                    "keywords": ["Python", "Saga"],
                    "location": "Remote",
                },
                "recipient": {
                    "channel": "console",
                    "user": "architect",
                },
            }
        }

        saga = DynamicSaga(engine=engine, blueprint=BLUEPRINT, registry=build_default_registry())
        result = await saga.run(
            saga_id=str(uuid.uuid4()),
            payload=payload,
            steps=[],
        )

        print("Notification test result:")
        print(result)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_notification_test())
