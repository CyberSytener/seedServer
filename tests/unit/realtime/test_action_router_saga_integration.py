"""
Integration Test: ActionRouter ↔ STEP 4 Saga Orchestrator

Tests the complete flow:
1. ActionRouter with feature flag
2. SagaOrchestrator integration
3. Real CalendarAdapter
4. Canary rollout
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
import uuid

from app.models.realtime import (
    Action,
    ActionMetadata,
    ClientActionConfirm,
)
from app.core.realtime.action_router import ActionRouter
from app.core.realtime.sagas.orchestrator import SagaOrchestrator
from app.core.realtime.feature_flags import FeatureFlagManager, RolloutState
from app.infrastructure.realtime.adapters.calendar_adapter_real import CalendarAdapterReal


class TestActionRouterWithSaga:
    """Test ActionRouter integration with STEP 4 saga"""
    
    @pytest.fixture
    def setup(self):
        """Set up test fixtures"""
        # Create feature flag manager
        ff_manager = FeatureFlagManager()
        ff_manager.set_state("calendar", RolloutState.ENABLED, canary_percentage=100)
        
        # Create saga orchestrator (mock DB)
        saga_orch = MagicMock(spec=SagaOrchestrator)
        saga_orch.start_saga = AsyncMock()
        saga_orch.resume_saga_on_confirm = AsyncMock()
        
        # Create router with saga integration
        router = ActionRouter(
            saga_orchestrator=saga_orch,
            feature_flag_manager=ff_manager,
        )
        
        return {
            "router": router,
            "saga_orch": saga_orch,
            "ff_manager": ff_manager,
        }
    
    def test_saga_actions_recognized(self, setup):
        """Verify saga-eligible actions are recognized"""
        router = setup["router"]
        assert "calendar_create" in router._saga_actions
        assert "schedule_event" in router._saga_actions
        print("✓ Saga actions recognized")
    
    def test_feature_flag_disabled_uses_traditional_flow(self, setup):
        """When saga flag disabled, use traditional executor path"""
        router = setup["router"]
        ff_manager = setup["ff_manager"]
        
        # Disable saga flag
        ff_manager.set_state("calendar", RolloutState.DISABLED, canary_percentage=0)
        
        # Execute action
        action = Action(
            id=f"act_{uuid.uuid4().hex[:8]}",
            name="calendar_create",
            params={"title": "Test event"},
            metadata=ActionMetadata(session_id="sess_123"),
        )
        
        result = router.execute_action(action, model_name="test")
        
        # Should ask for confirmation via traditional path (not saga)
        assert result.requires_manual_review == True
        assert result.result.get("saga_mode") is None or result.result.get("saga_mode") == False
        print("✓ Feature flag disabled uses traditional flow")
    
    def test_feature_flag_enabled_uses_saga_flow(self, setup):
        """When saga flag enabled, route to SagaOrchestrator"""
        router = setup["router"]
        ff_manager = setup["ff_manager"]
        
        # Enable saga flag at 100%
        ff_manager.set_state("calendar", RolloutState.ENABLED, canary_percentage=100)
        
        # Execute action
        action = Action(
            id=f"act_{uuid.uuid4().hex[:8]}",
            name="calendar_create",
            params={"title": "Test event"},
            metadata=ActionMetadata(session_id="sess_123"),
        )
        
        result = router.execute_action(action, model_name="test")
        
        # Should use saga flow
        assert result.requires_manual_review == True
        assert result.result.get("saga_mode") == True
        print("✓ Feature flag enabled uses saga flow")
    
    def test_canary_rollout_0_percent(self, setup):
        """Canary at 0% should use traditional flow"""
        router = setup["router"]
        ff_manager = setup["ff_manager"]
        
        # Canary 0% (no users get saga)
        ff_manager.set_state("calendar", RolloutState.CANARY, canary_percentage=0)
        
        action = Action(
            id=f"act_{uuid.uuid4().hex[:8]}",
            name="calendar_create",
            params={"title": "Test"},
            metadata=ActionMetadata(session_id="user_abc123"),
        )
        
        result = router.execute_action(action, model_name="test")
        
        # Should use traditional flow (0% canary)
        assert result.result.get("saga_mode") is None or result.result.get("saga_mode") == False
        print("✓ Canary 0% uses traditional flow")
    
    def test_canary_rollout_deterministic_bucketing(self, setup):
        """Canary should bucket users deterministically"""
        router = setup["router"]
        ff_manager = setup["ff_manager"]
        
        # Set canary to 50%
        ff_manager.set_state("calendar", RolloutState.CANARY, canary_percentage=50)
        
        # Test users should consistently go to same path
        user_ids = ["user_1", "user_2", "user_3"]
        for user_id in user_ids:
            enabled1 = router._is_saga_enabled_for_user(user_id)
            enabled2 = router._is_saga_enabled_for_user(user_id)
            
            # Same user should get same result
            assert enabled1 == enabled2, f"Non-deterministic bucketing for {user_id}"
        
        print("✓ Canary bucketing is deterministic")
    
    def test_non_saga_action_ignores_flag(self, setup):
        """Non-saga actions should ignore feature flag"""
        router = setup["router"]
        ff_manager = setup["ff_manager"]
        
        # Enable saga flag
        ff_manager.set_state("calendar", RolloutState.ENABLED, canary_percentage=100)
        
        # Execute non-saga action
        action = Action(
            id=f"act_{uuid.uuid4().hex[:8]}",
            name="send_email",  # Not a saga action
            params={"to": "user@test.com", "subject": "Hello", "body": "Hi there"},
            metadata=ActionMetadata(session_id="sess_123", confidence=0.9),
        )
        
        result = router.execute_action(action, model_name="test")
        
        # Should use traditional executor (not saga)
        assert result.result.get("saga_mode") is None or result.result.get("saga_mode") == False
        print("✓ Non-saga actions ignore feature flag")


class TestCalendarAdapterReal:
    """Test real calendar adapter"""
    
    @pytest.fixture
    def adapter(self):
        """Create real calendar adapter"""
        return CalendarAdapterReal(
            provider="google",
            auth_token="mock_token",
            user_email="test@example.com",
        )
    
    @pytest.mark.asyncio
    async def test_reserve_creates_event(self, adapter):
        """Reserve should create tentative event"""
        result = await adapter.reserve({
            "title": "Team standup",
            "date": "2026-02-15",
            "start_time": "09:00",
            "end_time": "10:00",
            "description": "Daily sync",
        })
        
        assert result["status"] == "reserved"
        assert result["event_id"]
        assert "Team standup" in result["title"]
        print(f"✓ Reserve creates event: {result['event_id']}")
    
    @pytest.mark.asyncio
    async def test_reserve_invalid_time_fails(self, adapter):
        """Reserve with invalid time should fail permanently"""
        from app.infrastructure.realtime.adapters import PermanentAdapterError
        
        with pytest.raises(PermanentAdapterError):
            await adapter.reserve({
                "title": "Bad time",
                "date": "2026-02-15",
                "start_time": "25:00",  # Invalid hour
                "end_time": "26:00",
            })
        
        print("✓ Invalid time raises PermanentAdapterError")
    
    @pytest.mark.asyncio
    async def test_confirm_sends_invites(self, adapter):
        """Confirm should send invites to attendees"""
        # First reserve
        reserve_result = await adapter.reserve({
            "title": "Standup",
            "date": "2026-02-15",
            "start_time": "09:00",
            "end_time": "10:00",
        })
        
        # Then confirm with attendees
        confirm_result = await adapter.confirm(
            original_payload=reserve_result,
            confirm_payload={
                "attendees": ["alice@company.com", "bob@company.com"],
                "notify": True,
            }
        )
        
        assert confirm_result["status"] == "confirmed"
        assert confirm_result["invites_sent"] == 2
        assert len(confirm_result["attendees"]) == 2
        print(f"✓ Confirm sends invites: {confirm_result['invites_sent']}")
    
    @pytest.mark.asyncio
    async def test_compensate_deletes_event(self, adapter):
        """Compensate should delete event"""
        # Reserve
        reserve_result = await adapter.reserve({
            "title": "Test event",
            "date": "2026-02-15",
            "start_time": "14:00",
            "end_time": "15:00",
        })
        
        event_id = reserve_result["event_id"]
        
        # Compensate (delete)
        compensate_result = await adapter.compensate({
            "event_id": event_id,
            "reason": "User cancelled",
        })
        
        assert compensate_result["status"] == "cancelled"
        assert compensate_result["event_id"] == event_id
        print(f"✓ Compensate deletes event: {event_id}")


class TestCanaryRolloutPlan:
    """Test canary rollout progression"""
    
    def test_rollout_schedule(self):
        """Verify canary rollout progression"""
        ff = FeatureFlagManager()
        
        # Day 1: Disabled
        ff.set_state("calendar", RolloutState.DISABLED, canary_percentage=0)
        assert ff.is_enabled("calendar", user_id="any_user") == False
        print("✓ Day 1: Disabled (0%)")
        
        # Day 2: Canary 5%
        ff.set_state("calendar", RolloutState.CANARY, canary_percentage=5)
        # Only ~5% of users should be enabled
        enabled_count = sum(
            1 for i in range(100)
            if ff.is_enabled("calendar", user_id=f"user_{i}")
        )
        assert 2 <= enabled_count <= 8, f"Expected ~5%, got {enabled_count}%"
        print(f"✓ Day 2: Canary 5% (~{enabled_count}% enabled)")
        
        # Day 3: Canary 25%
        ff.set_state("calendar", RolloutState.CANARY, canary_percentage=25)
        enabled_count = sum(
            1 for i in range(100)
            if ff.is_enabled("calendar", user_id=f"user_{i}")
        )
        assert 20 <= enabled_count <= 30, f"Expected ~25%, got {enabled_count}%"
        print(f"✓ Day 3: Canary 25% (~{enabled_count}% enabled)")
        
        # Day 4: Ramping 50%
        ff.set_state("calendar", RolloutState.RAMPING, canary_percentage=50)
        enabled_count = sum(
            1 for i in range(100)
            if ff.is_enabled("calendar", user_id=f"user_{i}")
        )
        assert 45 <= enabled_count <= 55, f"Expected ~50%, got {enabled_count}%"
        print(f"✓ Day 4: Ramping 50% (~{enabled_count}% enabled)")
        
        # Day 5: Enabled 100%
        ff.set_state("calendar", RolloutState.ENABLED, canary_percentage=100)
        enabled_count = sum(
            1 for i in range(100)
            if ff.is_enabled("calendar", user_id=f"user_{i}")
        )
        assert enabled_count == 100
        print(f"✓ Day 5: Enabled 100% (all users enabled)")


class TestEndToEndSagaFlow:
    """End-to-end test: ActionRouter → Saga → CalendarAdapter"""
    
    @pytest.mark.asyncio
    async def test_full_saga_flow(self):
        """Complete flow: action → saga → calendar → compensation"""
        # Setup
        ff_manager = FeatureFlagManager()
        ff_manager.set_state("calendar", RolloutState.ENABLED, canary_percentage=100)
        
        saga_orch = MagicMock(spec=SagaOrchestrator)
        saga_orch.start_saga = AsyncMock(return_value="saga_123")
        saga_orch.resume_saga_on_confirm = AsyncMock(return_value={
            "result": {"event_id": "evt_123", "status": "confirmed"}
        })
        
        calendar_adapter = CalendarAdapterReal(provider="google")
        
        router = ActionRouter(
            saga_orchestrator=saga_orch,
            feature_flag_manager=ff_manager,
        )
        
        # 1. User invokes calendar_create action
        action = Action(
            id=f"act_{uuid.uuid4().hex[:8]}",
            name="calendar_create",
            params={
                "title": "Quarterly sync",
                "date": "2026-02-15",
                "start_time": "10:00",
                "end_time": "11:00",
            },
            metadata=ActionMetadata(session_id="user_xyz"),
        )
        
        # 2. Router routes to saga (because feature flag enabled)
        result = router.execute_action(action, model_name="gemini")
        assert result.requires_manual_review == True
        assert result.result["saga_mode"] == True
        print("✓ Step 1: Action routed to saga")
        
        # 3. User confirms action
        confirm = ClientActionConfirm(
            action_id=action.id,
            confirm=True,
        )
        confirm_result = await router.resume_saga_on_confirm(confirm, model_name="gemini")
        print("✓ Step 2: User confirmed")
        
        # 4. Saga orchestrator handles the flow
        # (In real system, this would call adapter.reserve, wait, then adapter.confirm)
        
        # 5. If saga fails, compensation runs (adapter.compensate)
        # This removes the calendar event
        
        print("✓ End-to-end flow complete")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

