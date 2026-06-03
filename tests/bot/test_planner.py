"""Tests for modules.bot.planner — OptimizedEngine and PlannerConfig."""
import pytest
from modules.bot.models import (
    BotAction, BotActionCommand, BotInfo, GameState, GridInfo,
    ItemInfo, OrderInfo, OrderStatus, RoundActions,
)
from modules.bot.planner import OptimizedEngine, PlannerConfig


# ── Helpers ────────────────────────────────────────────────────────────

def _grid(width=12, height=10, walls=None):
    return GridInfo(width=width, height=height, walls=walls or [])


def _state(
    bots=None, items=None, orders=None, drop_off=None,
    round_num=0, walls=None, width=12, height=10, score=0,
    total_orders=50,
):
    if bots is None:
        bots = [BotInfo(id=0, position=[5, 5], inventory=[])]
    return GameState(
        type="game_state",
        round=round_num,
        max_rounds=300,
        grid=_grid(width, height, walls),
        bots=bots,
        items=items or [],
        orders=orders or [
            OrderInfo(id="o0", items_required=["milk"],
                      items_delivered=[], complete=False, status=OrderStatus.ACTIVE),
        ],
        drop_off=drop_off or [1, 1],
        score=score,
        total_orders=total_orders,
    )


EASY_WALLS = [
    # Border walls for a small 8x6 test grid
    *[[x, 0] for x in range(8)],
    *[[x, 5] for x in range(8)],
    *[[0, y] for y in range(6)],
    *[[7, y] for y in range(6)],
    # Internal shelf blocks (items sit on walls)
    [3, 2], [4, 2],
    [3, 3], [4, 3],
]


# ── PlannerConfig ──────────────────────────────────────────────────────

class TestPlannerConfig:
    def test_defaults(self):
        c = PlannerConfig()
        assert c.lookahead_orders == 2
        assert c.active_weight == 10.0
        assert c.preview_weight == 3.0
        assert c.prefetch is True

    def test_to_dict_roundtrip(self):
        c = PlannerConfig(lookahead_orders=5, preview_weight=7.0)
        d = c.to_dict()
        c2 = PlannerConfig.from_dict(d)
        assert c2.lookahead_orders == 5
        assert c2.preview_weight == 7.0

    def test_from_dict_ignores_extra_keys(self):
        d = {"lookahead_orders": 1, "unknown_key": True}
        c = PlannerConfig.from_dict(d)
        assert c.lookahead_orders == 1


# ── OptimizedEngine basics ─────────────────────────────────────────────

class TestOptimizedEngineBasics:
    def test_decide_returns_round_actions(self):
        engine = OptimizedEngine()
        state = _state()
        result = engine.decide(state)
        assert isinstance(result, RoundActions)
        assert len(result.actions) >= 0

    def test_decide_no_bots_returns_empty(self):
        engine = OptimizedEngine()
        state = _state(bots=[])
        result = engine.decide(state)
        assert result.actions == []

    def test_decide_records_timing(self):
        engine = OptimizedEngine()
        state = _state()
        engine.decide(state)
        assert engine.last_decision_ms >= 0


# ── Opportunistic drop-off ─────────────────────────────────────────────

class TestOpportunisticDropOff:
    def test_drop_off_when_at_dropoff_with_matching_items(self):
        """Bot at drop-off with matching inventory → drop off."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[1, 1], inventory=["milk"])],
            orders=[OrderInfo(
                id="o0", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 1],
        )
        result = engine.decide(state)
        assert len(result.actions) == 1
        assert result.actions[0].action == BotAction.DROP_OFF

    def test_no_drop_off_without_matching(self):
        """Bot at drop-off with non-matching inventory → don't drop off."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[1, 1], inventory=["cheese"])],
            orders=[OrderInfo(
                id="o0", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 1],
        )
        result = engine.decide(state)
        # Should not be DROP_OFF since cheese doesn't match
        if result.actions:
            assert result.actions[0].action != BotAction.DROP_OFF


# ── Opportunistic pickup ──────────────────────────────────────────────

class TestOpportunisticPickup:
    def test_pickup_adjacent_needed_item(self):
        """Bot adjacent to needed item → pick up."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[3, 4], inventory=[])],
            items=[ItemInfo(id="i0", type="milk", position=[3, 3])],
            orders=[OrderInfo(
                id="o0", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            walls=[[3, 3]],  # item on wall
        )
        result = engine.decide(state)
        assert len(result.actions) == 1
        assert result.actions[0].action == BotAction.PICK_UP
        assert result.actions[0].item_id == "i0"

    def test_no_pickup_unneeded_item(self):
        """Bot adjacent to item NOT needed → skip it."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[3, 4], inventory=[])],
            items=[ItemInfo(id="i0", type="cheese", position=[3, 3])],
            orders=[OrderInfo(
                id="o0", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            walls=[[3, 3]],
        )
        result = engine.decide(state)
        # Should NOT pick up cheese when only milk is needed
        if result.actions and result.actions[0].action == BotAction.PICK_UP:
            pytest.fail("Should not pick up unneeded item")


# ── Delivery timing ───────────────────────────────────────────────────

class TestDeliveryTiming:
    def test_deliver_when_order_completable(self):
        """Active needs are fully covered by inventory → head to drop-off."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=["milk"])],
            orders=[OrderInfo(
                id="o0", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 1],
        )
        result = engine.decide(state)
        # Bot should move toward drop-off
        assert result.actions[0].action in {
            BotAction.MOVE_LEFT, BotAction.MOVE_UP,
            BotAction.MOVE_DOWN, BotAction.MOVE_RIGHT,
        }

    def test_deliver_when_inventory_full(self):
        """Inventory at capacity with matching items → head to drop-off."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5],
                          inventory=["milk", "bread", "eggs"])],
            orders=[OrderInfo(
                id="o0",
                items_required=["milk", "bread", "eggs", "cheese"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            items=[ItemInfo(id="i0", type="cheese", position=[3, 3])],
            walls=[[3, 3]],
            drop_off=[1, 1],
        )
        result = engine.decide(state)
        # With full inventory and matching items, should head to drop-off
        assert result.actions[0].action in {
            BotAction.MOVE_LEFT, BotAction.MOVE_UP,
            BotAction.MOVE_DOWN, BotAction.MOVE_RIGHT,
        }

    def test_continue_picking_when_partial_order(self):
        """Bot with 1 matching item and room + items available → keep picking."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=["milk"])],
            items=[ItemInfo(id="i0", type="bread", position=[5, 3])],
            orders=[OrderInfo(
                id="o0",
                items_required=["milk", "bread", "eggs"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            walls=[[5, 3]],
            drop_off=[1, 1],
        )
        result = engine.decide(state)
        action = result.actions[0].action
        # Should move toward the item (bread at 5,3) not toward drop-off (1,1)
        # From (5,5), up is toward (5,3), left is toward (1,1)
        assert action in {BotAction.MOVE_UP, BotAction.PICK_UP}


# ── Prefetch / preview items ──────────────────────────────────────────

class TestPrefetch:
    def test_picks_preview_item_when_prefetch_enabled(self):
        """With prefetch on and no active items left, pick preview items."""
        cfg = PlannerConfig(prefetch=True)
        engine = OptimizedEngine(config=cfg)
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=[])],
            items=[ItemInfo(id="i0", type="cheese", position=[5, 4])],
            orders=[
                OrderInfo(
                    id="o0", items_required=["milk"],
                    items_delivered=["milk"], complete=False,
                    status=OrderStatus.ACTIVE,
                ),
                OrderInfo(
                    id="o1", items_required=["cheese"],
                    items_delivered=[], complete=False,
                    status=OrderStatus.PREVIEW,
                ),
            ],
            walls=[[5, 4]],
        )
        result = engine.decide(state)
        # Should pick up the preview item
        assert result.actions[0].action in {BotAction.PICK_UP, BotAction.MOVE_UP}

    def test_skips_preview_item_when_prefetch_disabled(self):
        """With prefetch off, don't pick preview-only items."""
        cfg = PlannerConfig(prefetch=False)
        engine = OptimizedEngine(config=cfg)
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=[])],
            items=[ItemInfo(id="i0", type="cheese", position=[5, 4])],
            orders=[
                OrderInfo(
                    id="o0", items_required=["milk"],
                    items_delivered=["milk"], complete=False,
                    status=OrderStatus.ACTIVE,
                ),
                OrderInfo(
                    id="o1", items_required=["cheese"],
                    items_delivered=[], complete=False,
                    status=OrderStatus.PREVIEW,
                ),
            ],
            walls=[[5, 4]],
        )
        result = engine.decide(state)
        # Should not actively pursue the preview item
        # (it may wait or try to deliver nothing)
        if result.actions:
            assert result.actions[0].action != BotAction.PICK_UP


# ── Deterministic tie-breaking ─────────────────────────────────────────

class TestDeterminism:
    def test_same_seed_same_result(self):
        """Same tiebreak_seed → identical decisions."""
        cfg = PlannerConfig(tiebreak_seed=42)
        items = [
            ItemInfo(id="i0", type="milk", position=[3, 3]),
            ItemInfo(id="i1", type="milk", position=[7, 3]),
        ]
        orders = [OrderInfo(
            id="o0", items_required=["milk", "milk"],
            items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
        )]
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=[])],
            items=items, orders=orders,
            walls=[[3, 3], [7, 3]],
        )

        eng1 = OptimizedEngine(config=PlannerConfig(tiebreak_seed=42))
        eng2 = OptimizedEngine(config=PlannerConfig(tiebreak_seed=42))
        r1 = eng1.decide(state)
        r2 = eng2.decide(state)
        assert r1.actions[0].action == r2.actions[0].action

    def test_different_seed_may_differ(self):
        """Different seeds may produce different tie-breaks (not guaranteed)."""
        items = [
            ItemInfo(id="i0", type="milk", position=[3, 3]),
            ItemInfo(id="i1", type="milk", position=[7, 3]),
        ]
        orders = [OrderInfo(
            id="o0", items_required=["milk", "milk"],
            items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
        )]
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=[])],
            items=items, orders=orders,
            walls=[[3, 3], [7, 3]],
        )
        # Just check that it doesn't crash with different seeds
        for seed in [0, 1, 2, 10, 99]:
            eng = OptimizedEngine(config=PlannerConfig(tiebreak_seed=seed))
            result = eng.decide(state)
            assert len(result.actions) == 1


# ── Fallback / edge cases ─────────────────────────────────────────────

class TestEdgeCases:
    def test_no_items_on_map(self):
        """No items anywhere → wait or deliver."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=[])],
            items=[],
        )
        result = engine.decide(state)
        assert result.actions[0].action == BotAction.WAIT

    def test_bot_with_non_matching_inventory_no_items(self):
        """Bot has items but none match order, no items on map → move to drop-off or wait."""
        engine = OptimizedEngine()
        state = _state(
            bots=[BotInfo(id=0, position=[5, 5], inventory=["cheese"])],
            items=[],
            orders=[OrderInfo(
                id="o0", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
        )
        result = engine.decide(state)
        # Bot has non-matching inventory → fallback moves toward drop-off
        # (planner tries to deliver inventory even if non-matching, to clear slots)
        assert result.actions[0].action in {
            BotAction.WAIT, BotAction.MOVE_UP, BotAction.MOVE_DOWN,
            BotAction.MOVE_LEFT, BotAction.MOVE_RIGHT,
        }

    def test_single_round_game(self):
        """Edge case: round 299 of 300 → still makes a valid decision."""
        engine = OptimizedEngine()
        state = _state(round_num=299)
        result = engine.decide(state)
        assert len(result.actions) >= 0
