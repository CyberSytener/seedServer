import pytest
from datetime import datetime, timezone

from app.core.realtime.validators import MessageValidator
from app.models.realtime import Action, ActionMetadata, ClientActionConfirm
from app.core.realtime.actions import ACTION_REGISTRY, ActionSpec


def test_validate_unknown_action_allowed():
    validator = MessageValidator()
    action = Action(
        id="act_x",
        name="unknown_action_abc",
        params={},
        metadata=ActionMetadata(session_id="s1"),
    )

    ok, errors = validator.validate_action(action)
    assert ok is True
    assert errors == []


def test_validate_missing_required_param():
    validator = MessageValidator()
    # search_listings requires 'location' in params per spec
    action = Action(
        id="act_s1",
        name="search_listings",
        params={"price_min": 100000},
        metadata=ActionMetadata(session_id="s2"),
    )

    ok, errors = validator.validate_action(action)
    assert not ok
    assert any("Missing required parameter: location" in e for e in errors)


def test_validate_confirm_checks_spec():
    validator = MessageValidator()

    action = Action(
        id="act_c1",
        name="send_email",
        params={"to": "u@x", "subject": "Hi", "body": "hey"},
        metadata=ActionMetadata(session_id="s3"),
    )

    confirm = ClientActionConfirm(action_id="act_c1", confirm=True)
    ok, errors = validator.validate_confirm(confirm, action)
    assert ok is True

    # For an action that does not require confirmation
    # create a temporary spec where requires_confirmation=False
    ACTION_REGISTRY["temp_action"] = ActionSpec(
        name="temp_action",
        description="Temp",
        category="misc",
        requires_confirmation=False,
        external_api=False,
        timeout_seconds=5,
        params_schema={},
    )

    action2 = Action(
        id="act_c2",
        name="temp_action",
        params={},
        metadata=ActionMetadata(session_id="s4"),
    )
    confirm2 = ClientActionConfirm(action_id="act_c2", confirm=True)
    ok2, errors2 = validator.validate_confirm(confirm2, action2)
    assert not ok2
    assert any("does not require confirmation" in e for e in errors2)

    # Cleanup
    del ACTION_REGISTRY["temp_action"]

