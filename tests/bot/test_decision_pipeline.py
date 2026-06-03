"""Comprehensive tests for the bot decision pipeline."""
import pytest
from modules.bot.models import (
    BotAction, BotActionCommand, BotInfo, GameState, GridInfo,
    ItemInfo, OrderInfo, OrderStatus, Pos, RoundActions,
)
from modules.bot.grid import Grid
from modules.bot.pathfinding import (
    bfs_shortest_path, bfs_distance, astar_path,
    find_pickup_position, find_all_pickup_positions,
)
from modules.bot.orders import compute_needed_items, get_active_order, items_matching_active
from modules.bot.assignment import assign_bots
from modules.bot.decision_engine import DecisionEngine
from modules.bot.collision import resolve_collisions, action_for_move


# ── Helpers ────────────────────────────────────────────────────────────

def make_grid_info(width=12, height=10, walls=None):
    return GridInfo(width=width, height=height, walls=walls or [])

def make_state(
    bots, items, orders, drop_off,
    round_num=0, walls=None, width=12, height=10, score=0,
):
    return GameState(
        type="game_state",
        round=round_num,
        max_rounds=300,
        grid=make_grid_info(width, height, walls or []),
        bots=bots,
        items=items,
        orders=orders,
        drop_off=drop_off,
        score=score,
    )


# ── Grid Tests ─────────────────────────────────────────────────────────

class TestGrid:
    def test_walkable_no_walls(self):
        grid = Grid(make_grid_info(5, 5))
        assert grid.is_walkable(0, 0)
        assert grid.is_walkable(4, 4)
        assert not grid.is_walkable(-1, 0)
        assert not grid.is_walkable(5, 0)

    def test_wall_blocking(self):
        grid = Grid(make_grid_info(5, 5, walls=[[2, 2]]))
        assert not grid.is_walkable(2, 2)
        assert grid.is_walkable(2, 1)
        assert grid.is_walkable(2, 3)

    def test_neighbors(self):
        grid = Grid(make_grid_info(5, 5, walls=[[2, 2]]))
        n = grid.neighbors(2, 1)
        assert (2, 0) in n
        assert (1, 1) in n
        assert (3, 1) in n
        assert (2, 2) not in n  # wall


# ── Pathfinding Tests ──────────────────────────────────────────────────

class TestBFS:
    def test_straight_line(self):
        grid = Grid(make_grid_info(5, 5))
        path = bfs_shortest_path(grid, (0, 0), (4, 0))
        assert path is not None
        assert len(path) == 5
        assert path[0] == (0, 0)
        assert path[-1] == (4, 0)

    def test_around_wall(self):
        # Wall blocks direct path
        grid = Grid(make_grid_info(5, 5, walls=[[2, 0], [2, 1], [2, 2]]))
        path = bfs_shortest_path(grid, (0, 0), (4, 0))
        assert path is not None
        assert (2, 0) not in path
        assert path[-1] == (4, 0)

    def test_unreachable(self):
        # Completely walled off
        grid = Grid(make_grid_info(5, 5, walls=[
            [2, 0], [2, 1], [2, 2], [2, 3], [2, 4]
        ]))
        path = bfs_shortest_path(grid, (0, 0), (4, 0))
        assert path is None

    def test_same_start_goal(self):
        grid = Grid(make_grid_info(5, 5))
        path = bfs_shortest_path(grid, (2, 2), (2, 2))
        assert path == [(2, 2)]

    def test_with_blocked_cells(self):
        grid = Grid(make_grid_info(5, 5))
        blocked = {(2, 0), (2, 1)}
        path = bfs_shortest_path(grid, (0, 0), (4, 0), blocked)
        assert path is not None
        assert (2, 0) not in path

    def test_bfs_distance(self):
        grid = Grid(make_grid_info(5, 5))
        assert bfs_distance(grid, (0, 0), (4, 0)) == 4
        assert bfs_distance(grid, (0, 0), (0, 0)) == 0


class TestAStar:
    def test_same_result_as_bfs(self):
        grid = Grid(make_grid_info(10, 10, walls=[[3, i] for i in range(8)]))
        bfs_path = bfs_shortest_path(grid, (0, 0), (9, 0))
        astar = astar_path(grid, (0, 0), (9, 0))
        assert bfs_path is not None and astar is not None
        assert len(bfs_path) == len(astar)


class TestPickupPositions:
    def test_shelf_on_wall(self):
        grid = Grid(make_grid_info(10, 10, walls=[[3, 2]]))
        positions = find_all_pickup_positions(grid, (3, 2))
        assert len(positions) > 0
        for px, py in positions:
            assert grid.is_walkable(px, py)
            assert abs(px - 3) + abs(py - 2) == 1

    def test_shelf_surrounded_by_walls(self):
        grid = Grid(make_grid_info(10, 10, walls=[
            [3, 2], [2, 2], [4, 2], [3, 1], [3, 3]
        ]))
        positions = find_all_pickup_positions(grid, (3, 2))
        assert len(positions) == 0  # completely surrounded


# ── Order Logic Tests ──────────────────────────────────────────────────

class TestOrderLogic:
    def test_compute_needed_basic(self):
        state = make_state(
            bots=[BotInfo(id=0, position=[0, 0], inventory=[])],
            items=[],
            orders=[OrderInfo(
                id="o1", items_required=["milk", "bread"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[0, 5],
        )
        needed = compute_needed_items(state)
        assert sorted(needed) == ["bread", "milk"]

    def test_compute_needed_with_delivered(self):
        state = make_state(
            bots=[BotInfo(id=0, position=[0, 0], inventory=[])],
            items=[],
            orders=[OrderInfo(
                id="o1", items_required=["milk", "bread"],
                items_delivered=["milk"], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[0, 5],
        )
        needed = compute_needed_items(state)
        assert needed == ["bread"]

    def test_compute_needed_with_inventory(self):
        state = make_state(
            bots=[BotInfo(id=0, position=[0, 0], inventory=["bread"])],
            items=[],
            orders=[OrderInfo(
                id="o1", items_required=["milk", "bread"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[0, 5],
        )
        needed = compute_needed_items(state)
        assert needed == ["milk"]

    def test_items_matching_active(self):
        state = make_state(
            bots=[BotInfo(id=0, position=[0, 0], inventory=["milk", "cheese"])],
            items=[],
            orders=[OrderInfo(
                id="o1", items_required=["milk", "bread"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[0, 5],
        )
        matching = items_matching_active(state.bots[0], state)
        assert matching == ["milk"]


# ── Decision Engine End-to-End ─────────────────────────────────────────

class TestDecisionEngine:
    def _easy_state(self, bot_pos, bot_inv=None, items=None, delivered=None):
        """Create a minimal Easy game state."""
        walls = [[3, i] for i in range(1, 5)]  # aisle
        return make_state(
            bots=[BotInfo(id=0, position=list(bot_pos), inventory=bot_inv or [])],
            items=items or [
                ItemInfo(id="item_0", type="milk", position=[3, 2]),
            ],
            orders=[OrderInfo(
                id="o1", items_required=["milk"],
                items_delivered=delivered or [],
                complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 9],
            walls=walls,
        )

    def test_bot_moves_toward_item(self):
        engine = DecisionEngine(debug=False)
        state = self._easy_state(bot_pos=(5, 8))
        actions = engine.decide(state)
        assert len(actions.actions) == 1
        # Bot should move (not wait) toward item
        assert actions.actions[0].action != BotAction.WAIT

    def test_bot_picks_up_when_adjacent(self):
        engine = DecisionEngine(debug=False)
        # Bot at (4, 2) is adjacent to item at (3, 2)
        state = self._easy_state(bot_pos=(4, 2))
        actions = engine.decide(state)
        assert actions.actions[0].action == BotAction.PICK_UP
        assert actions.actions[0].item_id == "item_0"

    def test_bot_picks_up_from_left(self):
        engine = DecisionEngine(debug=False)
        # Bot at (2, 2) is adjacent to item at (3, 2)
        state = self._easy_state(bot_pos=(2, 2))
        actions = engine.decide(state)
        assert actions.actions[0].action == BotAction.PICK_UP
        assert actions.actions[0].item_id == "item_0"

    def test_bot_delivers_at_dropoff(self):
        engine = DecisionEngine(debug=False)
        # Bot at drop_off with matching item
        state = self._easy_state(
            bot_pos=(1, 9),
            bot_inv=["milk"],
            items=[],  # no items left on map
        )
        actions = engine.decide(state)
        assert actions.actions[0].action == BotAction.DROP_OFF

    def test_bot_moves_to_dropoff_with_full_inventory(self):
        engine = DecisionEngine(debug=False)
        state = self._easy_state(
            bot_pos=(5, 5),
            bot_inv=["milk", "bread", "eggs"],
            items=[],
        )
        actions = engine.decide(state)
        # Should move toward drop-off, not wait
        assert actions.actions[0].action != BotAction.WAIT

    def test_bot_heads_to_dropoff_when_no_more_needed_items_on_map(self):
        engine = DecisionEngine(debug=False)
        # Bot has 1 item, no items on map match needed types
        state = self._easy_state(
            bot_pos=(5, 5),
            bot_inv=["milk"],
            items=[],  # no items left
        )
        actions = engine.decide(state)
        # Should head to drop-off
        assert actions.actions[0].action != BotAction.WAIT

    def test_full_cycle(self):
        """Simulate pick -> deliver cycle. Bot should score."""
        engine = DecisionEngine(debug=False)
        
        walls = [[3, i] for i in range(1, 5)]
        
        # Start: bot at (4, 2), adjacent to item at (3, 2)
        state = make_state(
            bots=[BotInfo(id=0, position=[4, 2], inventory=[])],
            items=[ItemInfo(id="item_0", type="milk", position=[3, 2])],
            orders=[OrderInfo(
                id="o1", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 9],
            walls=walls,
        )
        
        # Round 1: should pick up
        actions = engine.decide(state)
        assert actions.actions[0].action == BotAction.PICK_UP
        
        # Round 2: bot now has milk, no items on map
        # Should head to drop-off
        state2 = make_state(
            bots=[BotInfo(id=0, position=[4, 2], inventory=["milk"])],
            items=[],
            orders=[OrderInfo(
                id="o1", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 9],
            walls=walls,
        )
        actions2 = engine.decide(state2)
        assert actions2.actions[0].action != BotAction.WAIT
        assert actions2.actions[0].action != BotAction.PICK_UP
        
        # Round N: bot at drop-off with milk
        state3 = make_state(
            bots=[BotInfo(id=0, position=[1, 9], inventory=["milk"])],
            items=[],
            orders=[OrderInfo(
                id="o1", items_required=["milk"],
                items_delivered=[], complete=False, status=OrderStatus.ACTIVE,
            )],
            drop_off=[1, 9],
            walls=walls,
        )
        actions3 = engine.decide(state3)
        assert actions3.actions[0].action == BotAction.DROP_OFF


# ── Collision Tests ────────────────────────────────────────────────────

class TestCollision:
    def test_no_conflict(self):
        plans = [(0, (0, 0), (1, 0)), (1, (5, 5), (5, 4))]
        resolved = resolve_collisions(plans, set())
        assert resolved[0] == (1, 0)
        assert resolved[1] == (5, 4)

    def test_same_target(self):
        plans = [(0, (0, 0), (1, 0)), (1, (2, 0), (1, 0))]
        resolved = resolve_collisions(plans, set())
        # One gets the cell, other stays
        arrived = [bid for bid, pos in resolved.items() if pos == (1, 0)]
        stayed = [bid for bid, pos in resolved.items() if pos != (1, 0)]
        assert len(arrived) == 1
        assert len(stayed) == 1

    def test_action_for_move(self):
        assert action_for_move((0, 0), (1, 0)) == BotAction.MOVE_RIGHT
        assert action_for_move((0, 0), (0, 1)) == BotAction.MOVE_DOWN
        assert action_for_move((1, 0), (0, 0)) == BotAction.MOVE_LEFT
        assert action_for_move((0, 1), (0, 0)) == BotAction.MOVE_UP
        assert action_for_move((0, 0), (0, 0)) == BotAction.WAIT
