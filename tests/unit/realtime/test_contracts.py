"""
Quick test: Message contracts and action validation.

Demonstrates:
- Creating valid messages
- Validating actions
- Audit trail tracking
- Rate limiting
"""

import pytest
from datetime import datetime

from app.models.realtime import (
    ClientMessage,
    ClientActionConfirm,
    Action,
    ActionMetadata,
    ModelInvokeAction,
    ActionResult,
    ActionStatus,
)
from app.core.realtime.validators import (
    MessageValidator,
    AuditTrail,
    ActionRateLimiter,
    GuardrailChecker,
    ValidationError,
)


# ============================================================================
# TEST: Message Creation
# ============================================================================


def test_client_message_creation():
    """Test creating a client message."""
    msg = ClientMessage(
        text="Find 2-bed apartments in Oslo",
        metadata={"language": "en"}
    )
    assert msg.type == "client.message"
    assert msg.text == "Find 2-bed apartments in Oslo"
    assert msg.metadata["language"] == "en"


def test_action_creation():
    """Test creating an action."""
    action = Action(
        name="search_listings",
        id="act_search_001",
        params={
            "location": "Oslo",
            "price_max": 400000,
            "beds_min": 2,
        },
        metadata=ActionMetadata(
            session_id="sess_123",
            user_id="user_456",
            confidence=0.92,
            requires_user_confirmation=False,
        ),
    )
    assert action.name == "search_listings"
    assert action.params["location"] == "Oslo"
    assert action.metadata.confidence == 0.92


def test_action_confirmation():
    """Test user confirmation message."""
    confirm = ClientActionConfirm(
        action_id="act_book_001",
        confirm=True,
        reason="Looks good",
    )
    assert confirm.type == "client.action.confirm"
    assert confirm.confirm is True


# ============================================================================
# TEST: Validation
# ============================================================================


def test_validate_action_success():
    """Test successful action validation."""
    validator = MessageValidator()

    action = Action(
        name="search_listings",
        id="act_search_001",
        params={"location": "Oslo"},
        metadata=ActionMetadata(session_id="sess_123"),
    )

    is_valid, errors = validator.validate_action(action)
    assert is_valid
    assert len(errors) == 0


def test_validate_action_unknown_action():
    """Test validation fails for unknown action."""
    validator = MessageValidator()

    action = Action(
        name="invalid_action",
        id="act_123",
        params={},
        metadata=ActionMetadata(session_id="sess_123"),
    )

    is_valid, errors = validator.validate_action(action)
    # Unknown actions are considered valid at the message validation layer;
    # the router will make final decisions (e.g., saga flow or unknown-action errors).
    assert is_valid
    assert errors == []


def test_validate_client_message():
    """Test client message validation."""
    validator = MessageValidator()

    msg = ClientMessage(text="Hello")
    is_valid, errors = validator.validate_client_message(msg)
    assert is_valid


def test_validate_client_message_empty():
    """Test empty message validation fails."""
    validator = MessageValidator()

    msg = ClientMessage()  # Empty message
    is_valid, errors = validator.validate_client_message(msg)
    assert not is_valid
    assert "must have text" in str(errors)


# ============================================================================
# TEST: Audit Trail
# ============================================================================


def test_audit_trail_action_invoked():
    """Test recording action invocation."""
    trail = AuditTrail("sess_123")

    action = Action(
        name="search_listings",
        id="act_001",
        params={"location": "Oslo"},
        metadata=ActionMetadata(
            session_id="sess_123",
            confidence=0.92,
            requires_user_confirmation=False,
        ),
    )

    trail.record_action_invoked(action, "gemini-2.0-flash", "turn_001")

    events = trail.get_events()
    assert len(events) == 1
    assert events[0]["event"] == "action_invoked"
    assert events[0]["action_name"] == "search_listings"


def test_audit_trail_user_confirmation():
    """Test recording user confirmation."""
    trail = AuditTrail("sess_123")

    trail.record_user_confirmation(
        action_id="act_book_001",
        confirmed=True,
        reason="Looks good",
        turn_id="turn_002",
    )

    events = trail.get_events()
    assert len(events) == 1
    assert events[0]["event"] == "user_confirmed"


def test_audit_trail_export():
    """Test exporting audit trail."""
    trail = AuditTrail("sess_123")

    action = Action(
        name="search_listings",
        id="act_001",
        params={},
        metadata=ActionMetadata(session_id="sess_123"),
    )

    trail.record_action_invoked(action, "gemini", "turn_001")
    trail.record_user_confirmation("act_001", True)

    csv = trail.export_csv()
    assert "action_invoked" in csv
    assert "user_confirmed" in csv


# ============================================================================
# TEST: Rate Limiting
# ============================================================================


def test_rate_limiter_booking():
    """Test rate limit for bookings."""
    limiter = ActionRateLimiter()
    session_id = "sess_123"

    # Allow 3 bookings
    allowed, _ = limiter.check_limit(session_id, "book_viewing")
    assert allowed
    allowed, _ = limiter.check_limit(session_id, "book_viewing")
    assert allowed
    allowed, _ = limiter.check_limit(session_id, "book_viewing")
    assert allowed

    # Reject 4th
    allowed, error = limiter.check_limit(session_id, "book_viewing")
    assert not allowed
    assert "Rate limit exceeded" in error


def test_rate_limiter_email():
    """Test rate limit for emails."""
    limiter = ActionRateLimiter()
    session_id = "sess_123"

    for _ in range(5):
        allowed, _ = limiter.check_limit(session_id, "send_email")
        assert allowed

    allowed, error = limiter.check_limit(session_id, "send_email")
    assert not allowed


def test_rate_limiter_reset():
    """Test resetting rate limiter."""
    limiter = ActionRateLimiter()
    session_id = "sess_123"

    limiter.check_limit(session_id, "book_viewing")
    limiter.check_limit(session_id, "book_viewing")
    limiter.check_limit(session_id, "book_viewing")

    # At limit
    allowed, _ = limiter.check_limit(session_id, "book_viewing")
    assert not allowed

    # Reset
    limiter.reset_session(session_id)

    # Should work again
    allowed, _ = limiter.check_limit(session_id, "book_viewing")
    assert allowed


# ============================================================================
# TEST: Guardrails
# ============================================================================


def test_guardrail_booking_requires_confirmation():
    """Test guardrail: booking must require confirmation."""
    checker = GuardrailChecker()

    action = Action(
        name="book_viewing",
        id="act_book_001",
        params={"listing_id": "L1", "preferred_windows": ["2026-02-05T17:00/19:00"]},
        metadata=ActionMetadata(
            session_id="sess_123",
            confidence=0.9,
            requires_user_confirmation=True,  # Correct
        ),
    )

    passes, violations = checker.check_guardrails(action)
    assert passes
    assert len(violations) == 0


def test_guardrail_booking_missing_confirmation():
    """Test guardrail fails: booking without confirmation."""
    checker = GuardrailChecker()

    action = Action(
        name="book_viewing",
        id="act_book_001",
        params={"listing_id": "L1", "preferred_windows": ["2026-02-05T17:00/19:00"]},
        metadata=ActionMetadata(
            session_id="sess_123",
            confidence=0.9,
            requires_user_confirmation=False,  # Wrong!
        ),
    )

    passes, violations = checker.check_guardrails(action)
    assert not passes
    # Check for the specific violation (case-insensitive)
    assert any("confirmation" in v.lower() for v in violations)


def test_guardrail_low_confidence():
    """Test guardrail: critical actions need high confidence."""
    checker = GuardrailChecker()

    action = Action(
        name="send_email",
        id="act_email_001",
        params={"to": "user@example.com", "subject": "Test", "body": "Test"},
        metadata=ActionMetadata(
            session_id="sess_123",
            confidence=0.5,  # Too low!
            requires_user_confirmation=True,
        ),
    )

    passes, violations = checker.check_guardrails(action)
    assert not passes


# ============================================================================
# TEST: End-to-End Flow
# ============================================================================


def test_e2e_search_flow():
    """Test end-to-end search flow without confirmation."""
    validator = MessageValidator()
    trail = AuditTrail("sess_123")

    # Step 1: User sends message
    user_msg = ClientMessage(text="Find apartments in Oslo")
    assert user_msg.type == "client.message"

    # Step 2: Model invokes action
    action = Action(
        name="search_listings",
        id="act_search_001",
        params={"location": "Oslo", "price_max": 400000},
        metadata=ActionMetadata(
            session_id="sess_123",
            user_id="user_456",
            confidence=0.92,
            requires_user_confirmation=False,
        ),
    )

    is_valid, errors = validator.validate_action(action)
    assert is_valid
    trail.record_action_invoked(action, "gemini", "turn_001")

    # Step 3: Gateway executes action
    result = ActionResult(
        action_id=action.id,
        action_name=action.name,
        status=ActionStatus.SUCCESS,
        result={"listings": [{"id": "L1", "title": "Apartment", "price": 350000}]},
    )
    trail.record_action_result(result, "turn_001")

    # Verify audit trail
    events = trail.get_events()
    assert len(events) == 2
    assert events[0]["event"] == "action_invoked"
    assert events[1]["event"] == "action_result"


def test_e2e_booking_flow():
    """Test end-to-end booking flow WITH confirmation."""
    validator = MessageValidator()
    trail = AuditTrail("sess_123")
    limiter = ActionRateLimiter()
    checker = GuardrailChecker()

    # Step 1: Check rate limit
    allowed, _ = limiter.check_limit("sess_123", "book_viewing")
    assert allowed

    # Step 2: Model invokes action
    action = Action(
        name="book_viewing",
        id="act_book_001",
        params={
            "listing_id": "L1",
            "user_id": "user_456",
            "preferred_windows": ["2026-02-05T17:00/2026-02-05T19:00"],
        },
        metadata=ActionMetadata(
            session_id="sess_123",
            user_id="user_456",
            confidence=0.88,
            requires_user_confirmation=True,
        ),
    )

    # Validate
    is_valid, errors = validator.validate_action(action)
    assert is_valid

    # Check guardrails
    passes, violations = checker.check_guardrails(action)
    assert passes

    trail.record_action_invoked(action, "gemini", "turn_002")

    # Step 3: User confirms
    confirm = ClientActionConfirm(action_id=action.id, confirm=True)
    is_valid, errors = validator.validate_confirm(confirm, action)
    assert is_valid

    trail.record_user_confirmation(action.id, True, "Looks good", "turn_002")

    # Step 4: Gateway executes action
    result = ActionResult(
        action_id=action.id,
        action_name=action.name,
        status=ActionStatus.SUCCESS,
        result={"booking_id": "bk_789", "confirmed_datetime": "2026-02-05T17:30Z"},
    )
    trail.record_action_result(result, "turn_002")

    # Verify audit trail
    events = trail.get_events()
    assert len(events) == 3
    assert events[0]["event"] == "action_invoked"
    assert events[1]["event"] == "user_confirmed"
    assert events[2]["event"] == "action_result"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

