"""Task assignment — assign items to bots using greedy nearest-first."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .grid import Grid
from .models import GameState, ItemInfo, Pos
from .orders import compute_needed_items, compute_preview_items, items_matching_active
from .pathfinding import bfs_distance, find_all_pickup_positions


@dataclass
class Assignment:
    """What a bot should be doing this round."""
    target_type: str          # "pick_item" | "deliver" | "idle" | "pre_pick"
    item: Optional[ItemInfo] = None
    pickup_pos: Optional[tuple[int, int]] = None  # walkable cell near shelf
    drop_off: Optional[tuple[int, int]] = None


def assign_bots(state: GameState, grid: Grid, *, item_blocked: frozenset[tuple[int, int]] = frozenset()) -> dict[int, Assignment]:
    """Greedy assignment: nearest unassigned needed item per bot.

    Priority order:
    1. Bots on drop-off with matching items → deliver
    2. Bots with matching items in inventory → go to drop-off
    3. Assign nearest needed item to nearest idle bot
    4. If nothing to do, go to drop-off or wait
    """
    assignments: dict[int, Assignment] = {}
    drop_off = (state.drop_off[0], state.drop_off[1])

    needed_types = compute_needed_items(state)
    preview_types = compute_preview_items(state)

    # Items available on the map, indexed by type
    available_items: list[ItemInfo] = list(state.items)
    assigned_item_ids: set[str] = set()

    # Track which bots are already assigned
    unassigned_bots = list(state.bots)

    # ── Phase 1: Bots at drop-off with MATCHING inventory → deliver ───
    still_unassigned = []
    for bot in unassigned_bots:
        bpos = bot.pos.as_tuple()
        if bpos == drop_off and items_matching_active(bot, state):
            assignments[bot.id] = Assignment(target_type="deliver", drop_off=drop_off)
        else:
            still_unassigned.append(bot)
    unassigned_bots = still_unassigned

    # ── Phase 2: Bots with full inventory AND matching items → deliver ─
    still_unassigned = []
    for bot in unassigned_bots:
        if len(bot.inventory) >= 3 and items_matching_active(bot, state):
            assignments[bot.id] = Assignment(target_type="deliver", drop_off=drop_off)
        else:
            still_unassigned.append(bot)
    unassigned_bots = still_unassigned

    # ── Phase 3: Bots with any matching inventory items and no more
    #             needed items on map → go to drop-off ───────────────
    # (handled later if nothing to pick)

    # ── Phase 4: Greedy nearest-item assignment ──────────────────────
    still_unassigned = []
    for bot in sorted(unassigned_bots, key=lambda b: b.id):
        bpos = bot.pos.as_tuple()
        best_item: Optional[ItemInfo] = None
        best_dist = 999999
        best_pickup: Optional[tuple[int, int]] = None

        for item in available_items:
            if item.id in assigned_item_ids:
                continue
            # Only pick items that match needed or (lower priority) preview
            if item.type not in needed_types and item.type not in preview_types:
                continue
            # Prefer active-order items over preview
            priority_bonus = 0 if item.type in needed_types else 1000

            # Find best pickup position (walkable cell adjacent to shelf)
            pickup_positions = find_all_pickup_positions(grid, item.pos.as_tuple())
            for pp in pickup_positions:
                dist = bfs_distance(grid, bpos, pp, blocked=set(item_blocked)) + priority_bonus
                if dist < best_dist:
                    best_dist = dist
                    best_item = item
                    best_pickup = pp

        if best_item is not None:
            target_type = "pick_item" if best_item.type in needed_types else "pre_pick"
            assignments[bot.id] = Assignment(
                target_type=target_type,
                item=best_item,
                pickup_pos=best_pickup,
            )
            assigned_item_ids.add(best_item.id)
            if best_item.type in needed_types:
                needed_types.remove(best_item.type)
            elif best_item.type in preview_types:
                preview_types.remove(best_item.type)
        else:
            still_unassigned.append(bot)

    unassigned_bots = still_unassigned

    # ── Phase 5: Remaining bots with MATCHING inventory → deliver ───
    still_unassigned = []
    for bot in unassigned_bots:
        if bot.inventory and items_matching_active(bot, state):
            assignments[bot.id] = Assignment(target_type="deliver", drop_off=drop_off)
        else:
            still_unassigned.append(bot)
    unassigned_bots = still_unassigned

    # ── Phase 6: Truly idle bots → wait near drop-off ───────────────
    for bot in unassigned_bots:
        assignments[bot.id] = Assignment(target_type="idle")

    return assignments
