"""Max-score computation for the NMiAI Grocery Bot.

Scoring formula (from protocol):
    score = items_delivered × 1  +  orders_completed × 5

This module provides:
- ``score_upper_bound`` — theoretical max if all orders completed instantly
- ``estimate_max_score`` — round-budget-aware estimate from round-0 state
- ``OrderTracker`` — accumulates observed orders during gameplay
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import GameState, OrderInfo


# ── Simple bounds ──────────────────────────────────────────────────────────

def score_upper_bound(
    total_orders: int = 50,
    max_items_per_order: int = 4,
) -> int:
    """Absolute theoretical ceiling assuming every order completed.

    Ignores round budget — just ``total_orders * max_items_per_order + total_orders * 5``.
    """
    return total_orders * max_items_per_order + total_orders * 5


# ── Round-0 estimate ──────────────────────────────────────────────────────

@dataclass
class MaxScoreEstimate:
    total_orders: int
    max_rounds: int
    avg_order_size: float
    visible_order_sizes: list[int]

    # Upper bound (ignoring round budget)
    score_upper_bound: int

    # Achievable estimate (round-budget-aware)
    est_cycles: int          # delivery cycles that fit in max_rounds
    est_items_delivered: int
    est_orders_completed: int
    est_achievable_score: int


def estimate_max_score(
    state: GameState,
    *,
    avg_cycle_rounds: float = 15.0,
) -> MaxScoreEstimate:
    """Estimate max score from the round-0 game state.

    Parameters
    ----------
    state : GameState
        Typically the first ``game_state`` received.
    avg_cycle_rounds : float
        Estimated average rounds per pickup-to-delivery cycle.
        Default 15.0 is conservative for Easy with optimised routing.
    """
    total_orders = state.total_orders
    max_rounds = state.max_rounds

    visible_sizes = [len(o.items_required) for o in state.orders]
    avg_size = sum(visible_sizes) / len(visible_sizes) if visible_sizes else 3.5

    # Upper bound (all orders, unlimited time)
    ub = round(total_orders * avg_size) + total_orders * 5

    # Round-budget-aware estimate
    est_cycles = int(max_rounds / avg_cycle_rounds)
    est_items = est_cycles * 3  # 3 items per trip (inventory cap)
    est_orders = min(total_orders, int(est_items / avg_size))
    est_score = est_items + est_orders * 5

    return MaxScoreEstimate(
        total_orders=total_orders,
        max_rounds=max_rounds,
        avg_order_size=round(avg_size, 2),
        visible_order_sizes=visible_sizes,
        score_upper_bound=ub,
        est_cycles=est_cycles,
        est_items_delivered=est_items,
        est_orders_completed=est_orders,
        est_achievable_score=est_score,
    )


# ── Order tracker (accumulates during gameplay) ───────────────────────────

@dataclass
class OrderTracker:
    """Accumulates observed orders across rounds to compute exact totals.

    Feed it every ``GameState``; it records new orders as they become visible.
    """
    total_orders: int = 50
    observed: dict[str, list[str]] = field(default_factory=dict)
    completed_ids: set[str] = field(default_factory=set)
    _last_active_idx: int = -1

    def update(self, state: GameState) -> None:
        self.total_orders = state.total_orders
        for order in state.orders:
            if order.id not in self.observed:
                self.observed[order.id] = list(order.items_required)
            if order.complete:
                self.completed_ids.add(order.id)

    @property
    def observed_count(self) -> int:
        return len(self.observed)

    @property
    def total_items_observed(self) -> int:
        return sum(len(v) for v in self.observed.values())

    @property
    def avg_observed_size(self) -> float:
        if not self.observed:
            return 3.5
        return self.total_items_observed / len(self.observed)

    def exact_max_for_observed(self) -> int:
        """Score if every observed order were completed."""
        return self.total_items_observed + len(self.observed) * 5

    def projected_max(self) -> int:
        """Project max score assuming unseen orders match average size."""
        unseen = max(0, self.total_orders - self.observed_count)
        unseen_items = round(unseen * self.avg_observed_size)
        total_items = self.total_items_observed + unseen_items
        return total_items + self.total_orders * 5

    def summary(self) -> dict:
        return {
            "total_orders": self.total_orders,
            "observed_orders": self.observed_count,
            "completed_orders": len(self.completed_ids),
            "total_items_observed": self.total_items_observed,
            "avg_order_size": round(self.avg_observed_size, 2),
            "exact_max_observed": self.exact_max_for_observed(),
            "projected_max": self.projected_max(),
        }
