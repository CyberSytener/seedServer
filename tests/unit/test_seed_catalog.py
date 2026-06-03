"""Tests for the seed catalog module."""

from app.infrastructure.db.seed_catalog import (
    CATALOG_ITEMS,
    is_expected_catalog_seed_skip,
    log_catalog_seed_failure,
)
from fastapi import HTTPException


def test_catalog_has_50_items():
    assert len(CATALOG_ITEMS) == 50


def test_catalog_skus_unique():
    skus = [item[0] for item in CATALOG_ITEMS]
    assert len(skus) == len(set(skus))


def test_is_expected_skip_true():
    exc = HTTPException(status_code=503, detail={"error": "postgres_not_configured"})
    assert is_expected_catalog_seed_skip(exc) is True


def test_is_expected_skip_false_for_regular():
    exc = HTTPException(status_code=500, detail="something else")
    assert is_expected_catalog_seed_skip(exc) is False


def test_is_expected_skip_false_for_non_http():
    assert is_expected_catalog_seed_skip(RuntimeError("boom")) is False


def test_log_catalog_seed_failure_info(caplog):
    """Expected skip logs at INFO level."""
    import logging
    with caplog.at_level(logging.INFO):
        exc = HTTPException(status_code=503, detail={"error": "postgres_not_configured"})
        log_catalog_seed_failure(exc)
    assert "Postgres not configured" in caplog.text
