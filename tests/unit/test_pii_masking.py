"""Tests for PII masking utilities and logging filter (Phase 4, Task 4.3)."""
from __future__ import annotations

import logging

import pytest

from app.infrastructure.log_utils import (
    PIIMaskingFilter,
    mask_api_key,
    mask_email,
    mask_pii,
    safe_log_user_input,
    sanitize_log_extra,
)


# ---- mask_api_key ----

def test_mask_api_key_normal():
    assert mask_api_key("seed_abc123456789xyz") == "****9xyz"


def test_mask_api_key_short():
    assert mask_api_key("ab") == "***"


def test_mask_api_key_empty():
    assert mask_api_key("") == "***"


# ---- mask_email ----

def test_mask_email_normal():
    assert mask_email("user@example.com") == "us***@example.com"


def test_mask_email_short_username():
    assert mask_email("u@example.com") == "*@example.com"


def test_mask_email_not_email():
    assert mask_email("not-an-email") == "not-an-email"


# ---- mask_pii ----

def test_mask_pii_email_in_text():
    result = mask_pii("Contact user@example.com for info")
    assert "user@example.com" not in result
    assert "us***@example.com" in result


def test_mask_pii_api_key_in_text():
    result = mask_pii("Key: seed_abcdefghijklmnopqrstu")
    assert "seed_abcdefghijklmnopqrstu" not in result


def test_mask_pii_no_pii():
    assert mask_pii("Hello world") == "Hello world"


# ---- sanitize_log_extra ----

def test_sanitize_log_extra_masks_api_key():
    result = sanitize_log_extra({"api_key": "seed_secret123456789abcd"})
    assert result["api_key"] != "seed_secret123456789abcd"
    assert result["api_key"].startswith("****")


def test_sanitize_log_extra_masks_email():
    result = sanitize_log_extra({"user_email": "test@domain.com"})
    assert "test@domain.com" not in result["user_email"]


def test_sanitize_log_extra_none_input():
    assert sanitize_log_extra(None) == {}


# ---- safe_log_user_input ----

def test_safe_log_user_input_truncates():
    long_text = "a" * 600
    result = safe_log_user_input(long_text, max_length=100)
    assert "truncated" in result
    assert len(result) < 250


def test_safe_log_user_input_masks_pii():
    result = safe_log_user_input("My email is test@foo.com and it works")
    assert "test@foo.com" not in result


# ---- PIIMaskingFilter ----

def test_pii_filter_masks_extra_fields():
    filt = PIIMaskingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    record.user_email = "secret@domain.com"
    filt.filter(record)
    assert "secret@domain.com" not in record.user_email


def test_pii_filter_masks_message_args():
    filt = PIIMaskingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="User %s logged in", args=("admin@corp.com",), exc_info=None,
    )
    filt.filter(record)
    assert "admin@corp.com" not in str(record.args)


def test_pii_filter_returns_true():
    filt = PIIMaskingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="safe message", args=(), exc_info=None,
    )
    assert filt.filter(record) is True


def test_pii_filter_does_not_touch_internals():
    filt = PIIMaskingFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="/app/main.py", lineno=42,
        msg="ok", args=(), exc_info=None,
    )
    filt.filter(record)
    assert record.pathname == "/app/main.py"
    assert record.lineno == 42
