"""Circuit breaker for saga adapters."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: int = 60


class CircuitBreaker:
    """Circuit breaker for adapter calls to prevent cascading failures."""

    def __init__(
        self,
        config: CircuitBreakerConfig,
        adapter_name: str = "unknown",
        redis_client: Optional[Any] = None,
        metrics: Optional[Any] = None,
    ):
        self.config = config
        self.adapter_name = adapter_name
        self.redis = redis_client
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.logger = logging.getLogger(__name__)
        self.metrics = metrics

    def _report_state(self):
        if self.metrics and hasattr(self.metrics, "set_circuit_breaker_state"):
            self.metrics.set_circuit_breaker_state(
                self.adapter_name,
                self.state == CircuitState.OPEN,
            )

    def can_execute(self) -> bool:
        """Check if circuit allows execution."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time and (time.time() - self.last_failure_time) >= self.config.timeout:
                self.logger.info("Circuit breaker transitioning to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                self._report_state()
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return True

        return False

    def record_success(self):
        """Record successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.logger.info("Circuit breaker CLOSED (recovered)")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self._report_state()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    async def record_failure(self):
        """Record failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self.logger.warning("Circuit breaker re-opening after half-open failure")
            self.state = CircuitState.OPEN
            self._report_state()
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self.logger.error("Circuit breaker OPEN after %s failures", self.failure_count)
                self.state = CircuitState.OPEN
                self._report_state()

        await self._persist_state()

    async def _persist_state(self):
        """Persist circuit breaker state to Redis."""
        if not self.redis:
            return

        try:
            key = f"circuit:state:{self.adapter_name}"
            state_data = {
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure_time": self.last_failure_time,
            }
            await self.redis.setex(key, 3600, json.dumps(state_data))
        except Exception as e:
            self.logger.warning("Failed to persist circuit breaker state: %s", e)

    async def load_state(self):
        """Load circuit breaker state from Redis."""
        if not self.redis:
            return

        try:
            key = f"circuit:state:{self.adapter_name}"
            data = await self.redis.get(key)
            if data:
                state = json.loads(data)
                self.state = CircuitState(state.get("state", CircuitState.CLOSED.value))
                self.failure_count = state.get("failure_count", 0)
                self.success_count = state.get("success_count", 0)
                self.last_failure_time = state.get("last_failure_time")
                self.logger.info(
                    "Loaded circuit breaker state for %s: %s",
                    self.adapter_name,
                    self.state.value,
                )
                self._report_state()
        except Exception as e:
            self.logger.warning("Failed to load circuit breaker state: %s", e)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass
