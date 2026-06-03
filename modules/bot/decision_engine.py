"""DecisionEngine — per-round orchestrator for the grocery bot swarm."""
from __future__ import annotations

import time
from typing import Optional

from .assignment import Assignment, assign_bots
from .collision import action_for_move, resolve_collisions
from .grid import Grid
from .models import (
    BotAction,
    BotActionCommand,
    BotInfo,
    GameState,
    Pos,
    RoundActions,
)
from .orders import get_active_order, compute_needed_items, items_matching_active
from .pathfinding import astar_path, bfs_distance, bfs_shortest_path, find_all_pickup_positions


class DecisionEngine:
    """Stateless per-round decision maker.

    Call ``decide(state)`` each round.  Returns ``RoundActions`` ready to send.
    """

    def __init__(self, *, use_astar: bool = False, debug: bool = False, verbose: bool = False):
        self.use_astar = use_astar
        self.debug = debug
        self.verbose = verbose  # extra detailed per-round output
        self.last_decision_ms: float = 0.0

    # ── Public API ─────────────────────────────────────────────────────

    def decide(self, state: GameState) -> RoundActions:
        t0 = time.perf_counter()
        grid = Grid(state.grid)
        drop_off = (state.drop_off[0], state.drop_off[1])

        # Items on the map block movement but must NOT be merged into
        # grid._walls — that destroys pickup-position discovery.
        # Instead we thread item_positions as a "blocked" set through
        # pathfinding calls so BFS/A* won't route *through* items,
        # while walkable_neighbors_of() still reports floor tiles next
        # to item shelves correctly.
        item_positions = frozenset(
            (it.position[0], it.position[1]) for it in state.items
        )

        if self.verbose and state.round < 10:
            self._dump_state(state, grid)

        # Get assignments for all bots (clean grid — items NOT in walls)
        assignments = assign_bots(state, grid, item_blocked=item_positions)

        # Convert assignments into concrete single-step actions
        actions: list[BotActionCommand] = []
        # Track planned next positions for collision resolution
        move_plans: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
        stationary: set[tuple[int, int]] = set()

        for bot in state.bots:
            bpos = bot.pos.as_tuple()
            assign = assignments.get(bot.id)
            if assign is None:
                actions.append(BotActionCommand(bot=bot.id, action=BotAction.WAIT))
                stationary.add(bpos)
                continue

            if self.verbose:
                item_info = ""
                if assign.item:
                    item_info = f" item={assign.item.id}({assign.item.type})@{assign.item.pos.as_tuple()}"
                    item_info += f" pickup_pos={assign.pickup_pos}"
                print(f"    Bot{bot.id}@{bpos} inv={bot.inventory} -> "
                      f"{assign.target_type}{item_info} drop_off={assign.drop_off}")

            cmd = self._execute_assignment(bot, assign, grid, state, item_blocked=item_positions)

            if self.verbose:
                print(f"      => action={cmd.action.value}"
                      f"{' item_id=' + cmd.item_id if cmd.item_id else ''}")

            if cmd.action in (BotAction.PICK_UP, BotAction.DROP_OFF, BotAction.WAIT):
                actions.append(cmd)
                stationary.add(bpos)
            else:
                # Movement — compute target cell for collision check
                target = self._move_target(bpos, cmd.action)
                if grid.is_walkable(target[0], target[1]) and target not in item_positions:
                    move_plans.append((bot.id, bpos, target))
                else:
                    # Can't move there - wait instead
                    if self.verbose:
                        print(f"      => BLOCKED at {target}, waiting instead")
                    actions.append(BotActionCommand(bot=bot.id, action=BotAction.WAIT))
                    stationary.add(bpos)

        # Resolve collisions among moving bots
        if move_plans:
            resolved = resolve_collisions(move_plans, stationary)
            for bot_id, cur, desired in move_plans:
                actual = resolved[bot_id]
                if actual == cur:
                    # Blocked — wait
                    actions.append(BotActionCommand(bot=bot_id, action=BotAction.WAIT))
                else:
                    actions.append(BotActionCommand(
                        bot=bot_id,
                        action=action_for_move(cur, actual),
                    ))

        # Sort by bot id for clean output
        actions.sort(key=lambda a: a.bot)

        self.last_decision_ms = (time.perf_counter() - t0) * 1000
        if self.debug:
            action_str = ",".join(a.action.value for a in actions)
            print(f"  R{state.round:3d} score={state.score:3d} "
                  f"dt={self.last_decision_ms:.1f}ms "
                  f"actions=[{action_str}]")

        return RoundActions(actions=actions)

    def _dump_state(self, state: GameState, grid: Grid) -> None:
        """Print a visual grid for first few rounds."""
        drop_off = (state.drop_off[0], state.drop_off[1])
        active = get_active_order(state)
        needed = compute_needed_items(state)

        print(f"\n  === Round {state.round} | Score {state.score} | "
              f"Grid {state.grid.width}x{state.grid.height} ===")
        print(f"  Drop-off: {drop_off}")
        print(f"  Active order: {active.id if active else 'None'} "
              f"needed={needed}")
        for b in state.bots:
            print(f"  Bot{b.id} @ {b.pos.as_tuple()} inv={b.inventory}")
        print(f"  Items on map: {len(state.items)}")
        for it in state.items[:8]:
            is_wall = grid.is_wall(it.position[0], it.position[1])
            neighbors = grid.walkable_neighbors_of(it.pos)
            print(f"    {it.id} ({it.type}) @ {it.pos.as_tuple()} "
                  f"is_wall={is_wall} walkable_neighbors={neighbors}")

        # Print ASCII grid
        print("  Grid:")
        for y in range(state.grid.height):
            row = "  "
            for x in range(state.grid.width):
                pos = (x, y)
                if any(b.pos.as_tuple() == pos for b in state.bots):
                    row += "B"
                elif pos == drop_off:
                    row += "D"
                elif any(it.pos.as_tuple() == pos for it in state.items):
                    row += "i"
                elif grid.is_wall(x, y):
                    row += "#"
                else:
                    row += "."
                row += " "
            print(row)

    # ── Internal helpers ───────────────────────────────────────────────

    def _execute_assignment(
        self,
        bot: BotInfo,
        assign: Assignment,
        grid: Grid,
        state: GameState,
        *,
        item_blocked: frozenset[tuple[int, int]] = frozenset(),
    ) -> BotActionCommand:
        bpos = bot.pos.as_tuple()
        drop_off = (state.drop_off[0], state.drop_off[1])

        # ── OPPORTUNISTIC PICKUP ───────────────────────────────────
        # Before following assignment, check if bot is adjacent to ANY
        # needed item right now.  This catches edge cases where the
        # assignment picked a different item but we're next to one.
        if len(bot.inventory) < 3:
            needed = compute_needed_items(state)
            for item in state.items:
                if item.type in needed:
                    ipos = item.pos.as_tuple()
                    if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
                        return BotActionCommand(
                            bot=bot.id,
                            action=BotAction.PICK_UP,
                            item_id=item.id,
                        )

        # ── OPPORTUNISTIC DROP-OFF ─────────────────────────────────
        # If bot is standing ON drop-off with matching items, deliver now
        if bpos == drop_off and bot.inventory:
            matching = items_matching_active(bot, state)
            if matching:
                return BotActionCommand(bot=bot.id, action=BotAction.DROP_OFF)

        # ── DELIVER ────────────────────────────────────────────────
        if assign.target_type == "deliver":
            if bpos == drop_off:
                # Check if we have matching items
                matching = items_matching_active(bot, state)
                if matching:
                    return BotActionCommand(bot=bot.id, action=BotAction.DROP_OFF)
                else:
                    # Have inventory but nothing matches — go pick needed items
                    needed = compute_needed_items(state)
                    if needed and len(bot.inventory) < 3:
                        # Find nearest needed item to go pick
                        best_item = None
                        best_dist = 999999
                        best_pp = None
                        for item in state.items:
                            if item.type in needed:
                                pps = find_all_pickup_positions(grid, item.pos.as_tuple())
                                for pp in pps:
                                    d = bfs_distance(grid, bpos, pp, blocked=set(item_blocked))
                                    if d < best_dist:
                                        best_dist = d
                                        best_item = item
                                        best_pp = pp
                        if best_pp:
                            return self._move_toward(bot.id, bpos, best_pp, grid, state, item_blocked=item_blocked)
                    return BotActionCommand(bot=bot.id, action=BotAction.WAIT)
            # Move toward drop-off
            return self._move_toward(bot.id, bpos, drop_off, grid, state, item_blocked=item_blocked)

        # ── PICK ITEM ──────────────────────────────────────────────
        if assign.target_type in ("pick_item", "pre_pick") and assign.item:
            item_pos = assign.item.pos.as_tuple()
            # Check if already adjacent → pick up
            if abs(bpos[0] - item_pos[0]) + abs(bpos[1] - item_pos[1]) == 1:
                return BotActionCommand(
                    bot=bot.id,
                    action=BotAction.PICK_UP,
                    item_id=assign.item.id,
                )
            # Move toward pickup position (walkable cell adjacent to item shelf)
            target = assign.pickup_pos or bpos
            return self._move_toward(bot.id, bpos, target, grid, state, item_blocked=item_blocked)

        # ── IDLE — if bot has matching items, go deliver ──────────
        if bot.inventory and items_matching_active(bot, state):
            return self._move_toward(bot.id, bpos, drop_off, grid, state, item_blocked=item_blocked)
        # Bot idle with non-matching inventory (or empty) — go pick needed items
        if len(bot.inventory) < 3:
            needed = compute_needed_items(state)
            if needed:
                best_dist = 999999
                best_pp = None
                for item in state.items:
                    if item.type in needed:
                        pps = find_all_pickup_positions(grid, item.pos.as_tuple())
                        for pp in pps:
                            d = bfs_distance(grid, bpos, pp, blocked=set(item_blocked))
                            if d < best_dist:
                                best_dist = d
                                best_pp = pp
                if best_pp:
                    return self._move_toward(bot.id, bpos, best_pp, grid, state, item_blocked=item_blocked)
        return BotActionCommand(bot=bot.id, action=BotAction.WAIT)

    def _move_toward(
        self,
        bot_id: int,
        start: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        state: GameState,
        *,
        item_blocked: frozenset[tuple[int, int]] = frozenset(),
    ) -> BotActionCommand:
        """Compute one-step move toward *goal* using pathfinding."""
        if start == goal:
            return BotActionCommand(bot=bot_id, action=BotAction.WAIT)

        # Build blocked set from other bot positions + item positions
        blocked: set[tuple[int, int]] = set(item_blocked)
        for b in state.bots:
            if b.id != bot_id:
                blocked.add(b.pos.as_tuple())
        # Don't block the goal itself
        blocked.discard(goal)

        pathfn = astar_path if self.use_astar else bfs_shortest_path
        path = pathfn(grid, start, goal, blocked)

        if path is None or len(path) < 2:
            # Try without other-bot blocking (they might move), but keep items blocked
            path = pathfn(grid, start, goal, set(item_blocked) - {goal})
            if path is None or len(path) < 2:
                # Fallback: simple manhattan move
                return self._simple_move(bot_id, start, goal, grid, item_blocked=item_blocked)

        next_cell = path[1]
        return BotActionCommand(
            bot=bot_id,
            action=action_for_move(start, next_cell),
        )

    def _simple_move(
        self,
        bot_id: int,
        start: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        *,
        item_blocked: frozenset[tuple[int, int]] = frozenset(),
    ) -> BotActionCommand:
        """Fallback: take manhattan step toward goal, preferring bigger axis delta."""
        sx, sy = start
        gx, gy = goal
        dx, dy = gx - sx, gy - sy

        # Try the bigger axis first
        candidates = []
        if abs(dx) >= abs(dy):
            if dx > 0:
                candidates.append((sx + 1, sy, BotAction.MOVE_RIGHT))
            elif dx < 0:
                candidates.append((sx - 1, sy, BotAction.MOVE_LEFT))
            if dy > 0:
                candidates.append((sx, sy + 1, BotAction.MOVE_DOWN))
            elif dy < 0:
                candidates.append((sx, sy - 1, BotAction.MOVE_UP))
        else:
            if dy > 0:
                candidates.append((sx, sy + 1, BotAction.MOVE_DOWN))
            elif dy < 0:
                candidates.append((sx, sy - 1, BotAction.MOVE_UP))
            if dx > 0:
                candidates.append((sx + 1, sy, BotAction.MOVE_RIGHT))
            elif dx < 0:
                candidates.append((sx - 1, sy, BotAction.MOVE_LEFT))

        for nx, ny, action in candidates:
            if grid.is_walkable(nx, ny) and (nx, ny) not in item_blocked:
                return BotActionCommand(bot=bot_id, action=action)

        return BotActionCommand(bot=bot_id, action=BotAction.WAIT)

    @staticmethod
    def _move_target(pos: tuple[int, int], action: BotAction) -> tuple[int, int]:
        x, y = pos
        if action == BotAction.MOVE_UP:
            return (x, y - 1)
        if action == BotAction.MOVE_DOWN:
            return (x, y + 1)
        if action == BotAction.MOVE_LEFT:
            return (x - 1, y)
        if action == BotAction.MOVE_RIGHT:
            return (x + 1, y)
        return pos
