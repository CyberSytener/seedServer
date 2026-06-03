from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth import AuthContext
from app.core.realtime.sagas import saga_health
from app.core.realtime.sagas.saga_health import saga_health_router


class _FakeDLQ:
    def remove_message(self, saga_id: str) -> bool:
        return True


class _FakeSagaDB:
    async def fetch(self, query, *args):
        return []


class _FakeOrchestrator:
    def __init__(self):
        self.db = _FakeSagaDB()
        self.dlq = _FakeDLQ()
        self.retry_calls = []
        self.replay_calls = []
        self.remove_calls = []
        self.triage_calls = []
        self.purge_calls = []

    async def list_persistent_dlq_messages(self, *, limit: int = 100, saga_id=None):
        return [
            {
                "id": 1,
                "saga_id": saga_id or "saga-1",
                "action_id": "a1",
                "correlation_id": "c1",
                "flow_name": "llm_pipeline",
                "message_type": "permanent_failure",
                "error_message": "err",
                "error_type": "RuntimeError",
                "last_successful_step": "execute",
                "failed_step": "validate",
                "saga_state": {},
                "attempted_compensation_steps": [],
                "created_at": "2020-01-01T00:00:00+00:00",
                "saga_duration_ms": 0.0,
                "retry_count": 0,
                "last_retry_at": None,
                "next_retry_at": None,
                "client_id": None,
                "user_id": None,
                "tags": {},
            }
        ]

    async def retry_persistent_dlq_message(self, saga_id: str, *, retry_delay_seconds: int = 0):
        self.retry_calls.append((saga_id, retry_delay_seconds))
        return {
            "id": 1,
            "saga_id": saga_id,
            "action_id": "a1",
            "correlation_id": "c1",
            "flow_name": "llm_pipeline",
            "message_type": "permanent_failure",
            "error_message": "err",
            "error_type": "RuntimeError",
            "last_successful_step": "execute",
            "failed_step": "validate",
            "saga_state": {},
            "attempted_compensation_steps": [],
            "created_at": "2020-01-01T00:00:00+00:00",
            "saga_duration_ms": 0.0,
            "retry_count": 1,
            "last_retry_at": None,
            "next_retry_at": None,
            "client_id": None,
            "user_id": None,
            "tags": {},
        }

    async def replay_saga_from_dlq(self, saga_id: str):
        self.replay_calls.append(saga_id)
        return {"status": "replayed", "saga_id": saga_id}

    async def remove_persistent_dlq_message(self, saga_id: str):
        self.remove_calls.append(saga_id)
        return 1

    async def list_persistent_dlq_retry_candidates(self, *, limit: int = 100):
        return await self.list_persistent_dlq_messages(limit=limit, saga_id="retry-candidate")

    async def bulk_triage_persistent_dlq_messages(
        self,
        saga_ids,
        *,
        triage_status: str,
        note=None,
        retry_delay_seconds=None,
    ):
        self.triage_calls.append((list(saga_ids), triage_status, note, retry_delay_seconds))
        return len(saga_ids)

    async def purge_persistent_dlq_messages(self, *, older_than_days: int = 30, limit: int = 1000):
        self.purge_calls.append((older_than_days, limit))
        return 2


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(saga_health_router)
    app.state.saga_orchestrator = _FakeOrchestrator()
    app.state.seed = SimpleNamespace(db=object())
    return TestClient(app)


def _deny_admin(_request):
    raise HTTPException(status_code=401, detail="admin key required")


def _allow_admin(_request):
    return AuthContext(user_id="admin-1", is_admin=True)


def test_dlq_list_requires_admin(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _deny_admin,
    )
    client = _build_client()

    resp = client.get("/api/v1/health/saga/dlq")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "admin key required"


def test_dlq_retry_admin_can_replay(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _allow_admin,
    )
    client = _build_client()

    resp = client.post(
        "/api/v1/health/saga/dlq/saga-42/retry",
        json={"retry_delay_seconds": 15, "replay_now": True},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["retry_recorded"] is True
    assert payload["replay_result"]["status"] == "replayed"


def test_dlq_remove_admin_allowed(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _allow_admin,
    )
    client = _build_client()

    resp = client.delete("/api/v1/health/saga/dlq/saga-100")

    assert resp.status_code == 200
    assert resp.json()["removed"] is True


def test_recover_requires_admin(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _deny_admin,
    )
    client = _build_client()

    resp = client.post("/api/v1/health/saga/recover", json={"dry_run": True, "max_age_hours": 24})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "admin key required"


def test_dlq_retry_candidates_requires_admin(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _deny_admin,
    )
    client = _build_client()

    resp = client.get("/api/v1/health/saga/dlq/retry-candidates")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "admin key required"


def test_dlq_triage_admin_allowed(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _allow_admin,
    )
    client = _build_client()

    resp = client.post(
        "/api/v1/health/saga/dlq/triage",
        json={
            "saga_ids": ["s1", "s2"],
            "triage_status": "queued",
            "note": "manual triage",
            "retry_delay_seconds": 60,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["updated_count"] == 2


def test_dlq_purge_admin_allowed(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _allow_admin,
    )
    client = _build_client()

    resp = client.post(
        "/api/v1/health/saga/dlq/purge",
        json={"older_than_days": 21, "limit": 250},
    )

    assert resp.status_code == 200
    assert resp.json()["deleted_count"] == 2


def test_dlq_auto_triage_requires_admin(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _deny_admin,
    )
    client = _build_client()

    resp = client.post("/api/v1/health/saga/dlq/auto-triage", json={"dry_run": True})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "admin key required"


def test_dlq_auto_triage_admin_dry_run(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _allow_admin,
    )
    client = _build_client()

    resp = client.post(
        "/api/v1/health/saga/dlq/auto-triage",
        json={
            "dry_run": True,
            "include_message_types": ["permanent_failure"],
            "retry_count_threshold": 3,
            "min_age_minutes": 0,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["dry_run"] is True
    assert payload["eligible_count"] >= 1
    assert payload["updated_count"] == 0


def test_dlq_auto_triage_admin_updates(monkeypatch):
    monkeypatch.setattr(
        saga_health,
        "require_admin_key",
        _allow_admin,
    )
    client = _build_client()

    resp = client.post(
        "/api/v1/health/saga/dlq/auto-triage",
        json={
            "dry_run": False,
            "include_message_types": ["permanent_failure"],
            "retry_count_threshold": 3,
            "min_age_minutes": 0,
            "retry_delay_seconds": 90,
            "triage_status": "queued_for_retry",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["dry_run"] is False
    assert payload["updated_count"] >= 1
