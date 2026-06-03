import pytest
import asyncio
from unittest.mock import AsyncMock

from app.core.realtime.sagas.flows import BookingFlow
from app.core.realtime.sagas.orchestrator import SagaOrchestrator, SagaState

@pytest.mark.asyncio
async def test_run_booking_flow_with_async_reserve():
    class AsyncBookingAdapter:
        async def reserve(self, payload):
            await asyncio.sleep(0)
            return {"reservation_id": "R_async", "status": "pending"}

    adapter = AsyncBookingAdapter()
    orch = SagaOrchestrator(db_connection_string="postgresql://localhost/seed_server", adapter_registry={"booking": adapter}, async_mode=True)

    saga_id = "saga_async"
    steps = []
    orch._update_saga_state = AsyncMock()

    flow = BookingFlow(orch)
    await flow.run(saga_id, {"user_id": "u"}, steps)

    # After run, steps should include reserve_slot and await_user_confirm
    names = [s.get("name") for s in steps]
    assert "reserve_slot" in names
    assert "await_user_confirm" in names
    # Ensure update state to WAITING_CONFIRM was called
    assert any(call.args[1] == SagaState.WAITING_CONFIRM.value for call in orch._update_saga_state.call_args_list)

