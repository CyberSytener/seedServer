"""Background worker loop factories — extracted from create_app() in main.py."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict


async def archive_waiting_confirm_loop(saga_orchestrator: Any) -> None:
    ttl_seconds = int(os.getenv("SAGA_WAITING_CONFIRM_TTL_SECONDS", str(30 * 24 * 3600)))
    interval_seconds = int(os.getenv("SAGA_WAITING_CONFIRM_ARCHIVE_INTERVAL_SECONDS", "3600"))
    while True:
        try:
            archived = await saga_orchestrator.archive_waiting_confirm_sagas(ttl_seconds=ttl_seconds)
            if archived:
                logging.info(f"Archived {archived} waiting_confirm sagas")
        except Exception as e:
            logging.warning(f"Waiting-confirm archiver failed: {e}")
        await asyncio.sleep(interval_seconds)


async def recover_stuck_sagas_loop(saga_orchestrator: Any) -> None:
    interval_seconds = int(os.getenv("SAGA_RECOVERY_INTERVAL_SECONDS", "300"))
    stuck_threshold_seconds = int(os.getenv("SAGA_STUCK_THRESHOLD_SECONDS", "300"))
    batch_size = int(os.getenv("SAGA_RECOVERY_BATCH_SIZE", "200"))
    while True:
        try:
            if saga_orchestrator.db is None:
                await asyncio.sleep(interval_seconds)
                continue

            query = """
            SELECT saga_id
            FROM sagas
            WHERE state = $1
              AND updated_at < NOW() - INTERVAL '%s seconds'
            LIMIT $2
            """ % stuck_threshold_seconds

            rows = await saga_orchestrator.db.fetch(
                query,
                "in_progress",
                batch_size,
            )

            for row in rows:
                try:
                    await saga_orchestrator._check_saga_timeout(row["saga_id"])
                except Exception as recovery_error:
                    logging.warning(f"Recovery check failed for {row['saga_id']}: {recovery_error}")
        except Exception as e:
            logging.warning(f"Saga recovery worker failed: {e}")

        await asyncio.sleep(interval_seconds)


async def dlq_maintenance_loop(saga_orchestrator: Any) -> None:
    from app.core.realtime.sagas.dlq_maintenance import (
        DLQMaintenanceConfig,
        run_dlq_maintenance_cycle,
    )

    interval_seconds = int(os.getenv("SAGA_DLQ_MAINTENANCE_INTERVAL_SECONDS", "900"))
    enabled = str(os.getenv("SAGA_DLQ_MAINTENANCE_ENABLED", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        return

    config = DLQMaintenanceConfig(
        list_limit=int(os.getenv("SAGA_DLQ_MAINTENANCE_LIST_LIMIT", "200")),
        retry_count_threshold=int(os.getenv("SAGA_DLQ_MAINTENANCE_RETRY_THRESHOLD", "2")),
        min_age_minutes=int(os.getenv("SAGA_DLQ_MAINTENANCE_MIN_AGE_MINUTES", "10")),
        include_message_types=[
            v.strip()
            for v in str(os.getenv("SAGA_DLQ_MAINTENANCE_TYPES", "")).split(",")
            if v.strip()
        ]
        or None,
        triage_status=str(os.getenv("SAGA_DLQ_MAINTENANCE_TRIAGE_STATUS", "queued_for_retry")),
        triage_note=str(os.getenv("SAGA_DLQ_MAINTENANCE_TRIAGE_NOTE", "scheduled auto-triage")),
        retry_delay_seconds=int(os.getenv("SAGA_DLQ_MAINTENANCE_RETRY_DELAY_SECONDS", "300")),
        purge_enabled=str(os.getenv("SAGA_DLQ_MAINTENANCE_PURGE_ENABLED", "true")).strip().lower()
        in {"1", "true", "yes", "on"},
        purge_older_than_days=int(os.getenv("SAGA_DLQ_MAINTENANCE_PURGE_DAYS", "30")),
        purge_limit=int(os.getenv("SAGA_DLQ_MAINTENANCE_PURGE_LIMIT", "1000")),
        alert_eligible_threshold=int(os.getenv("SAGA_DLQ_MAINTENANCE_ALERT_THRESHOLD", "50")),
    )

    while True:
        try:
            if saga_orchestrator is None or saga_orchestrator.db is None:
                await asyncio.sleep(interval_seconds)
                continue
            await run_dlq_maintenance_cycle(saga_orchestrator, config)
        except Exception as dlq_maintenance_error:
            logging.warning(f"Saga DLQ maintenance worker failed: {dlq_maintenance_error}")
        await asyncio.sleep(interval_seconds)
