import pytest
from unittest.mock import AsyncMock

from app.core.realtime.sagas.orchestrator import SagaOrchestrator, SagaState


@pytest.mark.asyncio
async def test_resume_saga_on_confirm_db_error_triggers_compensation():
    """If a saga confirm step raises a DB-related error, compensation should run."""

    class DBErrorAdapter:
        def confirm(self, original_payload, confirm_payload):
            # Simulate a DB error raised by adapter/DB interaction during confirm
            raise Exception("DB error: deadlock detected")

        async def compensate(self, payload):
            # Compensation logic (would be awaited by orchestrator)
            return {"status": "cancelled"}

    adapter = DBErrorAdapter()

    orch = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry={"booking": adapter},
        async_mode=True,
    )

    saga_id = "saga-db-error"

    # _get_saga returns a waiting-for-confirm saga with a prior reserve step
    orch._get_saga = AsyncMock(return_value={
        "saga_id": saga_id,
        "state": SagaState.WAITING_CONFIRM.value,
        "payload": {"user_id": "u-test"},
        "steps": [
            {"name": "reserve_slot", "status": "succeeded", "meta": {"reservation_id": "RESV_db", "status": "pending"}}
        ],
    })

    # Prevent real DB calls in tests
    orch._update_saga_state = AsyncMock()
    orch._compensate_saga = AsyncMock()

    res = await orch.resume_saga_on_confirm(saga_id, {"reservation_id": "RESV_db", "confirmed": True})

    assert res.get("status") == "failed"
    assert res.get("compensated") is True
    # Ensure orchestrator attempted to compensate
    orch._compensate_saga.assert_awaited()

