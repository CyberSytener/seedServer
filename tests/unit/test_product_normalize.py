"""Tests for product normalization utilities extracted to app.services.product_normalize."""

from datetime import date, datetime, timezone

import pytest

from app.services.product_normalize import (
    _build_product_id,
    _coerce_date_safe,
    _dedupe_by_product_identity,
    _is_uuid,
    _looks_like_packaging_character,
    _merge_expiry_date,
    _normalize_brand,
    _normalize_product_name,
    _now_iso,
    _parse_dt,
    _parse_iso_date_safe,
    _sanitize_vision_expiry,
)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


class TestNowIso:
    def test_returns_iso_string(self):
        result = _now_iso()
        assert "T" in result
        datetime.fromisoformat(result)  # should not raise


class TestParseDt:
    def test_iso_with_t(self):
        dt = _parse_dt("2026-03-15T10:30:00")
        assert dt is not None
        assert dt.year == 2026

    def test_iso_with_z(self):
        dt = _parse_dt("2026-03-15T10:30:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_none_returns_none(self):
        assert _parse_dt(None) is None

    def test_empty_returns_none(self):
        assert _parse_dt("") is None

    def test_plain_date_string(self):
        dt = _parse_dt("2026-03-15")
        assert dt is not None
        assert dt.year == 2026

    def test_garbage_returns_none(self):
        assert _parse_dt("not-a-date") is None


class TestParseIsoDateSafe:
    def test_valid_date(self):
        assert _parse_iso_date_safe("2026-12-25") == date(2026, 12, 25)

    def test_none_returns_none(self):
        assert _parse_iso_date_safe(None) is None

    def test_invalid_returns_none(self):
        assert _parse_iso_date_safe("abc") is None


class TestCoerceDateSafe:
    def test_date_passthrough(self):
        d = date(2026, 1, 1)
        assert _coerce_date_safe(d) == d

    def test_datetime_truncates(self):
        dt = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
        assert _coerce_date_safe(dt) == date(2026, 6, 15)

    def test_string(self):
        assert _coerce_date_safe("2026-06-15") == date(2026, 6, 15)

    def test_none(self):
        assert _coerce_date_safe(None) is None


class TestSanitizeVisionExpiry:
    def test_valid_future_date(self):
        future = date.today().replace(year=date.today().year + 1).isoformat()
        assert _sanitize_vision_expiry(future) == future

    def test_past_year_rejected(self):
        past = date(2020, 1, 1).isoformat()
        assert _sanitize_vision_expiry(past) is None

    def test_none_returns_none(self):
        assert _sanitize_vision_expiry(None) is None


# ---------------------------------------------------------------------------
# Product identity
# ---------------------------------------------------------------------------


class TestNormalizeProductName:
    def test_lowercases_and_collapses(self):
        assert _normalize_product_name("  Whole  Milk  ") == "whole milk"

    def test_none_gives_empty(self):
        assert _normalize_product_name(None) == ""


class TestNormalizeBrand:
    def test_lowercases(self):
        assert _normalize_brand("  Arla  ") == "arla"


class TestBuildProductId:
    def test_deterministic(self):
        a = _build_product_id("milk", "arla")
        b = _build_product_id("milk", "arla")
        assert a == b
        assert len(a) == 20

    def test_different_for_different_inputs(self):
        a = _build_product_id("milk", "arla")
        b = _build_product_id("juice", "arla")
        assert a != b


class TestLooksLikePackagingCharacter:
    def test_regular_product(self):
        assert not _looks_like_packaging_character("whole milk")

    def test_mascot(self):
        assert _looks_like_packaging_character("brand mascot logo")

    def test_gingerbread_man(self):
        assert _looks_like_packaging_character("Gingerbread Man")


class TestMergeExpiryDate:
    def test_both_present_takes_earlier(self):
        d1 = date(2026, 6, 1)
        d2 = date(2026, 3, 1)
        assert _merge_expiry_date(d1, d2) == d2

    def test_only_incoming(self):
        assert _merge_expiry_date(None, date(2026, 6, 1)) == date(2026, 6, 1)

    def test_only_existing(self):
        assert _merge_expiry_date(date(2026, 6, 1), None) == date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Dedup & misc
# ---------------------------------------------------------------------------


class TestDedupeByProductIdentity:
    def test_merges_by_product_id(self):
        items = [
            {"name": "Milk", "quantity": 1, "metadata": '{"product_id": "abc"}'},
            {"name": "Milk", "quantity": 2, "metadata": '{"product_id": "abc"}'},
        ]
        result = _dedupe_by_product_identity(items)
        assert len(result) == 1
        assert result[0]["quantity"] == 3.0

    def test_different_ids_kept(self):
        items = [
            {"name": "Milk", "quantity": 1, "metadata": '{"product_id": "abc"}'},
            {"name": "Juice", "quantity": 1, "metadata": '{"product_id": "xyz"}'},
        ]
        result = _dedupe_by_product_identity(items)
        assert len(result) == 2


class TestIsUuid:
    def test_valid_uuid(self):
        assert _is_uuid("550e8400-e29b-41d4-a716-446655440000")

    def test_invalid(self):
        assert not _is_uuid("not-a-uuid")

    def test_none(self):
        assert not _is_uuid(None)
