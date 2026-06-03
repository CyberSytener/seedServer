"""Tests for modules.bot.max_score — scoring estimates and order tracking."""
import pytest
from modules.bot.models import (
    BotInfo, GameState, GridInfo, ItemInfo, OrderInfo, OrderStatus,
)
from modules.bot.max_score import (
    MaxScoreEstimate,
    OrderTracker,
    estimate_max_score,
    score_upper_bound,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _grid(width=12, height=10, walls=None):
    return GridInfo(width=width, height=height, walls=walls or [])


def _state(
    orders=None, bots=None, items=None, round_num=0,
    max_rounds=300, total_orders=50, active_order_index=0,
    score=0,
):
    """Build a minimal GameState for testing."""
    return GameState(
        type="game_state",
        round=round_num,
        max_rounds=max_rounds,
        grid=_grid(),
        bots=bots or [BotInfo(id=0, position=[10, 8], inventory=[])],
        items=items or [],
        orders=orders or [
            OrderInfo(
                id="o0", items_required=["milk", "bread", "eggs"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            ),
            OrderInfo(
                id="o1", items_required=["cheese", "butter"],
                items_delivered=[], complete=False, status=OrderStatus.PREVIEW,
            ),
        ],
        drop_off=[1, 8],
        score=score,
        active_order_index=active_order_index,
        total_orders=total_orders,
    )


# ── score_upper_bound ──────────────────────────────────────────────────

class TestScoreUpperBound:
    def test_default_easy(self):
        ub = score_upper_bound()
        # 50 * 4 + 50 * 5 = 200 + 250 = 450
        assert ub == 450

    def test_custom(self):
        assert score_upper_bound(10, 3) == 10 * 3 + 10 * 5  # 30 + 50 = 80

    def test_zero_orders(self):
        assert score_upper_bound(0) == 0


# ── estimate_max_score ─────────────────────────────────────────────────

class TestEstimateMaxScore:
    def test_returns_dataclass(self):
        state = _state()
        est = estimate_max_score(state)
        assert isinstance(est, MaxScoreEstimate)

    def test_total_orders_matches_state(self):
        state = _state(total_orders=25)
        est = estimate_max_score(state)
        assert est.total_orders == 25

    def test_max_rounds_matches_state(self):
        state = _state(max_rounds=150)
        est = estimate_max_score(state)
        assert est.max_rounds == 150

    def test_avg_order_size_from_visible(self):
        orders = [
            OrderInfo(id="o0", items_required=["a", "b", "c"],
                      items_delivered=[], complete=False, status=OrderStatus.ACTIVE),
            OrderInfo(id="o1", items_required=["x", "y", "z", "w"],
                      items_delivered=[], complete=False, status=OrderStatus.PREVIEW),
        ]
        state = _state(orders=orders)
        est = estimate_max_score(state)
        # avg = (3+4)/2 = 3.5
        assert est.avg_order_size == 3.5
        assert est.visible_order_sizes == [3, 4]

    def test_est_cycles_with_default_avg(self):
        state = _state(max_rounds=300)
        est = estimate_max_score(state, avg_cycle_rounds=15.0)
        assert est.est_cycles == 20  # 300 / 15

    def test_est_achievable_is_positive(self):
        state = _state()
        est = estimate_max_score(state)
        assert est.est_achievable_score > 0

    def test_upper_bound_in_estimate(self):
        state = _state(total_orders=10)
        est = estimate_max_score(state)
        assert est.score_upper_bound > 0


# ── OrderTracker ───────────────────────────────────────────────────────

class TestOrderTracker:
    def test_empty_tracker(self):
        t = OrderTracker()
        assert t.observed_count == 0
        assert t.total_items_observed == 0
        assert t.avg_observed_size == 3.5  # default fallback

    def test_update_adds_orders(self):
        t = OrderTracker()
        state = _state()
        t.update(state)
        assert t.observed_count == 2
        assert t.total_items_observed == 5  # 3 + 2

    def test_duplicate_update_same_orders(self):
        t = OrderTracker()
        state = _state()
        t.update(state)
        t.update(state)  # same orders again
        assert t.observed_count == 2  # no duplicates

    def test_new_order_increments(self):
        t = OrderTracker()
        t.update(_state())
        # Simulate a new order appearing
        new_orders = [
            OrderInfo(id="o2", items_required=["a", "b"],
                      items_delivered=[], complete=False, status=OrderStatus.ACTIVE),
        ]
        t.update(_state(orders=new_orders, active_order_index=2))
        assert t.observed_count == 3

    def test_completed_order_tracked(self):
        t = OrderTracker()
        orders = [
            OrderInfo(id="o0", items_required=["a"],
                      items_delivered=["a"], complete=True, status=OrderStatus.ACTIVE),
        ]
        t.update(_state(orders=orders))
        assert "o0" in t.completed_ids

    def test_avg_observed_size(self):
        t = OrderTracker()
        t.update(_state())
        # Orders have 3 and 2 items → avg 2.5
        assert t.avg_observed_size == 2.5

    def test_exact_max_for_observed(self):
        t = OrderTracker()
        t.update(_state())
        # 5 items + 2 orders * 5 = 15
        assert t.exact_max_for_observed() == 15

    def test_projected_max(self):
        t = OrderTracker()
        t.update(_state(total_orders=10))
        # observed: 2 orders, 5 items, avg 2.5
        # unseen: 8 orders, 8 * 2.5 = 20 items
        # total items: 5 + 20 = 25
        # projected max: 25 + 10 * 5 = 75
        assert t.projected_max() == 75

    def test_summary_keys(self):
        t = OrderTracker()
        t.update(_state())
        s = t.summary()
        expected_keys = {
            "total_orders", "observed_orders", "completed_orders",
            "total_items_observed", "avg_order_size",
            "exact_max_observed", "projected_max",
        }
        assert set(s.keys()) == expected_keys
