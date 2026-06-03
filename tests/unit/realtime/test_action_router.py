"""
Tests for Action Router (Execution Engine)

Coverage:
- Executor validation
- Action execution (success, error)
- State transitions (pending → confirmed)
- Idempotency (no duplicate execution)
- Rate limiting
- Confirmation handling
- End-to-end flows
"""

import pytest
import sys
from datetime import datetime, timezone
from typing import Dict, Any

# Import with absolute path for pytest
from app.models.realtime import (
    Action,
    ActionMetadata,
    ClientActionConfirm,
)
from app.core.realtime.executors import (
    SearchListingsExecutor,
    BookViewingExecutor,
    CreateOrUpdateCVExecutor,
    SendEmailExecutor,
    SendSMSExecutor,
    get_executor,
)
from app.core.realtime.action_router import ActionRouter
from app.core.realtime.idempotency import IdempotencyManager


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def router():
    """Fresh Action Router for each test"""
    return ActionRouter()


@pytest.fixture
def session_id():
    """Test session ID"""
    return "test_session_123"


@pytest.fixture
def action_metadata(session_id):
    """Standard action metadata for tests"""
    return ActionMetadata(
        session_id=session_id,
        user_id="user_456",
        timestamp=datetime.now(timezone.utc),
        confidence=0.95,
        requires_user_confirmation=False,
        audit_tags=["test"],
    )


def create_action(
    name: str,
    params: Dict[str, Any],
    metadata: ActionMetadata,
    action_id: str = None
) -> Action:
    """Helper to create action"""
    import uuid
    return Action(
        id=action_id or f"act_{uuid.uuid4().hex[:12]}",
        name=name,
        params=params,
        metadata=metadata,
    )


# ============================================================================
# 1. Executor Tests
# ============================================================================

class TestSearchListingsExecutor:
    """Test search_listings executor"""
    
    def test_validate_missing_location(self, session_id):
        executor = SearchListingsExecutor(session_id)
        is_valid, errors = executor.validate({"price_min": 100000})
        assert not is_valid
        assert "location is required" in errors
    
    def test_validate_invalid_price(self, session_id):
        executor = SearchListingsExecutor(session_id)
        is_valid, errors = executor.validate({
            "location": "Oslo",
            "price_min": 500000,
            "price_max": 200000,  # min > max
        })
        assert not is_valid
        assert "price_min cannot be greater than price_max" in errors
    
    def test_execute_search_success(self, session_id):
        executor = SearchListingsExecutor(session_id)
        result = executor.execute({
            "location": "Oslo",
            "price_min": 0,
            "price_max": 500000,
            "beds_min": 1,
        })
        
        assert result["status"] == "success"
        assert "results" in result["data"]
        assert result["data"]["count"] > 0
        assert "execution_id" in result
    
    def test_execute_search_with_keywords(self, session_id):
        executor = SearchListingsExecutor(session_id)
        result = executor.execute({
            "location": "Oslo",
            "keywords": "renovated",
        })
        
        assert result["status"] == "success"
        # Should find the renovated apartment
        assert result["data"]["count"] >= 1
    
    def test_execute_search_no_results(self, session_id):
        executor = SearchListingsExecutor(session_id)
        result = executor.execute({
            "location": "Oslo",
            "beds_min": 10,  # Unrealistic
        })
        
        assert result["status"] == "success"
        assert result["data"]["count"] == 0


class TestBookViewingExecutor:
    """Test book_viewing executor with state tracking"""
    
    def test_validate_missing_params(self, session_id):
        executor = BookViewingExecutor(session_id)
        is_valid, errors = executor.validate({"listing_id": "lst_001"})
        assert not is_valid
        assert "preferred_windows" in str(errors)
    
    def test_execute_booking_creates_pending(self, session_id):
        executor = BookViewingExecutor(session_id)
        result = executor.execute({
            "listing_id": "lst_001",
            "preferred_windows": ["2026-02-15", "2026-02-16"],
            "user_name": "Test User",
        })
        
        assert result["status"] == "success"
        assert "booking_id" in result["data"]
        assert result["data"]["state"] == "pending"
        assert result["data"]["message"] == "Booking created. Awaiting user confirmation."
    
    def test_confirm_booking_state_transition(self, session_id):
        # First: create booking
        executor = BookViewingExecutor(session_id)
        result = executor.execute({
            "listing_id": "lst_001",
            "preferred_windows": ["2026-02-15"],
        })
        booking_id = result["data"]["booking_id"]
        
        # Second: confirm booking
        success, msg = executor.confirm_booking(booking_id, "2026-02-15 14:00")
        assert success
        assert booking_id in msg
        
        # Third: verify state changed
        booking = executor.get_booking(booking_id)
        assert booking["status"] == "confirmed"
        assert booking["confirmed_time"] == "2026-02-15 14:00"
    
    def test_confirm_booking_not_found(self, session_id):
        executor = BookViewingExecutor(session_id)
        success, msg = executor.confirm_booking("bkg_nonexistent", "2026-02-15")
        assert not success
        assert "not found" in msg


class TestSendEmailExecutor:
    """Test send_email executor"""
    
    def test_validate_missing_recipient(self, session_id):
        executor = SendEmailExecutor(session_id)
        is_valid, errors = executor.validate({
            "subject": "Test",
            "body": "Body",
        })
        assert not is_valid
        assert "to" in str(errors)
    
    def test_validate_invalid_email(self, session_id):
        executor = SendEmailExecutor(session_id)
        is_valid, errors = executor.validate({
            "to": "invalid-email",
            "subject": "Test",
            "body": "Body",
        })
        assert not is_valid
    
    def test_execute_send_email_success(self, session_id):
        executor = SendEmailExecutor(session_id)
        result = executor.execute({
            "to": "user@example.com",
            "subject": "Test Subject",
            "body": "Test body content",
        })
        
        assert result["status"] == "success"
        assert result["data"]["to"] == "user@example.com"
        assert result["data"]["status"] == "sent"


class TestSendSMSExecutor:
    """Test send_sms executor"""
    
    def test_validate_message_too_long(self, session_id):
        executor = SendSMSExecutor(session_id)
        long_msg = "x" * 161  # Over SMS limit
        is_valid, errors = executor.validate({
            "phone": "+4798765432",
            "message": long_msg,
        })
        assert not is_valid
        assert "160 chars" in str(errors)
    
    def test_execute_send_sms_success(self, session_id):
        executor = SendSMSExecutor(session_id)
        result = executor.execute({
            "phone": "+4798765432",
            "message": "Hello, this is a test SMS!",
        })
        
        assert result["status"] == "success"
        assert result["data"]["phone"] == "+4798765432"
        assert result["data"]["status"] == "sent"


# ============================================================================
# 2. Idempotency Tests
# ============================================================================

class TestIdempotency:
    """Test idempotency manager"""
    
    def test_first_execution_runs(self):
        manager = IdempotencyManager()
        call_count = 0
        
        def slow_operation():
            nonlocal call_count
            call_count += 1
            return {"result": "done"}
        
        result1 = manager.get_or_execute("act_123", slow_operation)
        assert result1["status"] == "executed"
        assert call_count == 1
    
    def test_retry_returns_cached(self):
        manager = IdempotencyManager()
        call_count = 0
        
        def slow_operation():
            nonlocal call_count
            call_count += 1
            return {"result": f"call_{call_count}"}
        
        # First call
        result1 = manager.get_or_execute("act_123", slow_operation)
        first_data = result1["data"]
        
        # Retry with same ID
        result2 = manager.get_or_execute("act_123", slow_operation)
        
        assert result2["status"] == "cached"
        assert result2["data"] == first_data
        assert call_count == 1  # Still only 1 execution
    
    def test_force_reexecute_ignores_cache(self):
        manager = IdempotencyManager()
        call_count = 0
        
        def operation():
            nonlocal call_count
            call_count += 1
            return {"count": call_count}
        
        manager.get_or_execute("act_123", operation)
        manager.get_or_execute("act_123", operation, force_reexecute=True)
        
        assert call_count == 2
    
    def test_invalidate_clears_cache(self):
        manager = IdempotencyManager()
        call_count = 0
        
        def operation():
            nonlocal call_count
            call_count += 1
            return {"count": call_count}
        
        manager.get_or_execute("act_123", operation)
        assert manager.invalidate("act_123")
        result = manager.get_or_execute("act_123", operation)
        
        assert call_count == 2


# ============================================================================
# 3. Action Router Tests
# ============================================================================

class TestActionRouter:
    """Test main Action Router"""
    
    def test_execute_no_confirmation_needed(self, router, action_metadata):
        """Search doesn't need confirmation"""
        action = create_action(
            "search_listings",
            {"location": "Oslo", "beds_min": 1},  # Add required filter
            action_metadata,
        )
        
        result = router.execute_action(action)
        
        assert result.status.value == "success"
        assert result.result is not None
        # Result has nested structure from executor
        assert result.result.get("status") == "success"
    
    def test_execute_requires_confirmation(self, router, action_metadata):
        """Booking requires user confirmation"""
        # Create metadata with requires_confirmation=True for booking
        booking_metadata = ActionMetadata(
            session_id=action_metadata.session_id,
            user_id=action_metadata.user_id,
            timestamp=action_metadata.timestamp,
            confidence=0.95,
            requires_user_confirmation=True,  # book_viewing requires confirmation
            audit_tags=["test"],
        )
        
        action = create_action(
            "book_viewing",
            {
                "listing_id": "lst_001",
                "user_id": "user_456",
                "preferred_windows": ["2026-02-15"],
            },
            booking_metadata,
        )
        
        result = router.execute_action(action)
        
        # Should return REQUIRES_MANUAL_REVIEW
        assert result.status.value == "requires_manual_review"
        assert "message" in result.result
        assert "requires user confirmation" in result.result["message"]
        assert router.has_pending_confirmation(action.id)
    
    def test_confirm_action_success(self, router, action_metadata):
        """User confirms booking"""
        # First: execute (creates pending)
        booking_metadata = ActionMetadata(
            session_id=action_metadata.session_id,
            user_id=action_metadata.user_id,
            timestamp=action_metadata.timestamp,
            confidence=0.95,
            requires_user_confirmation=True,
            audit_tags=["test"],
        )
        action = create_action(
            "book_viewing",
            {
                "listing_id": "lst_001",
                "user_id": "user_456",
                "preferred_windows": ["2026-02-15"],
            },
            booking_metadata,
        )
        
        result1 = router.execute_action(action)
        action_id = action.id
        
        # Second: user confirms
        confirm = ClientActionConfirm(
            action_id=action_id,
            confirm=True,
        )
        
        result2 = router.confirm_action(confirm)
        
        assert result2.status.value == "success"
        assert not router.has_pending_confirmation(action_id)
    
    def test_confirm_action_rejection(self, router, action_metadata):
        """User rejects booking"""
        # First: execute (creates pending)
        booking_metadata = ActionMetadata(
            session_id=action_metadata.session_id,
            user_id=action_metadata.user_id,
            timestamp=action_metadata.timestamp,
            confidence=0.95,
            requires_user_confirmation=True,
            audit_tags=["test"],
        )
        action = create_action(
            "book_viewing",
            {
                "listing_id": "lst_001",
                "user_id": "user_456",
                "preferred_windows": ["2026-02-15"],
            },
            booking_metadata,
        )
        
        router.execute_action(action)
        action_id = action.id
        
        # Second: user rejects
        confirm = ClientActionConfirm(
            action_id=action_id,
            confirm=False,
            reason="Location not suitable",
        )
        
        result = router.confirm_action(confirm)
        
        assert result.status.value == "failed"
        assert result.result is None or result.result.get("rejected") == True
        assert not router.has_pending_confirmation(action_id)
    
    def test_validation_error(self, router, action_metadata):
        """Invalid action parameters"""
        action = create_action(
            "book_viewing",
            {
                "listing_id": "lst_001",
                # Missing preferred_windows
            },
            action_metadata,
        )
        
        result = router.execute_action(action)
        
        assert result.status.value == "failed"
        assert "validation" in result.error.lower() or "parameter" in result.error.lower()
    
    def test_idempotency_no_retry_execution(self, router, action_metadata):
        """Same action_id doesn't execute twice"""
        action = create_action(
            "search_listings",
            {"location": "Oslo", "beds_min": 1},
            action_metadata,
        )
        
        # First execution
        result1 = router.execute_action(action)
        
        # Retry with same action_id
        result2 = router.execute_action(action)
        
        # Should return same result without re-executing
        assert result1.result == result2.result
    
    def test_rate_limiting(self, router, session_id, action_metadata):
        """Rate limiting prevents too many bookings"""
        # Create 4 booking attempts (limit is 3)
        for i in range(4):
            action = create_action(
                "book_viewing",
                {
                    "listing_id": f"lst_{i:03d}",
                    "user_id": "user_456",
                    "preferred_windows": ["2026-02-15"],
                },
                ActionMetadata(
                    session_id=session_id,
                    user_id="user_456",
                    timestamp=datetime.now(timezone.utc),
                    confidence=0.95,
                    requires_user_confirmation=True,  # book_viewing MUST require confirmation
                    audit_tags=["test"],
                ),
            )
            result = router.execute_action(action)
            
            if i < 3:
                # First 3 should require confirmation
                assert result.status.value == "requires_manual_review"
            else:
                # 4th should be rate limited
                assert result.status.value == "failed"
                assert "rate" in result.error.lower()


# ============================================================================
# 4. End-to-End Flows
# ============================================================================

class TestE2EFlows:
    """Complete workflows"""
    
    def test_search_then_book(self, router, action_metadata):
        """User searches properties then books viewing"""
        session_id = action_metadata.session_id
        
        # 1. Search
        search_action = create_action(
            "search_listings",
            {"location": "Oslo", "beds_min": 1},
            ActionMetadata(
                session_id=session_id,
                user_id="user_456",
                timestamp=datetime.now(timezone.utc),
                confidence=0.95,
                requires_user_confirmation=False,
                audit_tags=["test"],
            ),
        )
        search_result = router.execute_action(search_action)
        assert search_result.status.value == "success"

        # 2. Get details
        first_listing = search_result.result["data"]["results"][0]
        details_action = create_action(
            "get_listing_details",
            {"listing_id": first_listing["id"]},
            ActionMetadata(
                session_id=session_id,
                user_id="user_456",
                timestamp=datetime.now(timezone.utc),
                confidence=0.95,
                requires_user_confirmation=False,
                audit_tags=["test"],
            ),
        )
        details_result = router.execute_action(details_action)
        assert details_result.status.value == "success"
        
        # 3. Book viewing
        book_action = create_action(
            "book_viewing",
            {
                "listing_id": first_listing["id"],
                "user_id": "user_456",
                "preferred_windows": ["2026-02-15", "2026-02-16"],
            },
            ActionMetadata(
                session_id=session_id,
                user_id="user_456",
                timestamp=datetime.now(timezone.utc),
                confidence=0.95,
                requires_user_confirmation=True,  # book_viewing requires confirmation
                audit_tags=["test"],
            ),
        )
        book_result = router.execute_action(book_action)
        assert book_result.status.value == "requires_manual_review"
        
        # 4. User confirms
        # The action_id for confirmation is the original action's id
        confirm = ClientActionConfirm(
            action_id=book_action.id,
            confirm=True,
        )
        confirm_result = router.confirm_action(confirm)
        assert confirm_result.status.value == "success"
    
    def test_email_confirmation_flow(self, router, action_metadata):
        """Send email requires confirmation"""
        # 1. Model proposes email
        email_metadata = ActionMetadata(
            session_id=action_metadata.session_id,
            user_id=action_metadata.user_id,
            timestamp=action_metadata.timestamp,
            confidence=0.95,
            requires_user_confirmation=True,  # send_email requires confirmation
            audit_tags=["test"],
        )
        
        email_action = create_action(
            "send_email",
            {
                "to": "user@example.com",
                "subject": "Your CV",
                "body": "Here is your CV...",
            },
            email_metadata,
        )
        
        result = router.execute_action(email_action)
        assert result.status.value == "requires_manual_review"
        
        # 2. User confirms
        confirm = ClientActionConfirm(
            action_id=email_action.id,
            confirm=True,
        )
        confirm_result = router.confirm_action(confirm)
        assert confirm_result.status.value == "success"
        # Email result is nested: {status, data, execution_id}
        assert confirm_result.result and "email_id" in confirm_result.result.get("data", {})


# ============================================================================
# Run tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

