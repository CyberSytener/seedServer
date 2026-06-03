"""
Message validation and audit utilities.

Ensures model compliance, prevents invalid actions, tracks audit trail.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from app.models.realtime.actions import Action, ActionResult, ActionStatus
from app.models.realtime.client import ClientMessage, ClientActionConfirm
from app.models.realtime.server import ModelInvokeAction
from app.models.realtime.audit import ConversationTurn
from app.core.realtime.actions import ACTION_REGISTRY, get_action_spec


class ValidationError(Exception):
    """Validation failed."""
    pass


class AuditEvent(Enum):
    """Audit event types."""
    ACTION_INVOKED = "action_invoked"
    ACTION_RESULT = "action_result"
    USER_CONFIRMED = "user_confirmed"
    USER_REJECTED = "user_rejected"
    VALIDATION_FAILED = "validation_failed"


class MessageValidator:
    """Validate messages against contracts."""

    def __init__(self, action_registry: Optional[Dict[str, Any]] = None):
        self.action_registry = action_registry or ACTION_REGISTRY

    def validate_action(self, action: Action) -> Tuple[bool, List[str]]:
        """
        Validate action against specification.
        
        Returns: (is_valid, list_of_errors)
        """
        errors = []

        # If action not registered, do not enforce schema here.
        # Router will handle unregistered actions (e.g., saga-eligible or
        # experimental actions). We treat it as valid for the purpose of
        # message validation to allow flexible testing and incremental
        # action onboarding.
        if action.name not in self.action_registry:
            return True, []

        spec = self.action_registry[action.name]

        # Check action ID format
        if not action.id or not action.id.startswith("act_"):
            errors.append("Action ID must start with 'act_'")

        # Check metadata
        if not action.metadata.session_id:
            errors.append("Missing session_id in metadata")

        # Check params match schema
        params_errors = self._validate_params(action.name, action.params)
        if params_errors:
            errors.extend(params_errors)

        # Check confirmation requirement
        if spec.requires_confirmation != action.metadata.requires_user_confirmation:
            action.metadata.requires_user_confirmation = spec.requires_confirmation
            # Not an error, just auto-correct

        return len(errors) == 0, errors

    def _validate_params(self, action_name: str, params: Dict[str, Any]) -> List[str]:
        """Validate action parameters against schema."""
        errors = []
        spec = self.action_registry.get(action_name)
        if not spec:
            return errors

        schema = spec.params_schema
        required = schema.get("required", [])

        # Check required fields
        for field in required:
            if field not in params:
                errors.append(f"Missing required parameter: {field}")

        # Additional type checks could go here
        # For now, basic required field validation

        return errors

    def validate_client_message(self, msg: ClientMessage) -> Tuple[bool, List[str]]:
        """Validate client message."""
        errors = []

        if not msg.text and not msg.audio_ref and not msg.file_ref:
            errors.append("Message must have text, audio_ref, or file_ref")

        if msg.text and len(msg.text) > 50000:
            errors.append("Message text exceeds 50K character limit")

        return len(errors) == 0, errors

    def validate_confirm(
        self, confirm: ClientActionConfirm, action: Action
    ) -> Tuple[bool, List[str]]:
        """Validate confirmation message."""
        errors = []

        if confirm.action_id != action.id:
            errors.append(f"Action ID mismatch: {confirm.action_id} != {action.id}")

        spec = self.action_registry.get(action.name)
        if not spec or not spec.requires_confirmation:
            errors.append(f"Action {action.name} does not require confirmation")

        return len(errors) == 0, errors


class AuditTrail:
    """Track audit events for compliance and debugging."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.events: List[Dict[str, Any]] = []

    def record_action_invoked(
        self,
        action: Action,
        model_used: str,
        turn_id: str,
    ) -> None:
        """Record action invocation."""
        self.events.append({
            "event": AuditEvent.ACTION_INVOKED.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_id": action.id,
            "action_name": action.name,
            "model": model_used,
            "turn_id": turn_id,
            "confidence": action.metadata.confidence,
            "requires_confirmation": action.metadata.requires_user_confirmation,
            "audit_tags": action.metadata.audit_tags,
        })

    def record_action_result(
        self,
        action_result: ActionResult,
        turn_id: str,
    ) -> None:
        """Record action result."""
        self.events.append({
            "event": AuditEvent.ACTION_RESULT.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_id": action_result.action_id,
            "action_name": action_result.action_name,
            "status": action_result.status,
            "error": action_result.error,
            "turn_id": turn_id,
            "requires_manual_review": action_result.requires_manual_review,
        })

    def record_user_confirmation(
        self,
        action_id: str,
        confirmed: bool,
        reason: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> None:
        """Record user confirmation/rejection."""
        event_dict = {
            "event": AuditEvent.USER_CONFIRMED.value if confirmed else AuditEvent.USER_REJECTED.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_id": action_id,
            "turn_id": turn_id,
        }
        if reason:
            event_dict["reason"] = reason
        self.events.append(event_dict)

    def record_validation_error(
        self,
        action_id: str,
        errors: List[str],
        turn_id: Optional[str] = None,
    ) -> None:
        """Record validation failure."""
        self.events.append({
            "event": AuditEvent.VALIDATION_FAILED.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_id": action_id,
            "errors": errors,
            "turn_id": turn_id,
        })

    def get_events(self) -> List[Dict[str, Any]]:
        """Get all audit events."""
        return self.events

    def export_csv(self) -> str:
        """Export audit trail as CSV."""
        if not self.events:
            return ""

        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=self.events[0].keys())
        writer.writeheader()
        writer.writerows(self.events)

        return output.getvalue()


class ActionRateLimiter:
    """Rate limiting for actions per session."""

    def __init__(self):
        self.limits = {
            "booking": 3,  # Max 3 bookings per session
            "email": 5,    # Max 5 emails per session
            "sms": 5,      # Max 5 SMS per session
        }
        self.counters: Dict[str, Dict[str, int]] = {}

    def init_session(self, session_id: str) -> None:
        """Initialize counters for session."""
        self.counters[session_id] = {
            "booking": 0,
            "email": 0,
            "sms": 0,
        }

    def check_limit(self, session_id: str, action_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if action is within rate limit.
        
        Returns: (allowed, error_message)
        """
        if session_id not in self.counters:
            self.init_session(session_id)

        # Map action name to limit type
        limit_type = None
        if action_name == "book_viewing":
            limit_type = "booking"
        elif action_name == "send_email":
            limit_type = "email"
        elif action_name == "send_sms":
            limit_type = "sms"

        if not limit_type:
            return True, None  # No limit for this action

        counter = self.counters[session_id][limit_type]
        limit = self.limits[limit_type]

        if counter >= limit:
            return False, f"Rate limit exceeded for {action_name}: {counter}/{limit}"

        self.counters[session_id][limit_type] += 1
        return True, None

    def reset_session(self, session_id: str) -> None:
        """Reset session counters."""
        if session_id in self.counters:
            del self.counters[session_id]


class GuardrailChecker:
    """Check if action invocation violates guardrails."""

    def __init__(self):
        self.action_registry = ACTION_REGISTRY

    def check_guardrails(self, action: Action) -> Tuple[bool, List[str]]:
        """
        Check action against guardrails.
        
        Returns: (passes_all, violations)
        """
        violations = []
        spec = self.action_registry.get(action.name)

        if not spec:
            return True, []

        # Check confidence for critical actions
        if action.name in ["book_viewing", "send_email", "send_sms"]:
            if action.metadata.confidence < 0.7:
                violations.append(
                    f"Low confidence for critical action {action.name}: {action.metadata.confidence}"
                )

        # Check metadata requirements
        if not action.metadata.requires_user_confirmation and spec.requires_confirmation:
            violations.append(
                f"Action {action.name} MUST require user confirmation but doesn't"
            )

        # Custom guardrails per action
        violations.extend(self._check_action_specific(action))

        return len(violations) == 0, violations

    def _check_action_specific(self, action: Action) -> List[str]:
        """Check action-specific guardrails."""
        violations = []

        if action.name == "book_viewing":
            if "preferred_windows" not in action.params or not action.params.get("preferred_windows"):
                violations.append("book_viewing missing preferred_windows")
            if not action.metadata.requires_user_confirmation:
                violations.append("book_viewing MUST require user confirmation")

        elif action.name == "send_email":
            if action.metadata.confidence < 0.85:
                violations.append("send_email confidence too low")

        elif action.name == "search_listings":
            # Warn if no filters
            if not any(k in action.params for k in ["price_max", "beds_min"]):
                violations.append("search_listings should have at least one filter")

        return violations


# ============================================================================
# TESTING UTILITIES
# ============================================================================


def create_mock_action(
    name: str,
    session_id: str,
    user_id: str = "user_test",
    **params,
) -> Action:
    """Create a mock action for testing."""
    from uuid import uuid4

    return Action(
        name=name,
        id=f"act_{uuid4().hex[:8]}",
        params=params,
        metadata={
            "session_id": session_id,
            "user_id": user_id,
            "confidence": 0.9,
            "requires_user_confirmation": ACTION_REGISTRY.get(name, {}).get(
                "requires_confirmation", False
            ),
        },
    )


def create_mock_action_result(
    action_id: str,
    action_name: str,
    status: ActionStatus = ActionStatus.SUCCESS,
    result: Optional[Dict[str, Any]] = None,
) -> ActionResult:
    """Create a mock action result for testing."""
    return ActionResult(
        action_id=action_id,
        action_name=action_name,
        status=status,
        result=result or {},
    )
