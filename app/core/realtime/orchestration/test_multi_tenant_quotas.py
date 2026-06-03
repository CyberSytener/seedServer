from datetime import datetime, timedelta
import pytest

from app.core.realtime.orchestration.multi_tenant_quotas import (
    QuotaManager,
    OperationType,
)


def test_set_and_get_quota_usage_basic():
    qm = QuotaManager()
    cfg = qm.set_quota("tenant_x", emails_per_day=10, emails_per_hour=5, llm_cost_per_month=1.0)

    assert cfg.tenant_id == "tenant_x"

    allowed, reason = qm.check_quota("tenant_x", OperationType.SEND_EMAIL)
    assert allowed is True

    usage_before = qm.get_usage("tenant_x")
    assert usage_before["emails"]["sent_day"] == 0


def test_check_quota_denies_when_limits_reached():
    qm = QuotaManager()
    qm.set_quota("tenant_y", emails_per_day=3, emails_per_hour=2)

    # Record email sends
    qm.record_usage("tenant_y", OperationType.SEND_EMAIL, quantity=2)
    allowed, reason = qm.check_quota("tenant_y", OperationType.SEND_EMAIL)
    # Hourly limit reached
    assert allowed is False
    assert "Hourly" in reason

    # Now simulate hitting daily limit by bumping daily counter
    qm.usage["tenant_y"].emails_sent_today = 3
    allowed, reason = qm.check_quota("tenant_y", OperationType.SEND_EMAIL)
    assert allowed is False
    assert ("Daily" in reason) or ("Hourly" in reason)


def test_llm_cost_limit_enforced_and_events_recorded():
    qm = QuotaManager()
    qm.set_quota("tenant_z", llm_cost_per_month=0.02)

    # Single LLM call costs 0.01 by OPERATION_COSTS; two calls should be allowed then denied
    allowed, _ = qm.check_quota("tenant_z", OperationType.LLM_CALL)
    assert allowed is True

    qm.record_usage("tenant_z", OperationType.LLM_CALL, quantity=2)

    allowed, reason = qm.check_quota("tenant_z", OperationType.LLM_CALL)
    assert allowed is False
    assert "LLM" in reason

    events = qm.get_usage_events("tenant_z", hours=1)
    assert len(events) >= 1


def test_record_usage_for_unknown_tenant_returns_false():
    qm = QuotaManager()
    ok = qm.record_usage("nope", OperationType.SEND_EMAIL, quantity=1)
    assert ok is False


def test_get_usage_calculations():
    qm = QuotaManager()
    qm.set_quota("tenant_stats", emails_per_day=10, emails_per_hour=5, api_calls_per_minute=100, concurrent_campaigns=2, llm_cost_per_month=10.0, storage_gb=50)

    qm.record_usage("tenant_stats", OperationType.SEND_EMAIL, quantity=2)
    qm.record_usage("tenant_stats", OperationType.API_CALL, quantity=3)
    qm.record_usage("tenant_stats", OperationType.CREATE_CAMPAIGN, quantity=1)
    qm.record_usage("tenant_stats", OperationType.LLM_CALL, quantity=5)

    u = qm.get_usage("tenant_stats")
    assert u["emails"]["sent_day"] == 2
    assert u["api"]["calls_minute"] == 3
    assert u["campaigns"]["active"] == 1
    assert u["llm"]["cost_month"] > 0

