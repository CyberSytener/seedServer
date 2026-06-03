from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AssertionRecord:
    key: str
    passed: bool
    message: str
    expected: Optional[Any] = None
    actual: Optional[Any] = None


@dataclass
class ScenarioSpec:
    scenario_id: str
    title: str
    description: str


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    passed: bool
    started_at: str
    finished_at: str
    duration_ms: int
    assertions: List[AssertionRecord] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class SimulationReport:
    run_id: str
    started_at: str
    finished_at: str
    duration_ms: int
    passed: bool
    scenario_count: int
    passed_count: int
    failed_count: int
    schema_id: str = "seed.simulation.report.v2"
    scenarios: List[ScenarioResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    run_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
