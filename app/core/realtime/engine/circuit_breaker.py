"""Compatibility bridge for circuit breaker utilities."""

from __future__ import annotations

from app.infrastructure.realtime.engine.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
)


__all__ = [
    "CircuitState",
    "CircuitBreakerConfig",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
]
