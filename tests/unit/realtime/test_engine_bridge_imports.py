from __future__ import annotations


def test_engine_cache_bridge_points_to_infrastructure_module():
    from app.core.realtime.engine.cache import TTLCache as CoreTTLCache
    from app.infrastructure.realtime.engine.cache import TTLCache as InfraTTLCache

    assert CoreTTLCache is InfraTTLCache


def test_engine_circuit_breaker_bridge_points_to_infrastructure_module():
    from app.core.realtime.engine.circuit_breaker import (
        CircuitBreaker as CoreCircuitBreaker,
        CircuitBreakerConfig as CoreCircuitBreakerConfig,
        CircuitBreakerOpenError as CoreCircuitBreakerOpenError,
        CircuitState as CoreCircuitState,
    )
    from app.infrastructure.realtime.engine.circuit_breaker import (
        CircuitBreaker as InfraCircuitBreaker,
        CircuitBreakerConfig as InfraCircuitBreakerConfig,
        CircuitBreakerOpenError as InfraCircuitBreakerOpenError,
        CircuitState as InfraCircuitState,
    )

    assert CoreCircuitState is InfraCircuitState
    assert CoreCircuitBreakerConfig is InfraCircuitBreakerConfig
    assert CoreCircuitBreaker is InfraCircuitBreaker
    assert CoreCircuitBreakerOpenError is InfraCircuitBreakerOpenError


def test_engine_db_bridge_points_to_infrastructure_module():
    from app.core.realtime.engine.db import AsyncPGPoolProxy as CoreAsyncPGPoolProxy
    from app.infrastructure.realtime.engine.db import AsyncPGPoolProxy as InfraAsyncPGPoolProxy

    assert CoreAsyncPGPoolProxy is InfraAsyncPGPoolProxy


def test_engine_locks_bridge_points_to_infrastructure_module():
    from app.core.realtime.engine.locks import DistributedLock as CoreDistributedLock
    from app.infrastructure.realtime.engine.locks import DistributedLock as InfraDistributedLock

    assert CoreDistributedLock is InfraDistributedLock


def test_engine_state_bridge_points_to_infrastructure_module():
    from app.core.realtime.engine.state import (
        SagaState as CoreSagaState,
        SagaStepRecord as CoreSagaStepRecord,
        StepStatus as CoreStepStatus,
    )
    from app.infrastructure.realtime.engine.state import (
        SagaState as InfraSagaState,
        SagaStepRecord as InfraSagaStepRecord,
        StepStatus as InfraStepStatus,
    )

    assert CoreSagaState is InfraSagaState
    assert CoreStepStatus is InfraStepStatus
    assert CoreSagaStepRecord is InfraSagaStepRecord
