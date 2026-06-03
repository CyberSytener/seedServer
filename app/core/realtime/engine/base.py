from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass(frozen=True)
class SagaStep:
    name: str
    adapter_type: Optional[str] = None
    compensatable: bool = False


@dataclass(frozen=True)
class SagaStepResult:
    meta: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    pause: bool = False


@dataclass(frozen=True)
class SagaStepDefinition:
    name: str
    execute: Callable[[], Awaitable[SagaStepResult]]
    compensate: Optional[Callable[["CompensationAction"], Awaitable[None]]] = None
    adapter_type: Optional[str] = None


@dataclass(frozen=True)
class CompensationAction:
    step_name: str
    reason: str
    meta: Optional[dict[str, Any]] = None


class BaseSaga:
    """Base saga flow. Delegates unknown attributes to the engine."""

    saga_type: str = "unknown"
    saga_version: str = "v1"

    def __init__(self, engine: Any):
        self._engine = engine

    def __getattr__(self, name: str) -> Any:
        return getattr(self._engine, name)

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(f"{self.__class__.__name__}.run not implemented")

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(f"{self.__class__.__name__}.resume not implemented")
