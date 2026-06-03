from __future__ import annotations

import asyncio
import random
import logging
from typing import Any, Callable

from app.core.realtime.adapters.errors import TransientAdapterError, PermanentAdapterError


class RetryConfig:
    """Configuration for retry logic."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter_strategy: str = "full",
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter_strategy = str(jitter_strategy or "full").strip().lower()

    def get_base_delay(self, attempt: int) -> float:
        delay = self.initial_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)

    def get_delay(self, attempt: int, *, apply_jitter: bool = True) -> float:
        base_delay = self.get_base_delay(attempt)
        if not apply_jitter or self.jitter_strategy == "none":
            return base_delay
        if self.jitter_strategy == "equal":
            half = base_delay / 2.0
            return half + random.uniform(0.0, half)
        return random.uniform(0.0, base_delay)


RETRY_CONFIGS = {
    "reserve": RetryConfig(max_attempts=3, initial_delay=1.0),
    "confirm": RetryConfig(max_attempts=5, initial_delay=0.5),
    "compensate": RetryConfig(max_attempts=10, initial_delay=2.0),
}


async def retry_with_backoff(
    func: Callable,
    config: RetryConfig,
    operation_name: str,
    logger_instance: logging.Logger,
) -> Any:
    """Execute function with exponential backoff retry."""
    last_exception = None

    for attempt in range(config.max_attempts):
        try:
            result = func()
            if asyncio.iscoroutine(result):
                return await result
            return result
        except PermanentAdapterError as e:
            logger_instance.error(
                f"❌ {operation_name} failed with permanent error (no retry): {e}"
            )
            raise
        except TransientAdapterError as e:
            last_exception = e
            if attempt < config.max_attempts - 1:
                delay = config.get_delay(attempt, apply_jitter=True)
                logger_instance.warning(
                    f"⚠️  {operation_name} failed with transient error (attempt {attempt + 1}/{config.max_attempts}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
            else:
                logger_instance.error(
                    f"❌ {operation_name} failed after {config.max_attempts} attempts: {e}"
                )
        except Exception as e:
            logger_instance.error(
                f"❌ {operation_name} failed with unexpected error (no retry): {e}"
            )
            raise

    raise last_exception
