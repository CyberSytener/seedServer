"""AgentBudget — tool-aware budget extending LLMBudget concepts (Phase 7 — P7-03).

Tracks LLM tokens/cost/wall-time **plus** tool call counts and per-tool limits.
JSON-serializable for persistence in ``agent_sessions.budget_config``.

Extended for P0-19: parent-child budget hierarchy with ``create_child()``
and ``asyncio.Lock`` for concurrency-safe parallel consumption.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentBudget:
    """Server-side budget enforced by the agent session loop.

    The model cannot bypass these limits — they are checked *before* every
    LLM call and tool invocation.
    """

    # --- LLM limits (mirrors LLMBudget) ---
    max_total_tokens: Optional[int] = 10_000
    max_total_cost_units: Optional[float] = 20.0
    max_wall_time_seconds: Optional[float] = 120.0

    # --- Tool limits (P7-03 extension) ---
    max_tool_calls: int = 20
    per_tool_limits: Dict[str, int] = field(default_factory=dict)

    # --- Consumed counters ---
    consumed_tokens: int = 0
    consumed_cost_units: float = 0.0
    consumed_tool_calls: int = 0
    consumed_per_tool: Dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)

    # --- Per-user cost attribution (P0-26) ---
    per_user_consumption: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # --- Parent-child hierarchy (P0-19) ---
    budget_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _parent: Optional["AgentBudget"] = field(default=None, repr=False)
    child_budget_ids: List[str] = field(default_factory=list)

    # Concurrency lock — serializes consume() from parallel children
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        # Ensure _lock is always present (e.g. after deserialization)
        if not hasattr(self, "_lock") or self._lock is None:
            object.__setattr__(self, "_lock", asyncio.Lock())

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "AgentBudget":
        """Construct from a JSON-deserialized config dict (from session row)."""
        return cls(
            max_total_tokens=config.get("max_total_tokens", 10_000),
            max_total_cost_units=config.get("max_total_cost_units", 20.0),
            max_wall_time_seconds=config.get("max_wall_time_seconds", 120.0),
            max_tool_calls=config.get("max_tool_calls", 20),
            per_tool_limits=dict(config.get("per_tool_limits") or {}),
            consumed_tokens=config.get("consumed_tokens", 0),
            consumed_cost_units=config.get("consumed_cost_units", 0.0),
            consumed_tool_calls=config.get("consumed_tool_calls", 0),
            consumed_per_tool=dict(config.get("consumed_per_tool") or {}),
            budget_id=config.get("budget_id", uuid.uuid4().hex[:12]),
            child_budget_ids=list(config.get("child_budget_ids") or []),
            per_user_consumption=dict(config.get("per_user_consumption") or {}),
        )

    # ------------------------------------------------------------------
    # Parent-child hierarchy (P0-19)
    # ------------------------------------------------------------------

    @property
    def remaining_tokens(self) -> Optional[int]:
        if self.max_total_tokens is None:
            return None
        return max(0, self.max_total_tokens - self.consumed_tokens)

    @property
    def remaining_cost_units(self) -> Optional[float]:
        if self.max_total_cost_units is None:
            return None
        return max(0.0, self.max_total_cost_units - self.consumed_cost_units)

    @property
    def remaining_tool_calls(self) -> int:
        return max(0, self.max_tool_calls - self.consumed_tool_calls)

    @property
    def parent(self) -> Optional["AgentBudget"]:
        return self._parent

    def create_child(
        self,
        *,
        max_tool_calls: int = 10,
        max_tokens: Optional[int] = None,
        max_cost: Optional[float] = None,
        max_wall_time: Optional[float] = None,
        per_tool_limits: Optional[Dict[str, int]] = None,
    ) -> "AgentBudget":
        """Create a child budget capped at ``min(requested, parent.remaining)``.

        The child's ``consume_*`` calls cascade to this parent (serialized
        through ``asyncio.Lock`` to prevent overspend with parallel children).
        """
        # Cap at parent remaining
        eff_tokens: Optional[int] = None
        if self.remaining_tokens is not None:
            eff_tokens = min(max_tokens, self.remaining_tokens) if max_tokens is not None else self.remaining_tokens

        eff_cost: Optional[float] = None
        if self.remaining_cost_units is not None:
            eff_cost = min(max_cost, self.remaining_cost_units) if max_cost is not None else self.remaining_cost_units

        eff_tool_calls = min(max_tool_calls, self.remaining_tool_calls)

        eff_wall_time: Optional[float] = None
        if self.max_wall_time_seconds is not None:
            remaining_wall = max(0.0, self.max_wall_time_seconds - self.elapsed_seconds)
            eff_wall_time = min(max_wall_time, remaining_wall) if max_wall_time is not None else remaining_wall

        child = AgentBudget(
            max_total_tokens=eff_tokens,
            max_total_cost_units=eff_cost,
            max_wall_time_seconds=eff_wall_time,
            max_tool_calls=eff_tool_calls,
            per_tool_limits=dict(per_tool_limits or {}),
            _parent=self,
            # Share the parent's lock so all children serialize through it
            _lock=self._lock,
        )
        self.child_budget_ids.append(child.budget_id)
        return child

    def split_budget(
        self,
        n: int,
        *,
        per_tool_limits: Optional[Dict[str, int]] = None,
    ) -> List["AgentBudget"]:
        """Split remaining budget into *n* equal child budgets.

        Each child gets ``remaining / n`` for tokens, cost, tool calls, and
        wall time.  All children share the parent's ``asyncio.Lock`` so
        concurrent consumption never exceeds the parent ceiling.
        """
        if n < 1:
            raise ValueError("n must be >= 1")
        children: List["AgentBudget"] = []
        for _ in range(n):
            share_tokens: Optional[int] = None
            if self.remaining_tokens is not None:
                share_tokens = max(1, self.remaining_tokens // n)
            share_cost: Optional[float] = None
            if self.remaining_cost_units is not None:
                share_cost = max(0.01, self.remaining_cost_units / n)
            share_tool_calls = max(1, self.remaining_tool_calls // n)
            share_wall: Optional[float] = None
            if self.max_wall_time_seconds is not None:
                remaining_wall = max(0.0, self.max_wall_time_seconds - self.elapsed_seconds)
                share_wall = remaining_wall  # each child gets full remaining wall time
            child = self.create_child(
                max_tokens=share_tokens,
                max_cost=share_cost,
                max_tool_calls=share_tool_calls,
                max_wall_time=share_wall,
                per_tool_limits=per_tool_limits,
            )
            children.append(child)
        return children

    # ------------------------------------------------------------------
    # Pre-checks (return stop-reason string or None)
    # ------------------------------------------------------------------

    def pre_check(self) -> Optional[str]:
        """Check all limits before an operation. Returns stop-reason or None."""
        if self.max_wall_time_seconds is not None and self.elapsed_seconds >= self.max_wall_time_seconds:
            return "budget_exceeded_time"
        if self.max_total_tokens is not None and self.consumed_tokens >= self.max_total_tokens:
            return "budget_exceeded_tokens"
        if self.max_total_cost_units is not None and self.consumed_cost_units >= self.max_total_cost_units:
            return "budget_exceeded_cost"
        if self.consumed_tool_calls >= self.max_tool_calls:
            return "budget_exceeded_tool_calls"
        return None

    def pre_check_tool(self, tool_name: str) -> Optional[str]:
        """Check tool-specific limits before a tool call."""
        base = self.pre_check()
        if base:
            return base
        if tool_name in self.per_tool_limits:
            used = self.consumed_per_tool.get(tool_name, 0)
            if used >= self.per_tool_limits[tool_name]:
                return f"budget_exceeded_per_tool:{tool_name}"
        return None

    # ------------------------------------------------------------------
    # Consume
    # ------------------------------------------------------------------

    def consume_llm(self, tokens: int = 0, cost_units: float = 0.0, *, user_id: Optional[str] = None) -> None:
        """Record LLM usage.  Cascades to parent if this is a child budget."""
        self.consumed_tokens += max(0, tokens)
        self.consumed_cost_units += max(0.0, cost_units)
        if user_id:
            self._track_user(user_id, tokens=max(0, tokens), cost_units=max(0.0, cost_units))
        if self._parent is not None:
            self._parent.consumed_tokens += max(0, tokens)
            self._parent.consumed_cost_units += max(0.0, cost_units)
            if user_id:
                self._parent._track_user(user_id, tokens=max(0, tokens), cost_units=max(0.0, cost_units))

    def consume_tool_call(self, tool_name: str, *, user_id: Optional[str] = None) -> None:
        """Record one tool invocation.  Cascades to parent if this is a child budget."""
        self.consumed_tool_calls += 1
        self.consumed_per_tool[tool_name] = self.consumed_per_tool.get(tool_name, 0) + 1
        if user_id:
            self._track_user(user_id, tool_calls=1)
        if self._parent is not None:
            self._parent.consumed_tool_calls += 1
            self._parent.consumed_per_tool[tool_name] = (
                self._parent.consumed_per_tool.get(tool_name, 0) + 1
            )
            if user_id:
                self._parent._track_user(user_id, tool_calls=1)

    def _track_user(
        self,
        user_id: str,
        *,
        tokens: int = 0,
        cost_units: float = 0.0,
        tool_calls: int = 0,
    ) -> None:
        """Accumulate per-user consumption."""
        entry = self.per_user_consumption.setdefault(user_id, {
            "tokens": 0,
            "cost_units": 0.0,
            "tool_calls": 0,
        })
        entry["tokens"] += tokens
        entry["cost_units"] += cost_units
        entry["tool_calls"] += tool_calls

    async def async_consume_llm(self, tokens: int = 0, cost_units: float = 0.0, *, user_id: Optional[str] = None) -> None:
        """Concurrency-safe LLM consumption (acquires ``_lock``)."""
        async with self._lock:
            self.consume_llm(tokens, cost_units, user_id=user_id)

    async def async_consume_tool_call(self, tool_name: str, *, user_id: Optional[str] = None) -> None:
        """Concurrency-safe tool consumption (acquires ``_lock``)."""
        async with self._lock:
            self.consume_tool_call(tool_name, user_id=user_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def would_exceed_tokens(self, estimated_tokens: int) -> bool:
        if self.max_total_tokens is None:
            return False
        return (self.consumed_tokens + estimated_tokens) > self.max_total_tokens

    # ------------------------------------------------------------------
    # Snapshot (JSON-serializable)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of current budget state."""
        return {
            "budget_id": self.budget_id,
            "max_total_tokens": self.max_total_tokens,
            "max_total_cost_units": self.max_total_cost_units,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_tool_calls": self.max_tool_calls,
            "per_tool_limits": dict(self.per_tool_limits),
            "consumed_tokens": self.consumed_tokens,
            "consumed_cost_units": round(self.consumed_cost_units, 6),
            "consumed_tool_calls": self.consumed_tool_calls,
            "consumed_per_tool": dict(self.consumed_per_tool),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "parent_budget_id": self._parent.budget_id if self._parent else None,
            "child_budget_ids": list(self.child_budget_ids),
            "per_user_consumption": {
                uid: dict(usage) for uid, usage in self.per_user_consumption.items()
            },
        }

    def to_config(self) -> Dict[str, Any]:
        """Serialize to a config dict suitable for ``budget_config`` JSON column."""
        snap = self.snapshot()
        # Remove elapsed_seconds — recomputed from started_at on load
        snap.pop("elapsed_seconds", None)
        return snap
