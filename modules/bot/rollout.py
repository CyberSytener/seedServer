"""Lightweight forward model and rollout evaluator for the planner.

Used for rolling-horizon lookahead: evaluates candidate planner strategies
by simulating a few rounds ahead and picking the highest-scoring variant.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import (
    BotAction,
    BotInfo,
    GameState,
    GridInfo,
    ItemInfo,
    OrderInfo,
    OrderStatus,
    RoundActions,
)


class MiniSim:
    """Minimal forward model for evaluating planner strategies.

    Implements the same game rules as the NMiAI server:
    - Sequential bot-ID collision processing
    - Pickup / drop-off / order completion / auto-delivery
    - Does NOT consume items on pickup (items are permanent on shelves)
    """

    __slots__ = (
        "grid", "drop_off", "max_rounds", "num_bots", "all_orders",
        "item_defs", "walls", "item_positions",
        "round", "score", "bot_positions", "bot_inventories",
        "_order_idx", "_order_deliveries",
    )

    def __init__(self, state: GameState, all_orders: list[dict]):
        self.grid = state.grid
        self.drop_off = [state.drop_off[0], state.drop_off[1]]
        self.max_rounds = state.max_rounds
        self.num_bots = len(state.bots)
        self.all_orders = all_orders

        # Item data  (static — items are never consumed)
        self.item_defs: list[dict] = [
            {"id": it.id, "type": it.type, "position": [it.position[0], it.position[1]]}
            for it in state.items
        ]

        # Pre-computed walkability sets
        self.walls: frozenset[tuple[int, int]] = frozenset(
            (w[0], w[1]) for w in state.grid.walls
        )
        self.item_positions: frozenset[tuple[int, int]] = frozenset(
            (it.position[0], it.position[1]) for it in state.items
        )

        # Mutable game state
        self.round = state.round
        self.score = state.score
        self.bot_positions: list[list[int]] = [
            [b.position[0], b.position[1]] for b in state.bots
        ]
        self.bot_inventories: list[list[str]] = [
            list(b.inventory) for b in state.bots
        ]

        # --- Restore order progress ---
        self._order_idx = 0
        self._order_deliveries: dict[str, list[str]] = {}

        for o in state.orders:
            if o.status == OrderStatus.ACTIVE:
                try:
                    self._order_idx = int(o.id.split("_")[1])
                except (ValueError, IndexError):
                    pass
                self._order_deliveries[o.id] = list(o.items_delivered)
            elif o.status == OrderStatus.PREVIEW:
                self._order_deliveries[o.id] = list(o.items_delivered)

        # Earlier orders are fully complete
        for i in range(self._order_idx):
            oid = f"order_{i}"
            if i < len(self.all_orders):
                self._order_deliveries[oid] = list(
                    self.all_orders[i].get("items_required", [])
                )

        # Later orders start with empty deliveries
        for i in range(self._order_idx + 2, len(self.all_orders)):
            self._order_deliveries.setdefault(f"order_{i}", [])

    # ── Fast deep-copy ─────────────────────────────────────────────────

    def clone(self) -> "MiniSim":
        """Return an independent copy (for branching rollout)."""
        c = object.__new__(MiniSim)
        c.grid = self.grid                       # immutable, shared
        c.drop_off = list(self.drop_off)
        c.max_rounds = self.max_rounds
        c.num_bots = self.num_bots
        c.all_orders = self.all_orders            # immutable, shared
        c.item_defs = self.item_defs              # immutable, shared
        c.walls = self.walls                      # frozen, shared
        c.item_positions = self.item_positions    # frozen, shared
        c.round = self.round
        c.score = self.score
        c.bot_positions = [list(p) for p in self.bot_positions]
        c.bot_inventories = [list(inv) for inv in self.bot_inventories]
        c._order_idx = self._order_idx
        c._order_deliveries = {k: list(v) for k, v in self._order_deliveries.items()}
        return c

    # ── Build a GameState (for feeding to the planner) ─────────────────

    def get_state(self) -> GameState:
        orders: list[OrderInfo] = []
        if self._order_idx < len(self.all_orders):
            o = self.all_orders[self._order_idx]
            orders.append(OrderInfo(
                id=o["id"],
                items_required=list(o["items_required"]),
                items_delivered=list(self._order_deliveries.get(o["id"], [])),
                complete=False,
                status=OrderStatus.ACTIVE,
            ))
        if self._order_idx + 1 < len(self.all_orders):
            o = self.all_orders[self._order_idx + 1]
            orders.append(OrderInfo(
                id=o["id"],
                items_required=list(o["items_required"]),
                items_delivered=list(self._order_deliveries.get(o["id"], [])),
                complete=False,
                status=OrderStatus.PREVIEW,
            ))

        items = [
            ItemInfo(id=it["id"], type=it["type"], position=it["position"])
            for it in self.item_defs
        ]
        bots = [
            BotInfo(
                id=i,
                position=list(self.bot_positions[i]),
                inventory=list(self.bot_inventories[i]),
            )
            for i in range(self.num_bots)
        ]
        return GameState(
            type="game_state",
            round=self.round,
            max_rounds=self.max_rounds,
            grid=self.grid,
            bots=bots,
            items=items,
            orders=orders,
            drop_off=list(self.drop_off),
            score=self.score,
        )

    # ── Step: apply actions and advance one round ──────────────────────

    def step(self, actions: RoundActions) -> None:
        move_targets: dict[int, tuple[int, int]] = {}
        non_move: dict[int, Any] = {}

        for act in actions.actions:
            bid = act.bot
            if act.action in (
                BotAction.MOVE_UP, BotAction.MOVE_DOWN,
                BotAction.MOVE_LEFT, BotAction.MOVE_RIGHT,
            ):
                dx, dy = _DELTAS[act.action]
                nx, ny = self.bot_positions[bid][0] + dx, self.bot_positions[bid][1] + dy
                if self._walkable(nx, ny):
                    move_targets[bid] = (nx, ny)
            elif act.action in (BotAction.PICK_UP, BotAction.DROP_OFF):
                non_move[bid] = act

        # Sequential collision (server model: ascending bot-ID order)
        occupied: set[tuple[int, int]] = set()
        for i in range(self.num_bots):
            occupied.add((self.bot_positions[i][0], self.bot_positions[i][1]))

        for bid in sorted(move_targets):
            tgt = move_targets[bid]
            cur = (self.bot_positions[bid][0], self.bot_positions[bid][1])
            if tgt in occupied and tgt != cur:
                pass                                  # blocked — stay
            else:
                occupied.discard(cur)
                self.bot_positions[bid][0], self.bot_positions[bid][1] = tgt
                occupied.add(tgt)

        for bid, act in non_move.items():
            if act.action == BotAction.PICK_UP:
                self._try_pickup(bid, act.item_id)
            elif act.action == BotAction.DROP_OFF:
                self._try_dropoff(bid)

        self.round += 1

    # ── Internals ──────────────────────────────────────────────────────

    def _walkable(self, x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= self.grid.width or y >= self.grid.height:
            return False
        return (x, y) not in self.walls and (x, y) not in self.item_positions

    def _try_pickup(self, bid: int, item_id: str | None) -> None:
        if not item_id or len(self.bot_inventories[bid]) >= 3:
            return
        bpos = self.bot_positions[bid]
        for it in self.item_defs:
            if it["id"] == item_id:
                ipos = it["position"]
                if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) <= 1:
                    self.bot_inventories[bid].append(it["type"])
                return

    def _try_dropoff(self, bid: int) -> None:
        bpos = self.bot_positions[bid]
        if bpos[0] != self.drop_off[0] or bpos[1] != self.drop_off[1]:
            return
        if not self.bot_inventories[bid] or self._order_idx >= len(self.all_orders):
            return

        active = self.all_orders[self._order_idx]
        oid = active["id"]
        remaining = list(active["items_required"])
        for d in self._order_deliveries.get(oid, []):
            if d in remaining:
                remaining.remove(d)

        new_inv = list(self.bot_inventories[bid])
        for item_type in list(new_inv):
            if item_type in remaining:
                remaining.remove(item_type)
                new_inv.remove(item_type)
                self._order_deliveries.setdefault(oid, []).append(item_type)
                self.score += 1
        self.bot_inventories[bid] = new_inv

        if not remaining:
            self.score += 5
            self._order_idx += 1
            if self._order_idx < len(self.all_orders):
                self._auto_deliver()

    def _auto_deliver(self) -> None:
        """Auto-deliver matching items from all bots at drop-off."""
        if self._order_idx >= len(self.all_orders):
            return
        active = self.all_orders[self._order_idx]
        oid = active["id"]
        remaining = list(active["items_required"])
        for d in self._order_deliveries.get(oid, []):
            if d in remaining:
                remaining.remove(d)

        for bid in range(self.num_bots):
            bp = self.bot_positions[bid]
            if bp[0] != self.drop_off[0] or bp[1] != self.drop_off[1]:
                continue
            new_inv = list(self.bot_inventories[bid])
            for item_type in list(new_inv):
                if item_type in remaining:
                    remaining.remove(item_type)
                    new_inv.remove(item_type)
                    self._order_deliveries.setdefault(oid, []).append(item_type)
                    self.score += 1
            self.bot_inventories[bid] = new_inv

        if not remaining:
            self.score += 5
            self._order_idx += 1
            if self._order_idx < len(self.all_orders):
                self._auto_deliver()


_DELTAS = {
    BotAction.MOVE_UP: (0, -1),
    BotAction.MOVE_DOWN: (0, 1),
    BotAction.MOVE_LEFT: (-1, 0),
    BotAction.MOVE_RIGHT: (1, 0),
}
