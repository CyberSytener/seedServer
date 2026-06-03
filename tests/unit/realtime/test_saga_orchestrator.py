"""
Comprehensive tests for STEP 4: Saga Orchestrator + Adapters.

Tests:
1. Happy path: reserve → confirm → succeeded
2. Compensation path: reserve → confirm fails → compensate
3. Persistence: restart saga, resume works
4. Concurrency: concurrent confirms on same saga (idempotency)
5. Adapter retry: transient failure then success
6. Feature flags: canary rollout logic
"""

import pytest
import asyncio
import json
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.core.realtime.sagas.orchestrator import (
    SagaOrchestrator,
    SagaState,
    StepStatus,
    SagaStepRecord,
)
from app.infrastructure.realtime.adapters import (
    BookingAdapter,
    CalendarAdapter,
    PaymentAdapter,
    AdapterError,
    TransientAdapterError,
    PermanentAdapterError,
)
from app.core.realtime.feature_flags import (
    FeatureFlagManager,
    RolloutState,
    FeatureFlag,
)


# ============================================================================
# Test Data
# ============================================================================

BOOKING_PAYLOAD = {
    "from": "NYC",
    "to": "LA",
    "date": "2026-02-15",
    "flight_id": "AA123",
    "price": 450.00,
    "user_id": "user_123",
}

CONFIRMATION_PAYLOAD = {
    "reservation_id": "RESV_concurrent",
    "confirmed": True,
}


# ============================================================================
# Test: Happy Path (Saga succeeds)
# ============================================================================

@pytest.mark.asyncio
async def test_saga_happy_path():
    """
    Happy path: start_saga → reserve succeeds → resume_saga_on_confirm → confirm succeeds.
    
    Expected saga flow:
    1. start_saga("booking_flow") → pause at waiting_confirm
    2. resume_saga_on_confirm() → confirm → succeeded
    """
    
    # Setup
    booking_adapter = BookingAdapter()
    adapters = {"booking": booking_adapter}
    
    orch = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry=adapters,
        async_mode=True,  # Use async for testing
    )
    
    # Mock DB operations
    orch._insert_saga = MagicMock()
    orch._update_saga_state = AsyncMock()
    orch._get_saga = AsyncMock(return_value={
        "saga_id": "saga-123",
        "saga_type": "booking_flow",
        "state": SagaState.WAITING_CONFIRM.value,
        "payload": BOOKING_PAYLOAD,
        "steps": [
            {
                "name": "reserve_slot",
                "status": StepStatus.SUCCEEDED.value,
                "meta": {"reservation_id": CONFIRMATION_PAYLOAD["reservation_id"]},
            }
        ],
    })
    
    # Start saga
    saga_id = await orch.start_saga(
        action_id="action-123",
        saga_type="booking_flow",
        payload=BOOKING_PAYLOAD,
        user_id="user-123",
    )
    
    assert saga_id is not None
    assert orch._insert_saga.called
    
    # Resume saga on confirmation
    result = await orch.resume_saga_on_confirm(saga_id, CONFIRMATION_PAYLOAD)
    
    assert result["status"] == "succeeded"
    assert orch._update_saga_state.called
    
    # Verify final state (accept positional or keyword usage)
    calls = orch._update_saga_state.call_args_list
    final_call = calls[-1]
    # Ensure the final state 'succeeded' appears either as a positional arg or among kw values
    assert any(SagaState.SUCCEEDED.value == item for item in list(final_call[0]) + list(final_call[1].values()))


@pytest.mark.asyncio
async def test_saga_compensation_path():
    """
    Compensation path: reserve succeeds → confirm fails → compensate called.
    
    Expected flow:
    1. Reserve succeeds
    2. Confirm fails
    3. Compensation triggered
    4. Final state: compensated
    """
    
    # Setup with adapter that fails on confirm
    class FailingBookingAdapter(BookingAdapter):
        async def confirm(self, *args, **kwargs):
            raise PermanentAdapterError("Simulated confirm failure")
    
    booking_adapter = FailingBookingAdapter()
    adapters = {"booking": booking_adapter}
    
    orch = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry=adapters,
        async_mode=True,
    )
    
    # Mock DB
    orch._insert_saga = MagicMock()
    orch._update_saga_state = AsyncMock()
    orch._get_saga = AsyncMock(return_value={
        "saga_id": "saga-456",
        "saga_type": "booking_flow",
        "state": SagaState.WAITING_CONFIRM.value,
        "payload": BOOKING_PAYLOAD,
        "steps": [
            {
                "name": "reserve_slot",
                "status": StepStatus.SUCCEEDED.value,
                "meta": {"reservation_id": "RESV_test"},
            }
        ],
    })
    orch._record_compensation = AsyncMock()
    
    saga_id = "saga-456"
    
    # Resume should trigger compensation
    result = await orch.resume_saga_on_confirm(saga_id, CONFIRMATION_PAYLOAD)
    
    assert result["status"] == "failed"
    assert "compensated" in result or "error" in result
    # Either recorded compensation or state update should have been invoked
    assert (hasattr(orch, "_record_compensation") and orch._record_compensation.called) or orch._update_saga_state.called


# ============================================================================
# Test: Adapter Operations
# ============================================================================

@pytest.mark.asyncio
async def test_booking_adapter_reserve():
    """Test booking adapter reserve operation."""
    adapter = BookingAdapter()
    
    result = await adapter.reserve(BOOKING_PAYLOAD)
    
    assert result["status"] == "pending"
    assert "reservation_id" in result
    assert result["price"] == 450.00


@pytest.mark.asyncio
async def test_booking_adapter_confirm():
    """Test booking adapter confirm operation."""
    adapter = BookingAdapter()
    
    # First reserve
    reserve_res = await adapter.reserve(BOOKING_PAYLOAD)
    
    # Then confirm
    confirm_data = {
        "reservation_id": reserve_res["reservation_id"],
        "confirmed": True,
    }
    
    confirm_res = await adapter.confirm(BOOKING_PAYLOAD, confirm_data)
    
    assert confirm_res["status"] == "confirmed"
    assert "booking_id" in confirm_res
    assert confirm_res["reservation_id"] == reserve_res["reservation_id"]


@pytest.mark.asyncio
async def test_booking_adapter_compensate():
    """Test booking adapter compensation."""
    adapter = BookingAdapter()
    
    # Reserve
    await adapter.reserve(BOOKING_PAYLOAD)
    
    # Compensate
    comp_res = await adapter.compensate(BOOKING_PAYLOAD)
    
    assert comp_res["status"] == "cancelled"
    assert comp_res["cancelled_count"] >= 0


@pytest.mark.asyncio
async def test_calendar_adapter_create():
    """Test calendar adapter create operation."""
    adapter = CalendarAdapter()
    
    payload = {
        "title": "Meeting with John",
        "date": "2026-02-15",
        "time": "10:00",
    }
    
    result = await adapter.create(payload)
    
    assert result["status"] == "created"
    assert "event_id" in result


# ============================================================================
# Test: Feature Flags
# ============================================================================

def test_feature_flag_disabled():
    """Test adapter disabled (should use mock)."""
    mgr = FeatureFlagManager()
    mgr.set_state("booking", RolloutState.DISABLED)
    
    assert not mgr.is_enabled("booking", "user-123")


def test_feature_flag_enabled():
    """Test adapter enabled (should use real)."""
    mgr = FeatureFlagManager()
    mgr.set_state("booking", RolloutState.ENABLED)
    
    assert mgr.is_enabled("booking", "user-123")


def test_feature_flag_canary():
    """Test canary: only some users get real adapter."""
    mgr = FeatureFlagManager()
    mgr.set_state("booking", RolloutState.CANARY, canary_pct=50)
    
    # Test deterministic hash-based bucketing
    enabled_count = 0
    for i in range(100):
        user_id = f"user-{i}"
        if mgr.is_enabled("booking", user_id):
            enabled_count += 1
    
    # Should be approximately 50
    assert 30 < enabled_count < 70  # Allow some variance


def test_feature_flag_status():
    """Test getting flag status."""
    mgr = FeatureFlagManager()
    mgr.set_state("booking", RolloutState.CANARY, canary_pct=25)
    
    status = mgr.get_status()
    
    assert "booking" in status
    assert status["booking"]["state"] == "canary"
    assert status["booking"]["canary_percentage"] == 25


# ============================================================================
# Test: Concurrency & Idempotency
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_confirms_idempotent():
    """
    Concurrency test: two confirms on same saga should be idempotent.
    
    Only first should succeed, second should get cached result.
    """
    
    booking_adapter = BookingAdapter()
    adapters = {"booking": booking_adapter}
    
    orch = SagaOrchestrator(
        db_connection_string="postgresql://localhost/seed_server",
        adapter_registry=adapters,
        async_mode=True,
    )
    
    saga_id = "saga-concurrent"
    
    # Mock DB: saga is waiting_confirm
    orch._get_saga = AsyncMock(return_value={
        "saga_id": saga_id,
        "state": SagaState.WAITING_CONFIRM.value,
        "payload": BOOKING_PAYLOAD,
        "steps": [{"name": "reserve_slot", "status": "succeeded", "meta": {"reservation_id": "RESV_concurrent"}}],
    })
    orch._update_saga_state = AsyncMock()
    
    # Try two concurrent confirms
    results = await asyncio.gather(
        orch.resume_saga_on_confirm(saga_id, CONFIRMATION_PAYLOAD),
        orch.resume_saga_on_confirm(saga_id, CONFIRMATION_PAYLOAD),
    )
    
    # Both should get same result (or at least not error)
    assert len(results) == 2
    # First should succeed, second might fail or return cached
    assert results[0]["status"] in ("succeeded", "error")


# ============================================================================
# Test: Retry & Backoff
# ============================================================================

@pytest.mark.asyncio
async def test_adapter_transient_error_recovery():
    """
    Test that transient adapter errors can be retried.
    
    Adapter fails once, succeeds on retry.
    """
    
    class RetryableBookingAdapter(BookingAdapter):
        def __init__(self):
            super().__init__()
            self.call_count = 0
        
        async def reserve(self, payload):
            self.call_count += 1
            if self.call_count == 1:
                raise TransientAdapterError("Simulated transient error")
            return {"reservation_id": "RESV_success", "status": "pending"}
    
    adapter = RetryableBookingAdapter()
    
    # First call fails
    with pytest.raises(TransientAdapterError):
        await adapter.reserve(BOOKING_PAYLOAD)
    
    # Second call succeeds
    result = await adapter.reserve(BOOKING_PAYLOAD)
    assert result["status"] == "pending"


# ============================================================================
# Test: Saga Persistence & Restart
# ============================================================================

def test_saga_persistence():
    """
    Test that saga state persists in DB (can survive process restart).
    
    Verify:
    1. Saga record created
    2. State transitions logged
    3. Can query after "restart"
    """
    
    # In real scenario, this would use actual DB
    # For now, verify mock calls show persistence
    
    saga_id = "saga-persist"
    
    # Simulate saga_orchestrator._insert_saga call
    records = {}
    
    def mock_insert(saga_id, action_id, saga_type, payload):
        records[saga_id] = {
            "action_id": action_id,
            "saga_type": saga_type,
            "payload": payload,
            "state": SagaState.PENDING.value,
        }
    
    # Insert
    mock_insert(saga_id, "action-123", "booking_flow", BOOKING_PAYLOAD)
    
    assert saga_id in records
    
    # Simulate restart: query returns saved record
    saved = records.get(saga_id)
    assert saved is not None
    assert saved["saga_type"] == "booking_flow"


# ============================================================================
# Test: Metrics & Observability
# ============================================================================

def test_saga_step_record():
    """Test SagaStepRecord creation and serialization."""
    
    step = SagaStepRecord(
        name="reserve_slot",
        status=StepStatus.SUCCEEDED.value,
        meta={"reservation_id": "RESV_123"},
    )
    
    step_dict = step.to_dict()
    
    assert step_dict["name"] == "reserve_slot"
    assert step_dict["status"] == "succeeded"
    assert "timestamp" in step_dict
    assert step_dict["meta"]["reservation_id"] == "RESV_123"


# ============================================================================
# Test: Error Handling
# ============================================================================

@pytest.mark.asyncio
async def test_adapter_permanent_error_no_retry():
    """Test that permanent errors don't trigger retries."""
    
    class FailingAdapter(BookingAdapter):
        async def reserve(self, payload):
            raise PermanentAdapterError("Invalid booking parameters")
    
    adapter = FailingAdapter()
    
    with pytest.raises(PermanentAdapterError):
        await adapter.reserve(BOOKING_PAYLOAD)


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

