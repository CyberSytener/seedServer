from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infrastructure.redis.worker import process_job


class FakeDB:
    def __init__(self, *, claim_succeeds: bool):
        self.claim_succeeds = claim_succeeds
        self.row = {
            "id": "job_1",
            "status": "queued",
            "not_before": None,
            "user_id": "u1",
            "action": "fix",
            "input_text": "hello",
            "options_json": '{"correlation_id":"corr-test-1"}',
            "mode": "fast",
            "persona_id_used": None,
        }

    def fetchone(self, sql: str, params=()):
        if "SELECT * FROM jobs" in sql:
            return dict(self.row)
        if "SELECT status, started_at FROM jobs" in sql:
            return {"status": self.row.get("status"), "started_at": self.row.get("started_at")}
        return None

    def execute(self, sql: str, params=()):
        if "UPDATE jobs SET status='running'" in sql:
            if self.row.get("status") == "queued" and self.claim_succeeds:
                self.row["status"] = "running"
                self.row["started_at"] = params[0]
            return

        if "UPDATE jobs\n            SET status='done'" in sql or "UPDATE jobs SET status='done'" in sql:
            self.row["status"] = "done"
            return

        if "UPDATE jobs SET status='failed'" in sql:
            self.row["status"] = "failed"
            return


class FakeBroker:
    def __init__(self):
        self.events = []

    async def publish(self, user_id: str, event: str, data):
        self.events.append((user_id, event, data))


class FakeExecutor:
    def __init__(self):
        self.calls = 0

    async def execute_action(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            provider="stub",
            model="stub-model",
            persona_id_used=None,
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            text="ok",
        )


@pytest.mark.asyncio
async def test_process_job_skips_when_claim_not_acquired():
    db = FakeDB(claim_succeeds=False)
    broker = FakeBroker()
    executor = FakeExecutor()

    await process_job(db=db, broker=broker, job_id="job_1", executor=executor, worker_name="w1")

    assert executor.calls == 0
    assert db.row["status"] == "queued"
    assert not broker.events


@pytest.mark.asyncio
async def test_process_job_executes_once_when_claim_acquired():
    db = FakeDB(claim_succeeds=True)
    broker = FakeBroker()
    executor = FakeExecutor()

    await process_job(db=db, broker=broker, job_id="job_1", executor=executor, worker_name="w1")

    assert executor.calls == 1
    assert db.row["status"] == "done"
    assert any(event == "job_done" for _, event, _ in broker.events)
    done_events = [data for _, event, data in broker.events if event == "job_done"]
    assert done_events
    assert done_events[0].get("correlation_id") == "corr-test-1"
