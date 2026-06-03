from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.core.realtime.adapters.errors import PermanentAdapterError, TransientAdapterError
from app.core.realtime.engine.retry import RetryConfig, retry_with_backoff


def test_retry_config_base_delay_caps_at_max_delay():
    cfg = RetryConfig(max_attempts=3, initial_delay=1.0, max_delay=2.5, exponential_base=2.0)
    assert cfg.get_base_delay(0) == 1.0
    assert cfg.get_base_delay(1) == 2.0
    assert cfg.get_base_delay(2) == 2.5


def test_retry_config_none_jitter_returns_base_delay():
    cfg = RetryConfig(max_attempts=3, initial_delay=2.0, max_delay=30.0, exponential_base=2.0, jitter_strategy="none")
    assert cfg.get_delay(0) == 2.0
    assert cfg.get_delay(1) == 4.0


def test_retry_config_equal_jitter_uses_half_plus_uniform():
    cfg = RetryConfig(max_attempts=3, initial_delay=2.0, max_delay=30.0, exponential_base=2.0, jitter_strategy="equal")
    with patch("app.core.realtime.engine.retry.random.uniform", return_value=0.5) as rand_uniform:
        delay = cfg.get_delay(1)
    rand_uniform.assert_called_once_with(0.0, 2.0)
    assert delay == 2.5


def test_retry_config_full_jitter_uses_uniform_0_to_base():
    cfg = RetryConfig(max_attempts=3, initial_delay=2.0, max_delay=30.0, exponential_base=2.0, jitter_strategy="full")
    with patch("app.core.realtime.engine.retry.random.uniform", return_value=1.25) as rand_uniform:
        delay = cfg.get_delay(1)
    rand_uniform.assert_called_once_with(0.0, 4.0)
    assert delay == 1.25


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_transient_then_succeeds():
    cfg = RetryConfig(max_attempts=4, initial_delay=1.0, max_delay=30.0, jitter_strategy="none")
    logger = Mock()

    attempts = {"count": 0}

    def flaky_call():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TransientAdapterError("temporary")
        return "ok"

    sleep_mock = AsyncMock()
    with patch("app.core.realtime.engine.retry.asyncio.sleep", sleep_mock):
        result = await retry_with_backoff(flaky_call, cfg, "test-op", logger)

    assert result == "ok"
    assert attempts["count"] == 3
    assert sleep_mock.await_count == 2
    sleep_mock.assert_any_await(1.0)
    sleep_mock.assert_any_await(2.0)


@pytest.mark.asyncio
async def test_retry_with_backoff_does_not_retry_permanent_error():
    cfg = RetryConfig(max_attempts=5, initial_delay=1.0, max_delay=30.0)
    logger = Mock()

    def permanent_fail():
        raise PermanentAdapterError("no retry")

    with patch("app.core.realtime.engine.retry.asyncio.sleep", AsyncMock()) as sleep_mock:
        with pytest.raises(PermanentAdapterError):
            await retry_with_backoff(permanent_fail, cfg, "test-op", logger)

    assert sleep_mock.await_count == 0
