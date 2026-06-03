import pytest
from datetime import datetime, timezone

from app.core.realtime.action_router import ActionRouter
from app.models.realtime import Action, ActionMetadata, ActionStatus
from app.core.realtime.executors import CreateOrUpdateCVExecutor


def _now_meta(session_id: str = "sess-cv"):
    return ActionMetadata(
        session_id=session_id,
        user_id="user-123",
        timestamp=datetime.now(timezone.utc),
        requires_user_confirmation=False,
    )


def create_action(name: str, params: dict, metadata: ActionMetadata, action_id: str = None):
    import uuid
    return Action(
        id=action_id or f"act_{uuid.uuid4().hex[:12]}",
        name=name,
        params=params,
        metadata=metadata,
    )


def test_end_to_end_create_cv_via_router():
    """Simulate user asking the model to 'Write my CV' and validate full cycle."""
    router = ActionRouter()

    meta = _now_meta("sess-cv-1")
    params = {
        "user_id": "user-123",
        "cv_payload": {
            "personal": {"name": "Alice Example"},
            "summary": "Experienced backend developer",
            "experience": ["Company A - Backend Engineer (2020-2023)"],
        },
        # Executor expects flat shape as well (legacy), include both forms to simulate model output
        "full_name": "Alice Example",
        "sections": {
            "summary": "Experienced backend developer",
            "experience": ["Company A - Backend Engineer (2020-2023)"]
        },
        "format": ["pdf"],
    }

    action = create_action("create_or_update_cv", params, meta)

    res = router.execute_action(action)

    assert res.status == ActionStatus.SUCCESS
    assert res.result is not None
    data = res.result
    # The idempotency layer and executor return a nested structure:
    # res.result may be either the executor 'data' dict or the full execution dict
    exec_data = data.get("data") if "data" in data else data

    assert exec_data.get("cv_id") is not None
    assert exec_data.get("preview") is not None
    assert exec_data.get("download_url") is not None

    cv_id = exec_data["cv_id"]

    # Stored in executor storage
    stored = CreateOrUpdateCVExecutor.USER_CVS.get(cv_id)
    assert stored is not None
    assert stored.get("full_name") == "Alice Example"
    assert "/api/cv/" in exec_data["download_url"]
    assert cv_id in exec_data["download_url"]


def test_create_cv_missing_name_fails():
    router = ActionRouter()
    meta = _now_meta("sess-cv-2")

    params = {
        "user_id": "user-999",
        "cv_payload": {"personal": {}, "summary": "No name provided"},
        # missing full_name on purpose - should fail executor validation
        "sections": {"summary": "No name provided"},
        "format": ["pdf"],
    }

    action = create_action("create_or_update_cv", params, meta)
    res = router.execute_action(action)

    assert res.status == ActionStatus.FAILED
    assert res.error and "full_name" in res.error


def test_create_then_update_creates_new_cv_entry():
    router = ActionRouter()
    meta = _now_meta("sess-cv-3")

    params1 = {
        "user_id": "user-555",
        "cv_payload": {"personal": {"name": "Bob One"}, "summary": "First draft"},
        "full_name": "Bob One",
        "sections": {"summary": "First draft"},
        "format": ["pdf"],
    }
    action1 = create_action("create_or_update_cv", params1, meta)
    res1 = router.execute_action(action1)
    assert res1.status == ActionStatus.SUCCESS
    exec1 = res1.result.get("data") if "data" in res1.result else res1.result
    id1 = exec1["cv_id"]

    params2 = {
        "user_id": "user-555",
        "cv_payload": {"personal": {"name": "Bob One"}, "summary": "Updated draft - more details"},
        "full_name": "Bob One",
        "sections": {"summary": "Updated draft - more details"},
        "format": ["pdf"],
    }
    action2 = create_action("create_or_update_cv", params2, meta)
    res2 = router.execute_action(action2)
    assert res2.status == ActionStatus.SUCCESS
    exec2 = res2.result.get("data") if "data" in res2.result else res2.result
    id2 = exec2["cv_id"]

    assert id1 != id2

    # Both should be present in storage
    assert id1 in CreateOrUpdateCVExecutor.USER_CVS
    assert id2 in CreateOrUpdateCVExecutor.USER_CVS

