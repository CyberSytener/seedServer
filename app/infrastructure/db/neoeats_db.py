"""NeoEats Postgres database helper — extracted from app.main."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException

from app.infrastructure.db.postgres import AsyncPGDatabase


async def get_neoeats_db(app: FastAPI) -> AsyncPGDatabase:
    """Return (or create) the shared NeoEats Postgres connection."""

    async def _ensure_storage_table(neoeats_db: AsyncPGDatabase) -> None:
        try:
            await neoeats_db.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_item (
                    storage_id uuid PRIMARY KEY,
                    name text NOT NULL,
                    quantity numeric NOT NULL,
                    unit text NOT NULL,
                    expires_at date,
                    metadata jsonb,
                    created_at timestamptz DEFAULT now(),
                    updated_at timestamptz DEFAULT now()
                )
                """
            )
            await neoeats_db.execute(
                """
                CREATE TABLE IF NOT EXISTS receipts (
                    id uuid PRIMARY KEY,
                    user_id text NOT NULL,
                    image_url text,
                    total_amount numeric NOT NULL DEFAULT 0,
                    currency text NOT NULL DEFAULT 'NOK',
                    merchant_name text,
                    scanned_at timestamptz NOT NULL DEFAULT now(),
                    raw_payload jsonb,
                    created_at timestamptz DEFAULT now(),
                    updated_at timestamptz DEFAULT now()
                )
                """
            )
            await neoeats_db.execute(
                """
                CREATE TABLE IF NOT EXISTS neoeats_user_memory_events (
                    id uuid PRIMARY KEY,
                    user_id text NOT NULL,
                    event_type text NOT NULL,
                    source text NOT NULL,
                    subject text,
                    text text NOT NULL,
                    event_hash text NOT NULL,
                    confidence numeric NOT NULL DEFAULT 0.72,
                    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
                    embedding_model text,
                    embedding_status text NOT NULL DEFAULT 'pending',
                    created_at timestamptz DEFAULT now(),
                    updated_at timestamptz DEFAULT now()
                )
                """
            )
            try:
                await neoeats_db.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await neoeats_db.execute(
                    "ALTER TABLE neoeats_user_memory_events ADD COLUMN IF NOT EXISTS embedding vector"
                )
            except Exception as exc:
                logging.info("NeoEats vector extension unavailable; memory retrieval will use lexical scoring: %s", exc)
            await neoeats_db.execute(
                "ALTER TABLE storage_item ADD COLUMN IF NOT EXISTS price_paid numeric"
            )
            await neoeats_db.execute(
                "ALTER TABLE storage_item ADD COLUMN IF NOT EXISTS receipt_id uuid REFERENCES receipts(id)"
            )
            await neoeats_db.execute(
                "CREATE INDEX IF NOT EXISTS ix_storage_item_expires_at ON storage_item(expires_at)"
            )
            await neoeats_db.execute(
                "CREATE INDEX IF NOT EXISTS ix_storage_item_receipt_id ON storage_item(receipt_id)"
            )
            await neoeats_db.execute(
                "CREATE INDEX IF NOT EXISTS ix_receipts_user_scanned ON receipts(user_id, scanned_at DESC)"
            )
            await neoeats_db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_neoeats_memory_user_event_hash
                ON neoeats_user_memory_events(user_id, event_type, event_hash)
                """
            )
            await neoeats_db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_neoeats_memory_user_created
                ON neoeats_user_memory_events(user_id, created_at DESC)
                """
            )
            await neoeats_db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_neoeats_memory_user_type
                ON neoeats_user_memory_events(user_id, event_type)
                """
            )
        except Exception as exc:
            logging.warning("NeoEats storage table ensure failed: %s", exc)

    if getattr(app.state, "saga_orchestrator", None) and app.state.saga_orchestrator.db is not None:
        db_conn = app.state.saga_orchestrator.db
        await _ensure_storage_table(db_conn)
        return db_conn

    saga_db_url = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL")
    if not saga_db_url:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "postgres_not_configured",
                "message": "Postgres not configured. Set SEED_SAGA_DB_URL or DATABASE_URL.",
            },
        )
    db_conn = await AsyncPGDatabase.get_shared(saga_db_url)
    await _ensure_storage_table(db_conn)
    return db_conn


def freshness_metrics(expires_at: datetime | None) -> tuple[Optional[int], Optional[int]]:
    """Calculate freshness percentage and days-to-expiry from an expiry date."""
    if not expires_at:
        return None, None
    today = datetime.now(timezone.utc).date()
    days_to_expiry = (expires_at.date() - today).days
    window_days = 14
    freshness = int(max(0, min(100, (days_to_expiry / window_days) * 100)))
    return freshness, days_to_expiry
