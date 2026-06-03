from __future__ import annotations

import logging

from fastapi import HTTPException

from app.infrastructure.db.seed_catalog import log_catalog_seed_failure as _log_catalog_seed_failure


def test_no_postgres_config_does_not_warn_on_catalog_seed(caplog) -> None:
    caplog.set_level(logging.INFO)
    _log_catalog_seed_failure(
        HTTPException(
            status_code=503,
            detail={
                "error": "postgres_not_configured",
                "message": "Postgres not configured. Set SEED_SAGA_DB_URL or DATABASE_URL.",
            },
        )
    )

    assert any(
        record.levelno == logging.INFO and "skipping catalog seed to DB" in record.getMessage()
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_catalog_seed_unexpected_error_still_warns(caplog) -> None:
    caplog.set_level(logging.INFO)
    _log_catalog_seed_failure(RuntimeError("db timeout"))
    assert any(record.levelno == logging.WARNING for record in caplog.records)
