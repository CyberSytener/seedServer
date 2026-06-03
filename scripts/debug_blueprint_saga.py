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
from app.services.job.sources import MockJobSource, RemotiveJobSource


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


MARKET_WATCHER_BLUEPRINT = [
    {
        "id": "scanner_step",
        "block": "market_scanner",
        "params": {
            "limit": 5,
        },
        "inputs": {
            "user_id": {"from": "request.user_id"},
            "persona": {
                "keywords": {
                    "from": "request.persona.title",
                    "default": ["Generalist"],
                    "transform": [
                        {"name": "lower"},
                        {"name": "split", "sep": " "},
                    ],
                },
                "location": {"from": "request.persona.location", "default": "Remote"},
                "remote_only": {"from": "request.persona.remote_only", "default": False},
                "salary_min": {"from": "request.persona.salary_min", "default": None},
            },
        },
    },
    {
        "id": "scorer_step",
        "block": "job_scorer",
        "inputs": {
            "jobs": {"from": "scanner_step.jobs"},
            "persona": {"from": "request.persona"},
            "user_id": {"from": "request.user_id"},
        },
    },
]


async def run_dynamic_test() -> None:
    print("Building saga from JSON blueprint...")

    registry = build_default_registry()

    dsn = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL") or "postgresql://localhost/seed_server"
    print(f"Using DB: {dsn}")
    db = await AsyncPGDatabase.create(dsn)
    try:
        remotive_sources = [RemotiveJobSource(limit=5, timeout_sec=10)]
        mock_sources = [MockJobSource()]

        def build_engine(sources):
            scanner = JobScanner(sources)
            scorer = JobScorer(vector_store=PgvectorStore(db), db=db)
            return SimpleEngine(
                db=db,
                adapters={
                    "job_scanner": scanner,
                    "job_scorer": scorer,
                    "job_sources": sources,
                },
            )

        saga = DynamicSaga(engine=build_engine(remotive_sources), blueprint=MARKET_WATCHER_BLUEPRINT, registry=registry)

        user_id_primary = str(uuid.uuid4())
        payload = {
            "request": {
                "user_id": user_id_primary,
                "persona": {
                    "title": "Python Saga Pattern",
                    "location": "Remote",
                    "salary_min": 100000,
                },
            }
        }

        print(f"Running DynamicSaga for title: {payload['request']['persona']['title']}")
        result = await saga.run(
            saga_id=str(uuid.uuid4()),
            payload=payload,
            steps=[],
        )
        print("Primary run payload:")
        print(result.get("result"))

        scan_count = (result.get("result") or {}).get("source_counts", {}).get("remotive", 0)
        if scan_count == 0:
            print("Remotive returned 0 jobs; retrying with MockJobSource...")
            saga = DynamicSaga(engine=build_engine(mock_sources), blueprint=MARKET_WATCHER_BLUEPRINT, registry=registry)
            result = await saga.run(
                saga_id=str(uuid.uuid4()),
                payload=payload,
                steps=[],
            )
            print("Mock fallback payload:")
            print(result.get("result"))

        payload_default = {
            "request": {
                "user_id": str(uuid.uuid4()),
                "persona": {
                    "location": "Remote",
                },
            }
        }
        print("Running DynamicSaga with default keywords...")
        saga = DynamicSaga(engine=build_engine(mock_sources), blueprint=MARKET_WATCHER_BLUEPRINT, registry=registry)
        default_result = await saga.run(
            saga_id=str(uuid.uuid4()),
            payload=payload_default,
            steps=[],
        )
        print("Default run payload:")
        print(default_result.get("result"))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run_dynamic_test())
