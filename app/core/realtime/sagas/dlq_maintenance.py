from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

from app.core.metrics import (
    DLQ_MAINTENANCE_ALERTS_TOTAL,
    DLQ_MAINTENANCE_CYCLES,
    DLQ_MAINTENANCE_ELIGIBLE,
    DLQ_MAINTENANCE_PURGED_TOTAL,
    DLQ_MAINTENANCE_TRIAGED_TOTAL,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DLQMaintenanceConfig:
    list_limit: int = 200
    retry_count_threshold: int = 2
    min_age_minutes: int = 10
    include_message_types: Optional[List[str]] = None
    triage_status: str = "queued_for_retry"
    triage_note: str = "scheduled auto-triage"
    retry_delay_seconds: int = 300
    purge_enabled: bool = True
    purge_older_than_days: int = 30
    purge_limit: int = 1000
    alert_eligible_threshold: int = 50


def _parse_datetime_safe(raw_value: Any) -> Optional[datetime]:
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value if raw_value.tzinfo else raw_value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except Exception:
        return None


async def run_dlq_maintenance_cycle(orchestrator: Any, config: DLQMaintenanceConfig) -> Dict[str, Any]:
    try:
        rows = await orchestrator.list_persistent_dlq_messages(limit=max(1, int(config.list_limit)))

        transient_defaults = {
            "timeout_no_response",
            "adapter_circuit_open",
            "lock_timeout",
            "unknown_error",
        }
        allowed_types = {
            str(t).strip().lower()
            for t in (config.include_message_types or list(transient_defaults))
            if str(t).strip()
        }

        now = datetime.now(timezone.utc)
        selected_saga_ids: List[str] = []
        for row in rows:
            message_type = str(row.get("message_type") or "").strip().lower()
            retry_count = int(row.get("retry_count") or 0)
            created_at = _parse_datetime_safe(row.get("created_at"))
            tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
            triage_status = str(tags.get("triage_status") or "").strip().lower()

            if message_type not in allowed_types:
                continue
            if retry_count > max(0, int(config.retry_count_threshold)):
                continue
            if triage_status in {"resolved", "archived", "ignore"}:
                continue
            if created_at is not None:
                age_minutes = (now - created_at).total_seconds() / 60.0
                if age_minutes < max(0, int(config.min_age_minutes)):
                    continue

            saga_id = str(row.get("saga_id") or "").strip()
            if saga_id and saga_id not in selected_saga_ids:
                selected_saga_ids.append(saga_id)

        triaged_count = 0
        if selected_saga_ids:
            triaged_count = await orchestrator.bulk_triage_persistent_dlq_messages(
                selected_saga_ids,
                triage_status=config.triage_status,
                note=config.triage_note,
                retry_delay_seconds=max(0, int(config.retry_delay_seconds)),
            )

        purged_count = 0
        if config.purge_enabled:
            purged_count = await orchestrator.purge_persistent_dlq_messages(
                older_than_days=max(1, int(config.purge_older_than_days)),
                limit=max(1, int(config.purge_limit)),
            )

        result = {
            "scanned_count": len(rows),
            "eligible_count": len(selected_saga_ids),
            "triaged_count": int(triaged_count or 0),
            "purged_count": int(purged_count or 0),
            "selected_saga_ids": selected_saga_ids,
        }

        DLQ_MAINTENANCE_ELIGIBLE.set(result["eligible_count"])
        if result["triaged_count"]:
            DLQ_MAINTENANCE_TRIAGED_TOTAL.inc(result["triaged_count"])
        if result["purged_count"]:
            DLQ_MAINTENANCE_PURGED_TOTAL.inc(result["purged_count"])

        if result["eligible_count"] >= max(1, int(config.alert_eligible_threshold)):
            DLQ_MAINTENANCE_ALERTS_TOTAL.labels(reason="eligible_threshold_exceeded").inc()
            logger.warning(
                "dlq_maintenance_alert_threshold_exceeded",
                extra={
                    "eligible_count": result["eligible_count"],
                    "alert_threshold": int(config.alert_eligible_threshold),
                    "triaged_count": result["triaged_count"],
                },
            )

        DLQ_MAINTENANCE_CYCLES.labels(status="success").inc()
        logger.info("dlq_maintenance_cycle", extra=result)
        return result
    except Exception:
        DLQ_MAINTENANCE_CYCLES.labels(status="error").inc()
        raise
