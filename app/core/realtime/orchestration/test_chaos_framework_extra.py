import time
import random
import pytest

from app.core.realtime.orchestration.chaos_framework import ChaosExperiment, FailureType


def test_inject_db_failure_recovers_after_duration():
    exp = ChaosExperiment(name="testdb", description="desc", target_tenant="t1")
    ev = exp.inject_db_failure(delay_seconds=0, duration_seconds=0.1)
    assert ev.failure_type == FailureType.DB_CONNECTION_DROP
    assert exp._active_failures.get("database") is True

    # Wait for recovery
    time.sleep(0.25)
    assert exp._active_failures.get("database") is None
    assert ev.resolved is True


def test_inject_network_failure_resolves():
    exp = ChaosExperiment(name="testnet", description="desc", target_tenant="t1")
    ev = exp.inject_network_failure(delay_seconds=0, duration_seconds=0.1, error_rate=0.5)
    assert ev.failure_type == FailureType.NETWORK_TIMEOUT
    assert exp._active_failures.get("network") is True

    time.sleep(0.25)
    assert exp._active_failures.get("network") is None
    assert ev.resolved is True


def test_should_fail_operation_controlled(monkeypatch):
    exp = ChaosExperiment(name="t", description="d", target_tenant="t1")
    exp.inject_partial_failure("op_x", error_rate=0.1)

    # Force random to a value that triggers failure
    monkeypatch.setattr('random.random', lambda: 0.05)
    assert exp.should_fail_operation("op_x", error_rate=0.1) is True

    # Force random to a value that does not trigger
    monkeypatch.setattr('random.random', lambda: 0.5)
    assert exp.should_fail_operation("op_x", error_rate=0.1) is False


def test_record_operation_updates_metrics():
    exp = ChaosExperiment(name="m", description="d", target_tenant="t1")
    exp.start()
    exp.inject_worker_failure("w1")

    exp.record_operation("opA", success=False, duration_ms=120, retry_count=1)
    assert exp.metrics.total_operations == 1
    assert exp.metrics.failed_operations == 1
    assert exp.metrics.retried_operations == 1

