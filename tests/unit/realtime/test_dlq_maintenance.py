import pytest

from app.core.realtime.sagas import dlq_maintenance
from app.core.realtime.sagas.dlq_maintenance import DLQMaintenanceConfig, run_dlq_maintenance_cycle


class _FakeOrchestrator:
    def __init__(self, rows):
        self.rows = rows
        self.triage_calls = []
        self.purge_calls = []

    async def list_persistent_dlq_messages(self, *, limit: int = 100):
        return self.rows[:limit]

    async def bulk_triage_persistent_dlq_messages(self, saga_ids, *, triage_status: str, note: str, retry_delay_seconds: int):
        self.triage_calls.append((list(saga_ids), triage_status, note, retry_delay_seconds))
        return len(saga_ids)

    async def purge_persistent_dlq_messages(self, *, older_than_days: int, limit: int):
        self.purge_calls.append((older_than_days, limit))
        return 3


class _MetricWithLabels:
    def __init__(self):
        self.inc_calls = []

    def labels(self, **kwargs):
        self.last_labels = kwargs
        return self

    def inc(self, value=1):
        self.inc_calls.append(value)


class _MetricGauge:
    def __init__(self):
        self.set_calls = []

    def set(self, value):
        self.set_calls.append(value)


class _FailingOrchestrator:
    async def list_persistent_dlq_messages(self, *, limit: int = 100):
        raise RuntimeError("db unavailable")


@pytest.mark.asyncio
async def test_run_dlq_maintenance_cycle_triages_and_purges():
    rows = [
        {
            "saga_id": "saga-1",
            "message_type": "timeout_no_response",
            "retry_count": 1,
            "created_at": "2020-01-01T00:00:00+00:00",
            "tags": {},
        },
        {
            "saga_id": "saga-2",
            "message_type": "permanent_failure",
            "retry_count": 1,
            "created_at": "2020-01-01T00:00:00+00:00",
            "tags": {},
        },
    ]
    orchestrator = _FakeOrchestrator(rows)
    config = DLQMaintenanceConfig(
        include_message_types=["timeout_no_response"],
        min_age_minutes=0,
        retry_count_threshold=2,
        purge_enabled=True,
        purge_older_than_days=14,
        purge_limit=500,
    )

    result = await run_dlq_maintenance_cycle(orchestrator, config)

    assert result["scanned_count"] == 2
    assert result["eligible_count"] == 1
    assert result["triaged_count"] == 1
    assert result["purged_count"] == 3
    assert result["selected_saga_ids"] == ["saga-1"]
    assert len(orchestrator.triage_calls) == 1
    assert len(orchestrator.purge_calls) == 1


@pytest.mark.asyncio
async def test_run_dlq_maintenance_cycle_skips_resolved_and_high_retry():
    rows = [
        {
            "saga_id": "saga-r",
            "message_type": "timeout_no_response",
            "retry_count": 10,
            "created_at": "2020-01-01T00:00:00+00:00",
            "tags": {},
        },
        {
            "saga_id": "saga-resolved",
            "message_type": "timeout_no_response",
            "retry_count": 0,
            "created_at": "2020-01-01T00:00:00+00:00",
            "tags": {"triage_status": "resolved"},
        },
    ]
    orchestrator = _FakeOrchestrator(rows)
    config = DLQMaintenanceConfig(min_age_minutes=0, retry_count_threshold=2, purge_enabled=False)

    result = await run_dlq_maintenance_cycle(orchestrator, config)

    assert result["eligible_count"] == 0
    assert result["triaged_count"] == 0
    assert result["purged_count"] == 0
    assert len(orchestrator.triage_calls) == 0
    assert len(orchestrator.purge_calls) == 0


@pytest.mark.asyncio
async def test_run_dlq_maintenance_cycle_emits_metrics(monkeypatch):
    cycles = _MetricWithLabels()
    alerts = _MetricWithLabels()
    eligible = _MetricGauge()
    triaged = _MetricWithLabels()
    purged = _MetricWithLabels()

    monkeypatch.setattr(dlq_maintenance, "DLQ_MAINTENANCE_CYCLES", cycles)
    monkeypatch.setattr(dlq_maintenance, "DLQ_MAINTENANCE_ALERTS_TOTAL", alerts)
    monkeypatch.setattr(dlq_maintenance, "DLQ_MAINTENANCE_ELIGIBLE", eligible)
    monkeypatch.setattr(dlq_maintenance, "DLQ_MAINTENANCE_TRIAGED_TOTAL", triaged)
    monkeypatch.setattr(dlq_maintenance, "DLQ_MAINTENANCE_PURGED_TOTAL", purged)

    rows = [
        {
            "saga_id": "saga-alert",
            "message_type": "timeout_no_response",
            "retry_count": 0,
            "created_at": "2020-01-01T00:00:00+00:00",
            "tags": {},
        }
    ]
    orchestrator = _FakeOrchestrator(rows)
    config = DLQMaintenanceConfig(min_age_minutes=0, alert_eligible_threshold=1)

    result = await run_dlq_maintenance_cycle(orchestrator, config)

    assert result["eligible_count"] == 1
    assert eligible.set_calls[-1] == 1
    assert triaged.inc_calls[-1] == 1
    assert purged.inc_calls[-1] == 3
    assert cycles.inc_calls[-1] == 1
    assert alerts.inc_calls[-1] == 1


@pytest.mark.asyncio
async def test_run_dlq_maintenance_cycle_marks_error_metric(monkeypatch):
    cycles = _MetricWithLabels()
    monkeypatch.setattr(dlq_maintenance, "DLQ_MAINTENANCE_CYCLES", cycles)

    with pytest.raises(RuntimeError):
        await run_dlq_maintenance_cycle(_FailingOrchestrator(), DLQMaintenanceConfig())

    assert cycles.inc_calls[-1] == 1
