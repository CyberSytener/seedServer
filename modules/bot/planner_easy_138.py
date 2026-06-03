"""Schedule-driven planner using precomputed optimal trip sequence.

Uses the Dijkstra-computed optimal 21-trip schedule (138 score in 300 rounds)
and executes it with BFS-optimal routing.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from itertools import permutations, product as iprod
from typing import Optional

from .collision import action_for_move
from .grid import Grid
from .max_score import OrderTracker
from .models import (
    BotAction,
    BotActionCommand,
    BotInfo,
    GameState,
    ItemInfo,
    Pos,
    RoundActions,
)
from .orders import (
    compute_needed_items,
    compute_preview_items,
    get_active_order,
    get_preview_order,
    items_matching_active,
)
from .pathfinding import bfs_distance, bfs_shortest_path, find_all_pickup_positions


# -- Configuration ----------------------------------------------------------

@dataclass
class PlannerConfig:
    """All tunable knobs for the optimised planner."""
    lookahead_orders: int = 2
    active_weight: float = 10.0
    preview_weight: float = 3.0
    auto_delivery_bonus: float = 5.0
    return_cost_factor: float = 1.5
    prefetch: bool = True
    deliver_on_full: bool = True
    deliver_to_complete: bool = True
    time_pressure_threshold: int = 0
    preview_detour_max: int = 6
    tiebreak_seed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PlannerConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# -- Optimal schedule (from Dijkstra solver) --------------------------------

# 21 trips that complete all 16 orders in exactly 300 rounds (manhattan cost).
# Each entry: tuple of item types to pick up.
OPTIMAL_SCHEDULE = [
    ("butter", "butter", "milk"),         # Trip 1: from start (10,8)
    ("butter", "cheese"),                  # Trip 2
    ("butter", "butter"),                  # Trip 3
    ("butter", "butter", "yogurt"),        # Trip 4
    ("milk", "milk", "milk"),              # Trip 5
    ("cheese", "cheese", "cheese"),        # Trip 6
    ("yogurt", "yogurt", "yogurt"),        # Trip 7
    ("milk", "milk", "yogurt"),            # Trip 8
    ("butter", "milk", "milk"),            # Trip 9
    ("cheese", "cheese", "yogurt"),        # Trip 10
    ("butter",),                           # Trip 11
    ("milk", "milk", "yogurt"),            # Trip 12
    ("cheese", "cheese", "yogurt"),        # Trip 13
    ("butter", "butter", "butter"),        # Trip 14
    ("yogurt", "yogurt", "yogurt"),        # Trip 15
    ("butter", "butter", "butter"),        # Trip 16
    ("cheese", "cheese", "cheese"),        # Trip 17
    ("milk", "milk", "milk"),              # Trip 18
    ("milk", "milk", "yogurt"),            # Trip 19
    ("butter", "butter"),                  # Trip 20
    ("butter", "cheese", "yogurt"),        # Trip 21
]


class OptimizedEngine:
    """Schedule-driven planner: follows the Dijkstra-optimal trip sequence."""

    def __init__(
        self,
        config: Optional[PlannerConfig] = None,
        *,
        debug: bool = False,
        verbose: bool = False,
    ):
        self.config = config or PlannerConfig()
        self.debug = debug
        self.verbose = verbose
        self.last_decision_ms: float = 0.0

        self._order_tracker = OrderTracker()
        self._trip_idx = 0
        self._trip_route: list[tuple[tuple[int, int], str]] = []
        self._delivering = False

    # -- Public API ---------------------------------------------------------

    def decide(self, state: GameState) -> RoundActions:
        t0 = time.perf_counter()
        self._order_tracker.update(state)

        if not state.bots:
            self.last_decision_ms = (time.perf_counter() - t0) * 1000
            return RoundActions(actions=[])

        bot = state.bots[0]
        bpos = bot.pos.as_tuple()
        drop_off = (state.drop_off[0], state.drop_off[1])
        grid = Grid(state.grid)
        item_blocked = frozenset(
            (it.position[0], it.position[1]) for it in state.items
        )

        action = self._plan_action(bot, state, grid, drop_off, item_blocked)

        self.last_decision_ms = (time.perf_counter() - t0) * 1000
        if self.debug:
            print(
                f"  R{state.round:3d} score={state.score:3d} "
                f"pos=({bpos[0]},{bpos[1]}) inv={bot.inventory} "
                f"trip={self._trip_idx} route_len={len(self._trip_route)} "
                f"action={action.action.value}"
            )
        return RoundActions(actions=[action])

    # -- Core decision logic ------------------------------------------------

    def _plan_action(
        self,
        bot: BotInfo,
        state: GameState,
        grid: Grid,
        drop_off: tuple[int, int],
        item_blocked: frozenset[tuple[int, int]],
    ) -> BotActionCommand:
        bpos = bot.pos.as_tuple()

        # -- 1. DROP-OFF when at drop-off with inventory ------------------
        if bpos == drop_off and bot.inventory:
            matching = items_matching_active(bot, state)
            if matching:
                self._trip_route = []
                self._delivering = False
                return BotActionCommand(bot=bot.id, action=BotAction.DROP_OFF)
            # Have items but none match active → deliver anyway (shouldn't happen
            # with correct schedule, but safety)
            if not self._trip_route and len(bot.inventory) >= 3:
                return BotActionCommand(bot=bot.id, action=BotAction.DROP_OFF)

        # -- 2. FOLLOW existing route ------------------------------------
        if self._trip_route and len(bot.inventory) < 3:
            action = self._follow_route(bot, state, grid, item_blocked)
            if action is not None:
                return action

        # -- 3. DELIVER after route complete (inventory full or has matching) -
        if bot.inventory and not self._trip_route:
            matching = items_matching_active(bot, state)
            if matching or len(bot.inventory) >= 3:
                return self._move_toward(bot.id, bpos, drop_off, grid, state, item_blocked)

        # -- 4. START next trip from schedule ----------------------------
        free_slots = 3 - len(bot.inventory)
        if self._trip_idx < len(OPTIMAL_SCHEDULE) and free_slots > 0:
            types = list(OPTIMAL_SCHEDULE[self._trip_idx])
            # Trim trip if we have leftover inventory reducing free slots
            types = types[:free_slots]
            self._trip_idx += 1

            items_by_type: dict[str, list[ItemInfo]] = {}
            for item in state.items:
                items_by_type.setdefault(item.type, []).append(item)

            blocked_set = set(item_blocked)
            route = self._build_route(
                bpos, drop_off, types, items_by_type, grid, blocked_set,
            )
            if route:
                self._trip_route = route
                action = self._follow_route(bot, state, grid, item_blocked)
                if action is not None:
                    return action

        # -- 5. FALLBACK: greedy or deliver or wait ----------------------
        if bot.inventory:
            return self._move_toward(bot.id, bpos, drop_off, grid, state, item_blocked)

        # Try greedy item pickup
        active_needs = compute_needed_items(state)
        preview_needs = compute_preview_items(state)
        result = self._best_item_to_pick(
            bot, state, grid, item_blocked, active_needs, preview_needs,
        )
        if result[0] is not None and result[1] is not None:
            item, pp = result
            ipos = item.pos.as_tuple()
            if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
                return BotActionCommand(
                    bot=bot.id, action=BotAction.PICK_UP, item_id=item.id,
                )
            return self._move_toward(bot.id, bpos, pp, grid, state, item_blocked)

        return BotActionCommand(bot=bot.id, action=BotAction.WAIT)

    # -- Route following ----------------------------------------------------

    def _follow_route(
        self,
        bot: BotInfo,
        state: GameState,
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
    ) -> Optional[BotActionCommand]:
        if not self._trip_route:
            return None
        bpos = bot.pos.as_tuple()
        target_pp, target_item_id = self._trip_route[0]

        target_item = None
        for item in state.items:
            if item.id == target_item_id:
                target_item = item
                break

        if target_item is None:
            # Item disappeared?  Skip to next in route.
            self._trip_route.pop(0)
            return self._follow_route(bot, state, grid, item_blocked) if self._trip_route else None

        ipos = target_item.pos.as_tuple()
        if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
            self._trip_route.pop(0)
            return BotActionCommand(
                bot=bot.id, action=BotAction.PICK_UP,
                item_id=target_item_id,
            )

        return self._move_toward(
            bot.id, bpos, target_pp, grid, state, item_blocked,
        )

    # -- Route building (TSP with BFS distances) ----------------------------

    def _build_route(
        self,
        start: tuple[int, int],
        drop_off: tuple[int, int],
        types: list[str],
        items_by_type: dict[str, list[ItemInfo]],
        grid: Grid,
        blocked: set[tuple[int, int]],
    ) -> list[tuple[tuple[int, int], str]]:
        if not types:
            return []

        def manhattan(a, b):
            return abs(a[0] - b[0]) + abs(a[1] - b[1])

        candidates: list[list[tuple[str, tuple[int, int]]]] = []
        for t in types:
            cands = []
            for item in items_by_type.get(t, []):
                for pp in find_all_pickup_positions(grid, item.pos.as_tuple()):
                    if pp not in blocked:
                        cands.append((item.id, pp))
            if not cands:
                return []
            cands.sort(key=lambda c: manhattan(c[1], drop_off))
            candidates.append(cands[:5])

        # Precompute BFS distances
        all_points: set[tuple[int, int]] = {start, drop_off}
        for cands in candidates:
            for _, pp in cands:
                all_points.add(pp)

        bfs_cache: dict[tuple[tuple[int, int], tuple[int, int]], int] = {}
        for src in all_points:
            for dst in all_points:
                if src == dst:
                    bfs_cache[(src, dst)] = 0
                elif (src, dst) not in bfs_cache:
                    d = bfs_distance(grid, src, dst, blocked=blocked)
                    bfs_cache[(src, dst)] = d
                    bfs_cache[(dst, src)] = d

        n = len(candidates)
        best_cost = 999999
        best_route: list[tuple[tuple[int, int], str]] = []

        for choices in iprod(*candidates):
            pts = [(pp, iid) for iid, pp in choices]
            for perm in permutations(range(n)):
                cost = bfs_cache.get((start, pts[perm[0]][0]), 999999)
                for i in range(n - 1):
                    cost += bfs_cache.get(
                        (pts[perm[i]][0], pts[perm[i + 1]][0]), 999999
                    )
                cost += bfs_cache.get((pts[perm[-1]][0], drop_off), 999999)
                if cost < best_cost:
                    best_cost = cost
                    best_route = [pts[perm[j]] for j in range(n)]

        return best_route

    # -- Greedy fallback ----------------------------------------------------

    def _best_item_to_pick(
        self,
        bot: BotInfo,
        state: GameState,
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
        active_needs: list[str],
        preview_needs: list[str],
    ) -> tuple[Optional[ItemInfo], Optional[tuple[int, int]]]:
        bpos = bot.pos.as_tuple()
        cfg = self.config
        free_slots = 3 - len(bot.inventory)
        active_counter = Counter(active_needs)
        preview_counter = Counter(preview_needs)
        blocked_set = set(item_blocked)
        drop_off_tuple = (state.drop_off[0], state.drop_off[1])
        scored: list[tuple[float, int, str, int, int, ItemInfo]] = []

        for item in state.items:
            utility = 0.0
            if item.type in active_counter and active_counter[item.type] > 0:
                utility = cfg.active_weight
            elif not active_needs and item.type in preview_counter and preview_counter[item.type] > 0:
                utility = cfg.preview_weight
            else:
                continue

            for pp in find_all_pickup_positions(grid, item.pos.as_tuple()):
                if pp in blocked_set:
                    continue
                dist = bfs_distance(grid, bpos, pp, blocked=blocked_set)
                if dist >= 999999:
                    continue
                return_manhattan = abs(pp[0] - drop_off_tuple[0]) + abs(pp[1] - drop_off_tuple[1])
                total_cost = dist + cfg.return_cost_factor * return_manhattan
                score = utility / max(total_cost, 1)
                scored.append((score, dist, item.type, pp[0], pp[1], item))

        if not scored:
            return None, None
        scored.sort(key=lambda s: (-s[0], s[1], s[2], s[3], s[4]))
        best = scored[0]
        return best[5], (best[3], best[4])

    # -- Movement -----------------------------------------------------------

    def _move_toward(
        self,
        bot_id: int,
        start: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        state: GameState,
        item_blocked: frozenset[tuple[int, int]],
    ) -> BotActionCommand:
        if start == goal:
            return BotActionCommand(bot=bot_id, action=BotAction.WAIT)

        blocked: set[tuple[int, int]] = set(item_blocked)
        for b in state.bots:
            if b.id != bot_id:
                blocked.add(b.pos.as_tuple())
        blocked.discard(goal)

        path = bfs_shortest_path(grid, start, goal, blocked)
        if path is None or len(path) < 2:
            path = bfs_shortest_path(grid, start, goal, set(item_blocked) - {goal})
            if path is None or len(path) < 2:
                return self._simple_move(bot_id, start, goal, grid, item_blocked)

        return BotActionCommand(
            bot=bot_id,
            action=action_for_move(start, path[1]),
        )

    @staticmethod
    def _simple_move(
        bot_id: int,
        start: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
    ) -> BotActionCommand:
        sx, sy = start
        gx, gy = goal
        dx, dy = gx - sx, gy - sy
        candidates = []
        if abs(dx) >= abs(dy):
            if dx > 0: candidates.append((sx + 1, sy, BotAction.MOVE_RIGHT))
            elif dx < 0: candidates.append((sx - 1, sy, BotAction.MOVE_LEFT))
            if dy > 0: candidates.append((sx, sy + 1, BotAction.MOVE_DOWN))
            elif dy < 0: candidates.append((sx, sy - 1, BotAction.MOVE_UP))
        else:
            if dy > 0: candidates.append((sx, sy + 1, BotAction.MOVE_DOWN))
            elif dy < 0: candidates.append((sx, sy - 1, BotAction.MOVE_UP))
            if dx > 0: candidates.append((sx + 1, sy, BotAction.MOVE_RIGHT))
            elif dx < 0: candidates.append((sx - 1, sy, BotAction.MOVE_LEFT))
        for nx, ny, action in candidates:
            if grid.is_walkable(nx, ny) and (nx, ny) not in item_blocked:
                return BotActionCommand(bot=bot_id, action=action)
        return BotActionCommand(bot=bot_id, action=BotAction.WAIT)
