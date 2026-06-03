from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LLMBudget:
    max_total_tokens: Optional[int] = None
    max_total_cost_units: Optional[float] = None
    max_wall_time_seconds: Optional[float] = None
    started_at: float = field(default_factory=time.monotonic)
    consumed_tokens: int = 0
    consumed_cost_units: float = 0.0

    @classmethod
    def from_payload(cls, payload: Dict[str, Any], mode: str) -> "LLMBudget":
        defaults = {
            "fast": {
                "max_total_tokens": 6000,
                "max_total_cost_units": 12.0,
                "max_wall_time_seconds": 25.0,
            },
            "best": {
                "max_total_tokens": 18000,
                "max_total_cost_units": 40.0,
                "max_wall_time_seconds": 90.0,
            },
        }
        cfg = dict(defaults.get(str(mode or "").lower(), defaults["fast"]))
        payload_budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
        cfg.update({k: v for k, v in payload_budget.items() if v is not None})
        max_wall_time_seconds = _as_float(cfg.get("max_wall_time_seconds"))
        if max_wall_time_seconds is not None and max_wall_time_seconds <= 0:
            # Explicitly treat zero/negative wall-time as disabled budget limit.
            max_wall_time_seconds = None

        return cls(
            max_total_tokens=_as_int(cfg.get("max_total_tokens")),
            max_total_cost_units=_as_float(cfg.get("max_total_cost_units")),
            max_wall_time_seconds=max_wall_time_seconds,
        )

    def pre_check(self) -> Optional[str]:
        if self.max_wall_time_seconds is not None and self.elapsed_seconds >= self.max_wall_time_seconds:
            return "budget_exceeded_time"
        if self.max_total_tokens is not None and self.consumed_tokens >= self.max_total_tokens:
            return "budget_exceeded_tokens"
        if self.max_total_cost_units is not None and self.consumed_cost_units >= self.max_total_cost_units:
            return "budget_exceeded_cost"
        return None

    def consume(self, usage: Optional[Dict[str, Any]], cost: Optional[Dict[str, Any]]) -> None:
        usage = usage or {}
        cost = cost or {}
        total_tokens = _as_int(usage.get("total_tokens")) or 0
        cost_units = _as_float(cost.get("units")) or 0.0
        self.consumed_tokens += max(0, total_tokens)
        self.consumed_cost_units += max(0.0, cost_units)

    def would_exceed(
        self,
        usage_estimate: Optional[Dict[str, Any]],
        cost_estimate: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        usage_estimate = usage_estimate or {}
        cost_estimate = cost_estimate or {}
        predicted_tokens = self.consumed_tokens + max(0, (_as_int(usage_estimate.get("total_tokens")) or 0))
        predicted_cost = self.consumed_cost_units + max(0.0, (_as_float(cost_estimate.get("units")) or 0.0))
        if self.max_total_tokens is not None and predicted_tokens > self.max_total_tokens:
            return "budget_exceeded_tokens_predicted"
        if self.max_total_cost_units is not None and predicted_cost > self.max_total_cost_units:
            return "budget_exceeded_cost_predicted"
        if self.max_wall_time_seconds is not None and self.elapsed_seconds >= self.max_wall_time_seconds:
            return "budget_exceeded_time"
        return None

    def post_check(self) -> Optional[str]:
        # Keep stop-reason precedence aligned with pre_check: wall time first.
        if self.max_wall_time_seconds is not None and self.elapsed_seconds >= self.max_wall_time_seconds:
            return "budget_exceeded_time"
        if self.max_total_tokens is not None and self.consumed_tokens > self.max_total_tokens:
            return "budget_exceeded_tokens"
        if self.max_total_cost_units is not None and self.consumed_cost_units > self.max_total_cost_units:
            return "budget_exceeded_cost"
        return None

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "consumed_tokens": self.consumed_tokens,
            "consumed_cost_units": round(self.consumed_cost_units, 6),
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "max_total_tokens": self.max_total_tokens,
            "max_total_cost_units": self.max_total_cost_units,
            "max_wall_time_seconds": self.max_wall_time_seconds,
        }


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
