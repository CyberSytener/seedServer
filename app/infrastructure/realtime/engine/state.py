"""State and step models for saga orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class SagaState(str, Enum):
    """Saga lifecycle states."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_CONFIRM = "waiting_confirm"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    ARCHIVED = "archived"


class StepStatus(str, Enum):
    """Individual step status within saga."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class SagaStepRecord:
    """Record of a step execution within saga."""

    name: str
    status: str = StepStatus.PENDING.value
    meta: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0
    compensated: bool = False
    adapter_type: Optional[str] = None
    compensatable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
