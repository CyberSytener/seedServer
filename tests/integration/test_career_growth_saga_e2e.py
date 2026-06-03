import asyncio
import json
import uuid
import pytest

from app.core.realtime.sagas.orchestrator import SagaOrchestrator, SagaState, DistributedLock
from app.infrastructure.realtime.adapters import TransientAdapterError, PermanentAdapterError


class FakeDB:
    def __init__(self):
        self.sagas = {}
        self.saga_idempotency = {}
        self.state_history = {}
        self._lock = asyncio.Lock()
        self._db_locks = set()

    async def execute(self, query, *args):
        if "INSERT INTO sagas" in query:
            saga_id = args[0]
            async with self._lock:
                if saga_id in self.sagas:
                    return "INSERT 0 0"
                steps_raw = args[7]
                steps = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
                self.sagas[saga_id] = {
                    "saga_id": saga_id,
                    "action_id": args[1],
                    "user_id": args[2],
                    "saga_type": args[3],
                    "saga_version": args[4],
                    "state": args[5],
                    "payload": args[6],
                    "steps": steps,
                    "result": None,
                    "correlation_id": args[8],
                }
                self.state_history[saga_id] = [args[5]]
                return "INSERT 0 1"
        if "INSERT INTO saga_idempotency" in query:
            key, result = args[0], args[1]
            self.saga_idempotency[key] = result
            return "INSERT 0 1"
        if "UPDATE sagas" in query and "SET state = $1, updated_at" in query:
            state, saga_id, expected = args[0], args[1], args[2]
            saga = self.sagas.get(saga_id)
            if saga and saga.get("state") == expected:
                saga["state"] = state
                self.state_history.setdefault(saga_id, []).append(state)
                return "UPDATE 1"
            return "UPDATE 0"
        if "UPDATE sagas" in query and "SET state = $1, steps = $2, result = $3" in query:
            state, steps_raw, result_raw, saga_id = args[0], args[1], args[2], args[3]
            saga = self.sagas.get(saga_id)
            if saga:
                steps = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
                result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                saga.update({"state": state, "steps": steps, "result": result})
                self.state_history.setdefault(saga_id, []).append(state)
            return "UPDATE 1"
        if "UPDATE sagas" in query and "SET state = $1, result = $2" in query:
            state, result_raw, saga_id = args[0], args[1], args[2]
            saga = self.sagas.get(saga_id)
            if saga:
                result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                saga.update({"state": state, "result": result})
                self.state_history.setdefault(saga_id, []).append(state)
            return "UPDATE 1"
        if "SELECT pg_advisory_unlock" in query:
            lock_id = args[0]
            self._db_locks.discard(lock_id)
            return "OK"
        return "OK"

    async def fetchrow(self, query, *args):
        if "SELECT * FROM sagas" in query:
            saga_id = args[0]
            return self.sagas.get(saga_id)
        if "FROM saga_idempotency" in query:
            key = args[0]
            if key in self.saga_idempotency:
                return {"result": self.saga_idempotency[key]}
            return None
        return None

    async def fetch(self, query, *args):
        if "FROM compensation_history" in query:
            return []
        return []

    async def fetchval(self, query, *args):
        if "SELECT pg_try_advisory_lock" in query:
            lock_id = args[0]
            if lock_id in self._db_locks:
                return False
            self._db_locks.add(lock_id)
            return True
        return None


class FakeCVAdapter:
    def __init__(self):
        self.calls = 0
        self.trace_contexts = []

    async def generate_cv(self, payload, trace_context=None, trace_id=None, correlation_id=None):
        self.calls += 1
        self.trace_contexts.append(trace_context or {})
        return {"document": "CV_DOC", "keywords": ["Senior AI Engineer"]}


class FakeJobAdapter:
    def __init__(self, fail_times=0):
        self.calls = 0
        self.fail_times = fail_times
        self.trace_contexts = []
        self.last_vacancies = []

    async def search_jobs(self, payload, trace_context=None, trace_id=None, correlation_id=None):
        self.calls += 1
        self.trace_contexts.append(trace_context or {})
        if self.calls <= self.fail_times:
            raise TransientAdapterError("timeout")
        vacancies = [
            {
                "title": "Senior AI Engineer",
                "company": "London AI Labs",
                "location": "London",
                "required_skills": ["python", "ml", "llm"],
                "contact_email": "hr@londonai.example",
            }
        ]
        self.last_vacancies = vacancies
        return {
            "vacancies": [
                *vacancies
            ]
        }


class FakeEducationAdapter:
    def __init__(self):
        self.received_vacancies = None
        self.trace_contexts = []

    async def generate_lessons(self, payload, trace_context=None, trace_id=None, correlation_id=None):
        self.received_vacancies = payload.get("vacancies")
        self.trace_contexts.append(trace_context or {})
        return {
            "lessons": [
                {"title": "ML Fundamentals", "summary": "Intro", "read_more": "url1"},
                {"title": "LLM Systems", "summary": "Intro", "read_more": "url2"},
                {"title": "MLOps", "summary": "Intro", "read_more": "url3"},
            ]
        }


class FakeOutreachAdapter:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0
        self.sent_payloads = []
        self.trace_contexts = []

    async def send_application(self, payload, trace_context=None, trace_id=None, correlation_id=None):
        self.calls += 1
        self.sent_payloads.append(payload)
        self.trace_contexts.append(trace_context or {})
        if self.fail:
            raise PermanentAdapterError("smtp down")
        return {"status": "sent", "attachment": payload.get("attachment")}


def build_orchestrator(adapters):
    orchestrator = SagaOrchestrator(
        db_connection_string="postgresql://test",
        adapter_registry=adapters,
        async_mode=True,
        redis_url=None,
    )
    fake_db = FakeDB()
    orchestrator.db = fake_db
    orchestrator.lock_manager = DistributedLock(
        None,
        fake_db,
        db_url="postgresql://test",
        async_mode=True,
        fail_open=False,
    )
    return orchestrator, fake_db


@pytest.mark.asyncio
async def test_career_growth_e2e_success():
    cv_adapter = FakeCVAdapter()
    job_adapter = FakeJobAdapter()
    edu_adapter = FakeEducationAdapter()
    outreach_adapter = FakeOutreachAdapter()

    orchestrator, fake_db = build_orchestrator(
        {
            "cv": cv_adapter,
            "job_search": job_adapter,
            "career_education": edu_adapter,
            "email_outreach": outreach_adapter,
        }
    )

    action_id = f"action-{uuid.uuid4()}"
    payload = {
        "user_id": "user-1",
        "user_persona": {"work_history": ["Junior Python Developer"]},
        "current_skills": ["python", "sql"],
        "target_role": "Senior AI Engineer",
        "location": "London",
    }

    saga_id = await orchestrator.start_saga(
        action_id=action_id,
        saga_type="career_growth_flow",
        payload=payload,
        correlation_id="corr-1",
        trace_id="trace-1",
    )

    saga = fake_db.sagas[saga_id]
    steps = saga.get("steps") or []
    assert saga["state"] == SagaState.SUCCEEDED.value

    # Data consistency: CV attached to outreach
    assert outreach_adapter.sent_payloads
    for sent in outreach_adapter.sent_payloads:
        assert sent.get("attachment") == {"document": "CV_DOC", "keywords": ["Senior AI Engineer"]}

    # Context persistence: education got vacancies from job discovery
    assert edu_adapter.received_vacancies is not None
    assert edu_adapter.received_vacancies == job_adapter.last_vacancies
    assert len(edu_adapter.received_vacancies) >= 1

    # Trace propagation
    for ctx in cv_adapter.trace_contexts + job_adapter.trace_contexts + edu_adapter.trace_contexts + outreach_adapter.trace_contexts:
        assert ctx.get("correlation_id") == "corr-1"
        assert ctx.get("trace_id") == "trace-1"

    # Step meta duration and status
    for step in steps:
        if step.get("status") == "succeeded":
            assert "duration_ms" in step.get("meta", {})

    # State transitions
    history = fake_db.state_history[saga_id]
    assert SagaState.PENDING.value in history
    assert SagaState.IN_PROGRESS.value in history
    assert SagaState.SUCCEEDED.value in history


@pytest.mark.asyncio
async def test_job_discovery_timeout_retries():
    cv_adapter = FakeCVAdapter()
    job_adapter = FakeJobAdapter(fail_times=2)
    edu_adapter = FakeEducationAdapter()
    outreach_adapter = FakeOutreachAdapter()

    orchestrator, _ = build_orchestrator(
        {
            "cv": cv_adapter,
            "job_search": job_adapter,
            "career_education": edu_adapter,
            "email_outreach": outreach_adapter,
        }
    )

    await orchestrator.start_saga(
        action_id=f"action-{uuid.uuid4()}",
        saga_type="career_growth_flow",
        payload={
            "user_id": "user-2",
            "user_persona": {"work_history": ["Junior Python Developer"]},
            "current_skills": ["python"],
            "target_role": "Senior AI Engineer",
            "location": "London",
        },
    )

    assert job_adapter.calls == 3


@pytest.mark.asyncio
async def test_outreach_failure_no_compensation():
    cv_adapter = FakeCVAdapter()
    job_adapter = FakeJobAdapter()
    edu_adapter = FakeEducationAdapter()
    outreach_adapter = FakeOutreachAdapter(fail=True)

    orchestrator, fake_db = build_orchestrator(
        {
            "cv": cv_adapter,
            "job_search": job_adapter,
            "career_education": edu_adapter,
            "email_outreach": outreach_adapter,
        }
    )

    saga_id = await orchestrator.start_saga(
        action_id=f"action-{uuid.uuid4()}",
        saga_type="career_growth_flow",
        payload={
            "user_id": "user-3",
            "user_persona": {"work_history": ["Junior Python Developer"]},
            "current_skills": ["python"],
            "target_role": "Senior AI Engineer",
            "location": "London",
            "default_contact_email": "hr@londonai.example",
        },
    )

    saga = fake_db.sagas[saga_id]
    assert saga["state"] == SagaState.FAILED.value
    assert saga["result"].get("partial_success") is True
    assert not any(step.get("name", "").startswith("compensate_") for step in saga.get("steps") or [])


@pytest.mark.asyncio
async def test_idempotency_action_id_reuse():
    cv_adapter = FakeCVAdapter()
    job_adapter = FakeJobAdapter()
    edu_adapter = FakeEducationAdapter()
    outreach_adapter = FakeOutreachAdapter()

    orchestrator, _ = build_orchestrator(
        {
            "cv": cv_adapter,
            "job_search": job_adapter,
            "career_education": edu_adapter,
            "email_outreach": outreach_adapter,
        }
    )

    action_id = f"action-{uuid.uuid4()}"
    payload = {
        "user_id": "user-4",
        "user_persona": {"work_history": ["Junior Python Developer"]},
        "current_skills": ["python"],
        "target_role": "Senior AI Engineer",
        "location": "London",
    }

    results = await asyncio.gather(
        orchestrator.start_saga(action_id, "career_growth_flow", payload),
        orchestrator.start_saga(action_id, "career_growth_flow", payload),
    )

    assert results[0] == results[1]
    assert cv_adapter.calls == 1

