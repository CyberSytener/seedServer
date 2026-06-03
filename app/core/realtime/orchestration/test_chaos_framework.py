import time
from app.core.realtime.orchestration.chaos_framework import ChaosExperiment, FailureType


def test_inject_and_resolve_worker_failure():
    exp = ChaosExperiment(name="test", description="desc", target_tenant="t1", duration_seconds=1)
    ev = exp.inject_worker_failure(worker_id="worker_1", delay_seconds=0)
    assert ev.failure_type == FailureType.WORKER_CRASH
    assert exp._active_failures.get("worker_1") is True

    # Resolve manually and check recovery
    exp._resolve_failure("worker_1")
    assert not exp._active_failures.get("worker_1")
    assert ev.resolved is True
    assert ev.recovery_time is not None


def test_partial_and_db_failures_and_results():
    exp = ChaosExperiment(name="test2", description="d", target_tenant="t2", duration_seconds=1)
    exp.start()
    exp.inject_partial_failure("op_x", error_rate=0.2)
    exp.inject_worker_failure("w2")

    # Do not resolve failures; get_results should flag unresolved failures
    res = exp.get_results()
    assert res["failures_injected"] >= 2
    assert res["data_integrity"]["is_consistent"] is False
    assert "CRITICAL" in res["conclusion"] or "Not all failures" in res["conclusion"]
