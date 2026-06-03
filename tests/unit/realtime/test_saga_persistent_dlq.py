import pytest
from unittest.mock import AsyncMock

from app.core.realtime.sagas.orchestrator import SagaOrchestrator, SagaState


class _FakeDB:
    def __init__(self, rows=None, row=None, execute_result="DELETE 1"):
        self.rows = rows or []
        self.row = row
        self.execute_result = execute_result

    async def fetch(self, query, *args):
        return self.rows

    async def fetchrow(self, query, *args):
        return self.row

    async def execute(self, query, *args):
        return self.execute_result


@pytest.mark.asyncio
async def test_list_persistent_dlq_messages_normalizes_json_fields():
    fake_rows = [
        {
            "id": 1,
            "saga_id": "saga-1",
            "saga_state": '{"stop_reason":"validation_failed"}',
            "attempted_compensation_steps": '["step-1"]',
            "tags": '{"k":"v"}',
        }
    ]
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator.db = _FakeDB(rows=fake_rows)

    rows = await orchestrator.list_persistent_dlq_messages(limit=10)

    assert len(rows) == 1
    assert rows[0]["saga_state"] == {"stop_reason": "validation_failed"}
    assert rows[0]["attempted_compensation_steps"] == ["step-1"]
    assert rows[0]["tags"] == {"k": "v"}


@pytest.mark.asyncio
async def test_retry_persistent_dlq_message_returns_updated_row():
    fake_row = {
        "id": 2,
        "saga_id": "saga-2",
        "retry_count": 1,
        "saga_state": {},
        "attempted_compensation_steps": [],
        "tags": {},
    }
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator.db = _FakeDB(row=fake_row)

    updated = await orchestrator.retry_persistent_dlq_message("saga-2", retry_delay_seconds=30)

    assert updated is not None
    assert updated["saga_id"] == "saga-2"
    assert updated["retry_count"] == 1


@pytest.mark.asyncio
async def test_remove_persistent_dlq_message_returns_deleted_count():
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator.db = _FakeDB(execute_result="DELETE 1")

    removed = await orchestrator.remove_persistent_dlq_message("saga-3")

    assert removed == 1


@pytest.mark.asyncio
async def test_list_persistent_dlq_retry_candidates_returns_rows():
    fake_rows = [
        {
            "id": 11,
            "saga_id": "saga-retry-1",
            "saga_state": "{}",
            "attempted_compensation_steps": "[]",
            "tags": '{"triage_status":"queued"}',
        }
    ]
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator.db = _FakeDB(rows=fake_rows)

    rows = await orchestrator.list_persistent_dlq_retry_candidates(limit=20)

    assert len(rows) == 1
    assert rows[0]["saga_id"] == "saga-retry-1"
    assert rows[0]["tags"]["triage_status"] == "queued"


@pytest.mark.asyncio
async def test_bulk_triage_persistent_dlq_messages_returns_updated_count():
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator.db = _FakeDB(execute_result="UPDATE 3")

    updated = await orchestrator.bulk_triage_persistent_dlq_messages(
        ["saga-a", "saga-b", "saga-c"],
        triage_status="queued",
        note="batch triage",
        retry_delay_seconds=120,
    )

    assert updated == 3


@pytest.mark.asyncio
async def test_purge_persistent_dlq_messages_returns_deleted_count():
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator.db = _FakeDB(execute_result="DELETE 7")

    deleted = await orchestrator.purge_persistent_dlq_messages(older_than_days=14, limit=500)

    assert deleted == 7


@pytest.mark.asyncio
async def test_replay_saga_from_dlq_restarts_non_succeeded_saga():
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator._get_saga = AsyncMock(
        return_value={
            "saga_id": "saga-4",
            "action_id": "action-4",
            "saga_type": "llm_pipeline",
            "saga_version": "v1",
            "state": SagaState.FAILED.value,
            "payload": {"foo": "bar", "correlation_id": "corr-4"},
            "steps": [],
            "user_id": "u-4",
            "correlation_id": "corr-4",
        }
    )
    orchestrator._update_saga_state = AsyncMock()
    orchestrator._run_saga = AsyncMock()

    result = await orchestrator.replay_saga_from_dlq("saga-4")

    assert result["status"] == "replayed"
    orchestrator._update_saga_state.assert_awaited_once()
    orchestrator._run_saga.assert_awaited_once()


@pytest.mark.asyncio
async def test_replay_saga_from_dlq_skips_already_succeeded():
    orchestrator = SagaOrchestrator("postgresql://localhost/test", adapter_registry={}, async_mode=True)
    orchestrator._get_saga = AsyncMock(return_value={"saga_id": "saga-5", "state": SagaState.SUCCEEDED.value})

    result = await orchestrator.replay_saga_from_dlq("saga-5")

    assert result["status"] == "skipped"
    assert result["reason"] == "already_succeeded"
