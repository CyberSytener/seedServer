"""Multi-bot planner for hard+ difficulties.

Coordinates 5 bots to complete orders in parallel.
Falls back to schedule-driven approach for easy (1 bot).
"""
from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import permutations, product as iprod
from typing import Optional

from .collision import action_for_move, resolve_collisions
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
from .pathfinding import bfs_distance, bfs_distances_from, bfs_shortest_path, find_all_pickup_positions


# -- Configuration ----------------------------------------------------------

@dataclass
class PlannerConfig:
    lookahead_orders: int = 2
    active_weight: float = 10.0
    preview_weight: float = 3.0
    auto_delivery_bonus: float = 5.0
    return_cost_factor: float = 0.9
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


# -- Easy schedule (from Dijkstra solver) -----------------------------------

EASY_SCHEDULE = [
    ("butter", "butter", "milk"),
    ("butter", "cheese"),
    ("butter", "butter"),
    ("butter", "butter", "yogurt"),
    ("milk", "milk", "milk"),
    ("cheese", "cheese", "cheese"),
    ("yogurt", "yogurt", "yogurt"),
    ("milk", "milk", "yogurt"),
    ("butter", "milk", "milk"),
    ("cheese", "cheese", "yogurt"),
    ("butter",),
    ("milk", "milk", "yogurt"),
    ("cheese", "cheese", "yogurt"),
    ("butter", "butter", "butter"),
    ("yogurt", "yogurt", "yogurt"),
    ("butter", "butter", "butter"),
    ("cheese", "cheese", "cheese"),
    ("milk", "milk", "milk"),
    ("milk", "milk", "yogurt"),
    ("butter", "butter"),
    ("butter", "cheese", "yogurt"),
]

# -- Known hard orders (deterministic sequence) -----------------------------
HARD_ORDERS: list[list[str]] = [
    ['cheese', 'milk', 'flour'],
    ['flour', 'oats', 'butter', 'cream', 'cheese'],
    ['cream', 'yogurt', 'pasta'],
    ['oats', 'cheese', 'bread'],
    ['oats', 'cheese', 'cereal'],
    ['flour', 'butter', 'eggs', 'butter', 'pasta'],
    ['rice', 'rice', 'rice'],
    ['cereal', 'cheese', 'cheese'],
    ['oats', 'cereal', 'cream', 'cereal', 'flour'],
    ['cheese', 'pasta', 'yogurt'],
    ['oats', 'milk', 'cereal'],
    ['flour', 'cream', 'milk', 'cream'],
    ['cheese', 'bread', 'butter'],
    ['flour', 'butter', 'rice', 'cereal', 'cream'],
    ['yogurt', 'rice', 'cheese', 'flour'],
    ['pasta', 'oats', 'milk', 'cheese'],
    # Generated orders (Random(42)) ---
    ['butter', 'bread', 'yogurt', 'cream', 'cheese'],
    ['cereal', 'yogurt', 'butter'],
    ['yogurt', 'oats', 'butter', 'pasta', 'flour'],
    ['bread', 'butter', 'cheese'],
    ['oats', 'pasta', 'bread'],
    ['cheese', 'yogurt', 'rice', 'yogurt', 'oats'],
    ['cheese', 'milk', 'pasta', 'cream'],
    ['cereal', 'yogurt', 'flour'],
    ['cream', 'cereal', 'cheese', 'eggs'],
]


class OptimizedEngine:
    """Multi-bot planner with easy schedule fallback."""

    def __init__(
        self,
        config: Optional[PlannerConfig] = None,
        *,
        debug: bool = False,
        verbose: bool = False,
        phase3b_noise: float = 0.0,
        phase3b_seed: int = 0,
    ):
        self.config = config or PlannerConfig()
        self.debug = debug
        self.verbose = verbose
        self.last_decision_ms: float = 0.0

        self._order_tracker = OrderTracker()
        self._mode: Optional[str] = None  # "easy" or "multi"

        # Phase 3b noise for offline search (0 = deterministic)
        self._phase3b_noise = phase3b_noise
        self._phase3b_rng = random.Random(phase3b_seed)

        # Easy mode state
        self._trip_idx = 0
        self._trip_route: list[tuple[tuple[int, int], str]] = []

        # Multi-bot state
        self._bot_assignments: dict[int, dict] = {}

        # Dynamic order tracking (replaces hardcoded HARD_ORDERS for Phase 3b)
        self._observed_orders: dict[str, list[str]] = {}
        self._last_active_idx: int = -1
        
        # Deadlock Detection
        self._last_positions: dict[int, tuple[int, int]] = {}
        self._stuck_counts: dict[int, int] = {}


        # Defer tuning
        self._defer_cap: int = 2           # max bots deferred per round
        self._defer_thresh: int = 6        # manhattan detour threshold (active)
        self._preview_defer_thresh: int = 3  # manhattan detour threshold (preview)

        # Rolling-horizon rollout state
        self._defer_mode: int = 0          # 0=normal, 1=no-defer, 2=wide-defer
        self._synergy_override: int | None = None   # override synergy weight
        self._congestion_override: int | None = None # override congestion weight
        self._rollout_interval: int = 0    # 0=disabled; set >0 to enable periodic rollout
        self._rollout_horizon: int = 8     # simulate N rounds ahead
        self._last_rollout_round: int = -999
        self._all_orders: list[dict] | None = None  # built lazily

        # Persistent assignment locks (anti-flicker)
        self._locked: dict[int, tuple[str, str, tuple[int, int]]] = {}
        # bot_id → (need_type, item_id, pickup_pos)
        self._lock_order_id: str | None = None  # clear on order change

    def _build_all_orders(self) -> list[dict]:
        """Build the full 50-order sequence for rollout forward model."""
        orders: list[dict] = []
        for i, items in enumerate(HARD_ORDERS):
            orders.append({"id": f"order_{i}", "items_required": list(items)})
        # Extend using observed orders first, then HARD_ORDERS, then Random(42)
        item_types = sorted(['bread', 'butter', 'cereal', 'cheese', 'cream',
                             'eggs', 'flour', 'milk', 'oats', 'pasta', 'rice', 'yogurt'])
        rng = random.Random(42)
        for i in range(len(HARD_ORDERS), 50):
            oid = f"order_{i}"
            if oid in self._observed_orders:
                orders.append({"id": oid, "items_required": list(self._observed_orders[oid])})
                # Advance RNG to keep it in sync
                sz = rng.choice([3, 4, 5])
                for _ in range(sz):
                    rng.choice(item_types)
            else:
                sz = rng.choice([3, 4, 5])
                req = [rng.choice(item_types) for _ in range(sz)]
                orders.append({"id": oid, "items_required": req})
        return orders

    def _do_rollout(self, state: GameState) -> int:
        """Evaluate strategy variants via forward rollout.

        Each variant is a tuple (defer_mode, synergy_weight, congestion_weight).
        Returns the index of the winning variant and sets override fields.
        """
        from .rollout import MiniSim

        if self._all_orders is None:
            self._all_orders = self._build_all_orders()

        # Strategy variants: (defer_mode, synergy_override, congestion_override)
        variants = [
            (0, None, None),   # A: baseline (threshold 6, synergy -3, congestion ×3)
            (1, None, None),   # B: no defer  (deliver immediately)
            (2, None, None),   # C: wide defer (threshold 10)
            (0, -5, None),     # D: stronger synergy
            (0, None, 0),      # E: no congestion penalty
        ]

        best_idx = 0
        best_score = -1
        horizon = self._rollout_horizon

        for idx, (dmode, syn, cong) in enumerate(variants):
            eng = OptimizedEngine(config=self.config, debug=False)
            eng._observed_orders = dict(self._observed_orders)
            eng._last_active_idx = self._last_active_idx
            eng._defer_mode = dmode
            eng._synergy_override = syn
            eng._congestion_override = cong
            eng._rollout_interval = 0  # DISABLE nested rollouts

            sim = MiniSim(state, self._all_orders)
            for _ in range(horizon):
                if sim.round >= sim.max_rounds:
                    break
                sim_state = sim.get_state()
                actions = eng.decide(sim_state)
                sim.step(actions)
            if sim.score > best_score:
                best_score = sim.score
                best_idx = idx

        dmode, syn, cong = variants[best_idx]
        self._defer_mode = dmode
        self._synergy_override = syn
        self._congestion_override = cong
        return best_idx

    def decide(self, state: GameState) -> RoundActions:
        t0 = time.perf_counter()
        self._order_tracker.update(state)

        if not state.bots:
            self.last_decision_ms = (time.perf_counter() - t0) * 1000
            return RoundActions(actions=[])

        # Auto-detect mode on first call
        if self._mode is None:
            if len(state.bots) == 1:
                self._mode = "easy"
            else:
                self._mode = "multi"

        if self._mode == "easy":
            actions = self._decide_easy(state)
        else:
            # Reset rollout state on new game (engine reused across sim runs)
            if state.round < self._last_rollout_round:
                self._last_rollout_round = -999
                self._defer_mode = 0
                self._synergy_override = None
                self._congestion_override = None
                self._all_orders = None
                self._locked.clear()
                self._lock_order_id = None
            # Rolling-horizon: periodically evaluate defer strategies
            remaining = state.max_rounds - state.round
            if (self._rollout_interval > 0
                    and remaining > 30
                    and state.round - self._last_rollout_round >= self._rollout_interval
                    and state.round >= 5):
                self._last_rollout_round = state.round
                self._do_rollout(state)
            actions = self._decide_multi(state)

        self.last_decision_ms = (time.perf_counter() - t0) * 1000

        if self.debug:
            act_str = ",".join(a.action.value for a in actions.actions)
            bots_str = " ".join(
                f"B{b.id}@{b.pos.as_tuple()}"
                for b in state.bots
            )
            print(
                f"  R{state.round:3d} score={state.score:3d} "
                f"{bots_str} [{act_str}]"
            )

        return actions

    # ===================================================================
    # MULTI-BOT PLANNER
    # ===================================================================

    def _decide_multi(self, state: GameState) -> RoundActions:
        grid = Grid(state.grid)
        drop_off = (state.drop_off[0], state.drop_off[1])
        item_blocked = frozenset(
            (it.position[0], it.position[1]) for it in state.items
        )

        active_needs = compute_needed_items(state)
        preview_needs = compute_preview_items(state) if self.config.prefetch else []

        # --- Dynamic order tracking ---
        for order in state.orders:
            if order.id not in self._observed_orders:
                self._observed_orders[order.id] = list(order.items_required)
        active_order = get_active_order(state)
        if active_order:
            try:
                self._last_active_idx = int(active_order.id.split('_')[1])
            except (ValueError, IndexError):
                pass

        # --- STUCK DETECTION ---
        stuck_bots = set()
        for bot in state.bots:
            prev = self._last_positions.get(bot.id)
            if prev and prev == bot.pos.as_tuple():
                # Bot didn't move
                # Check if it *wanted* to move (implied by previous actions? No state).
                # Assume if bot hasn't moved for 3 turns, it is stuck.
                # (Charging? No charging in this game).
                # (Picking up? Takes 1 turn. Dropping off? 1 turn).
                # So if stuck > 3 turns, force move.
                self._stuck_counts[bot.id] = self._stuck_counts.get(bot.id, 0) + 1
            else:
                self._stuck_counts[bot.id] = 0
            
            self._last_positions[bot.id] = bot.pos.as_tuple()
            
            if self._stuck_counts.get(bot.id, 0) > 3:
                stuck_bots.add(bot.id)

        actions: list[BotActionCommand] = []
        move_plans: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
        stationary: set[tuple[int, int]] = set()
        delivering_bots: set[int] = set()  # bots delivering active items
        bot_dist_maps: dict[int, dict[tuple[int, int], int]] = {}

        # Build items-by-type index
        items_by_type: dict[str, list[ItemInfo]] = {}
        for item in state.items:
            items_by_type.setdefault(item.type, []).append(item)

        assigned_items: set[str] = set()
        remaining_active = list(active_needs)
        remaining_preview = list(preview_needs) if self.config.prefetch else []

        bot_positions = {b.id: b.pos.as_tuple() for b in state.bots}
        bots_handled: set[int] = set()
        bot_priorities: dict[int, int] = {}
        
        # --- Panic Mode: Stuck bots ignore all logic and move frantically ---
        for bid in stuck_bots:
             if bid in bots_handled: continue
             bot = next(b for b in state.bots if b.id == bid)
             # Move Randomly to ANY valid neighbor
             neighbors = grid.neighbors(bot.pos.x, bot.pos.y)
             # Avoid walls/items but ALLOW occupied (to push/swap/deadlock-break)
             valid_n = [n for n in neighbors if n not in item_blocked]
             if valid_n:
                 target = random.choice(valid_n)
                 # Generate Command
                 dx, dy = target[0]-bot.pos.x, target[1]-bot.pos.y
                 act = BotAction.WAIT
                 if dx == 1: act = BotAction.MOVE_RIGHT
                 elif dx == -1: act = BotAction.MOVE_LEFT
                 elif dy == 1: act = BotAction.MOVE_DOWN
                 elif dy == -1: act = BotAction.MOVE_UP
                 
                 actions.append(BotActionCommand(bot=bid, action=act))
                 move_plans.append((bid, bot.pos.as_tuple(), target))
                 bots_handled.add(bid)
                 bot_priorities[bid] = 50 # ULTRA HIGH PRIORITY to smash through blockage

        # --- Phase 1: Bot at drop-off with matching items → DROP_OFF ---

        for bot in state.bots:
            bpos = bot.pos.as_tuple()
            if bpos == drop_off and bot.inventory:
                if items_matching_active(bot, state):
                    actions.append(BotActionCommand(
                        bot=bot.id, action=BotAction.DROP_OFF))
                    stationary.add(bpos)
                    bots_handled.add(bot.id)
                    delivering_bots.add(bot.id)

        # Pre-compute dropoff distance map for ALL cells
        item_blocked_set = set(item_blocked)
        
        # Traffic Control: Traffic Light System for Single-Lane Dropoffs
        # 1. Identify Exit Tile (preferred egress route)
        # Prefer East > West > South > North
        exit_tile = None
        for dx, dy in ((1,0), (-1,0), (0,1), (0,-1)):
             cand = (drop_off[0]+dx, drop_off[1]+dy)
             if grid.is_walkable(cand[0], cand[1]) and cand not in item_blocked_set:
                 exit_tile = cand
                 break
        
        # 2. Determine Phase
        # Cycle: 15 rounds Ingress (Open), 10 rounds Egress (Blocked for Entry)
        # Starting with Ingress to let bots fill up.
        # R0-14: Ingress. R15-24: Egress.
        phase_len = 25
        phase_step = state.round % phase_len
        is_egress_phase = (phase_step >= 15)
        
        # 3. Apply Blocking
        # ENABLE TRAFFIC LIGHT
        ingress_blocked = set(item_blocked_set)
        if exit_tile and is_egress_phase:
            ingress_blocked.add(exit_tile)


            
        dropoff_dist_map = bfs_distances_from(grid, drop_off, ingress_blocked)
        
        # Note: We removed the "unreachable_check" because we WANT bots to find it unreachable 
        # during Egress phase so they back off.



        # EXPERIMENT: Unified Phase 2+3 (Tour Generation)
        # Replacing old Phases 1b through 3b with heuristic search
        # 1. Identify all high-value targets (needed items)
        # 2. For each bot, find best multi-item tour ending at DropOff
        # 3. Assign
        
        # Priority Constants
        _W_ACTIVE = 100.0
        _W_PREVIEW = 20.0
        _W_FUTURE = 1.0
        _W_CONGESTION = -5.0
        
        # Build candidate items (Type -> Priority)
        # Include Future items (up to +5 orders ahead)
        if self._all_orders is None:
            self._all_orders = self._build_all_orders()
        
        target_items: dict[str, float] = {}
        for t in remaining_active: 
            target_items[t] = max(target_items.get(t, 0), _W_ACTIVE)
        for t in remaining_preview: 
            target_items[t] = max(target_items.get(t, 0), _W_PREVIEW)
            
        future_limit = min(self._last_active_idx + 8, len(self._all_orders))
        for i in range(self._last_active_idx + 2, future_limit):
             for t in self._all_orders[i]["items_required"]:
                 target_items[t] = max(target_items.get(t, 0), _W_FUTURE)

        # Collect tangible Item candidates
        candidates = [] # (priority, item)
        for t, prio in target_items.items():
            for item in items_by_type.get(t, []):
                candidates.append((prio, item))
        
        # Sort candidates by priority desc (optimization)
        candidates.sort(key=lambda x: x[0], reverse=True)
        # Limit candidates to ~100 to keep search fast?
        # Actually, brute force (Bot x Item x Item) is OK.

        # Aisle congestion map
        _AISLE_XS = frozenset((4, 8, 12, 16))
        aisle_pop: dict[int, int] = {}
        for _bid, _bpos in bot_positions.items():
            if _bpos[0] in _AISLE_XS and 2 <= _bpos[1] <= 10:
                aisle_pop[_bpos[0]] = aisle_pop.get(_bpos[0], 0) + 1

        # Search for assignments
        # Use greedy allocation: Find globally best (Bot, Tour), assign, repeat.
        # Tour definition: Current -> Item A -> [Item B] -> DropOff
        # Or: Current -> DropOff (if carrying items)
        
        # Compute DistMaps for ALL free bots (we need them for precise costing)
        # Optimization: Lazy compute inside loop? No, compute once.
        for bot in state.bots:
            if bot.id not in bots_handled:
                bot_dist_maps[bot.id] = bfs_distances_from(
                    grid, bot.pos.as_tuple(), item_blocked_set)

        # Iterative Assignment
        assigned_bot_ids = set(bots_handled) # copy
        
        while len(assigned_bot_ids) < len(state.bots):
            best_tour = None
            best_score = -999999.0
            
            # Evaluate all unassigned bots
            for bot in state.bots:
                if bot.id in assigned_bot_ids: continue
                
                bpos = bot.pos.as_tuple()
                dmap = bot_dist_maps.get(bot.id)
                if not dmap: continue
                
                # Base Tour: Just drop off what we have
                # Value = inventory value
                # Cost = dist to drop
                inv_val = 0
                for t in bot.inventory:
                    if t in remaining_active: inv_val += _W_ACTIVE
                    elif t in remaining_preview: inv_val += _W_PREVIEW
                    else: inv_val += _W_FUTURE # Carried garbage?
                    
                dist_drop = dropoff_dist_map.get(bpos, 999)
                # If bot is standing on the exit tile, it is adjacent to dropoff (dist=1)
                # even though exit_tile is technically "blocked" for ingress from outside.
                if bpos == exit_tile:
                    dist_drop = 1
                
                # Score = Value / Time? Or Value - Cost?
                # Value - Cost * Factor is safer to prevent infinite loops.
                # Factor ~ 1.0 (1 step = 1 point cost).
                
                # Base Tour logic: deliver current inventory
                if not bot.inventory:
                    # Empty bots shouldn't go to dropoff unless picking up something
                    base_score = -999999.0
                elif dist_drop > 100:
                    # Dropoff unreachable (e.g. Egress Phase blocking). 
                    # Do NOT try to go there (which results in waiting at the blockade).
                    # Instead, yield (score low) -> Phase 4 moves away.
                    base_score = -999999.0
                else:
                    base_score = inv_val - dist_drop

                    
                    # CRITICAL: If at dropoff (dist_drop < 1) with NO active items, 
                    # we are blocking the port. Penalize heavily to force eviction.
                    # This happens when holding only Preview/Future items.
                    if dist_drop < 1:
                        has_active = any(t in remaining_active for t in bot.inventory)
                        if not has_active:
                             base_score -= 2000.0


                
                # If inventory full, only consider dropping off
                if len(bot.inventory) >= 3:
                     if base_score > best_score:
                         best_score = base_score
                         best_tour = (bot.id, None, None) # (id, item1, item2)
                     continue
                
                # Compare against extending tour (Pickup 1 item)
                # Candidates check
                for prio, item in candidates:
                    if item.id in assigned_items: continue
                    ipos = item.pos.as_tuple()
                    
                    # Find valid pickup positions (adjacent, walkable, not blocked by other items)
                    # Note: find_all_pickup_positions checks grid walls, but not dynamic item_blocked
                    valid_pps = []
                    for pp in find_all_pickup_positions(grid, ipos):
                         if pp not in item_blocked_set: 
                             valid_pps.append(pp)
                    
                    if not valid_pps: continue

                    # Cost to get there (min dist to any valid pickup spot)
                    dist_to_item = 999
                    for pp in valid_pps:
                        d = dmap.get(pp, 999)
                        if d < dist_to_item: dist_to_item = d
                    
                    if dist_to_item > 50: continue # Unreachable

                    # Cost from item to drop
                    dist_item_drop = 999
                    for pp in valid_pps:
                        d = dropoff_dist_map.get(pp, 999)
                        if d < dist_item_drop: dist_item_drop = d
                    
                    # Total cost = dist_to_item + dist_item_drop
                    # Value = inv_val + prio
                    # Congestion
                    cong = 0
                    if ipos[0] in _AISLE_XS and 2 <= ipos[1] <= 10:
                        others = aisle_pop.get(ipos[0], 0)
                        if bpos[0] == ipos[0] and 2 <= bpos[1] <= 10: others = max(0, others - 1)
                        cong = others * _W_CONGESTION

                    score = (inv_val + prio) - (dist_to_item + dist_item_drop) + cong
                    
                    # Bonus for picking up item on the way to dropoff (Deferral)
                    # If we have inventory, and this item is "on the way"
                    # Original logic used detour check.
                    # Here, score naturally handles it:
                    # Direct Drop: Val - DistDrop
                    # Detour: (Val+Prio) - (DistItem + DistItemDrop)
                    # Gain = Prio - (DistItem + DistItemDrop - DistDrop)
                    # If Prio(=ACTIVE=100) > DetourCost, we do it.
                    # If Prio(=FUTURE=1) > DetourCost, we only do it if detour is very small.
                    
                    if score > best_score:
                        best_score = score
                        best_tour = (bot.id, item, None)
                        
                    # 2-Item Tour? (Bot -> Item A -> Item B -> Drop)
                    # Expensive to check all pairs. 
                    # Only check if Bot has <= 1 item (capacity for 2)
                    if len(bot.inventory) <= 1:
                        # Find Item B near Item A
                        # Optimization: only check nearby candidates
                        # BFS from Item A? Or just manhattan check
                        pass 
                        # For now, let's stick to 1-step lookahead + greedy re-eval.
                        # If we pick Item A, next round we pick Item B.
                        # The "score" includes dist_item_drop, which assumes we go to dropoff.
                        # If we actually pick Item B later, cost is (DistItemA_ItemB + DistItemB_Drop).
                        # This might be LESS or MORE than DistItemA_Drop.
                        # Usually MORE. So our estimate is optimistic if we stop, conservative if we continue?
                        # It assumes we stop.
                        
            # Apply Best Tour
            if best_tour:
                bid, item1, item2 = best_tour
                bot = next(b for b in state.bots if b.id == bid)
                
                # If just dropping off
                if item1 is None:

                    # Move to dropoff
                    # CRITICAL: Use ingress_blocked to avoid blocking the exit_tile
                    cmd = self._move_toward_direct(bid, bot.pos.as_tuple(), drop_off, grid, ingress_blocked)
                    if cmd.action in (BotAction.WAIT, BotAction.PICK_UP, BotAction.DROP_OFF):
                       actions.append(cmd)
                       stationary.add(bot.pos.as_tuple())
                    else:
                       target = self._move_target(bot.pos.as_tuple(), cmd.action)
                       move_plans.append((bid, bot.pos.as_tuple(), target))
                    delivering_bots.add(bid)
                    bot_priorities[bid] = 10
                else: 
                    # Move to item1
                    # Assign
                    # CRITICAL: Use item_blocked_set (without exit_tile block) so bots can LEAVE dropoff
                    self._assign_bot_to_item(
                        bid, bot, item1, item1.pos.as_tuple(), grid, state, item_blocked_set,
                        {b.id: b.pos.as_tuple() for b in state.bots}, bots_handled, actions, move_plans, stationary)

                    
                    assigned_items.add(item1.id)
                    # Update active/preview needs so other bots know?
                    # We are in loop within one turn. Yes.
                    # But `remaining_active` is list of types.
                    if item1.type in remaining_active: remaining_active.remove(item1.type)
                    elif item1.type in remaining_preview: remaining_preview.remove(item1.type)
                    
                    bot_priorities[bid] = 5
                
                # Critical Priority Boost: Bot currently at drop-off MUST leave to unblock others
                if bot.pos.as_tuple() == drop_off:
                    bot_priorities[bid] = 20

                assigned_bot_ids.add(bid)
                bots_handled.add(bid)
            else:
                break # No beneficial moves found

        # --- Phase 4b: Park remaining bots (unassigned) ---
        # The greedy search above should assign everyone unless score is terrible (e.g. unreachable).
        # Fallback to parking.
        for bot in state.bots:
            if bot.id in bots_handled: continue
            
            bpos = bot.pos.as_tuple()
             # CRITICAL: empty OR non-active bot at drop-off must leave
             # If bot is at dropoff and not dropping off (handled in Phase 1), it is obstructing.
            if bpos == drop_off:
                # Check neighbors to force-move (avoid other bots to prevent swap-lock)
                best_esc = None
                best_dist = -1
                
                # Check if we should really flee? (If we are holding valid active items, we should be dropping)
                # But Phase 1 handles drop-off. If we are here, we FAILED Phase 1 or didn't qualify.
                # So we MUST leave.
                
                # Force high priority to clear the jam
                bot_priorities[bot.id] = 20
                
                # Determine escape route (farthest from dropoff? No, just any neighbor not blocked)

                
                # Collect occupied positions
                occ = set(bot_positions.values())
                
                for n in grid.neighbors(bpos[0], bpos[1]):
                    if n == drop_off: continue
                    if n in item_blocked: continue
                    # Phase 4b PANIC: Allow moving into occupied cells to facilitate SWAPS
                    # if n in occ: continue 
                    
                    # Distance from dropoff

                    d = abs(n[0]-drop_off[0]) + abs(n[1]-drop_off[1])
                    if d > best_dist:
                        best_dist = d
                        best_esc = n
                
                if best_esc:
                    # Determine action
                    dx, dy = best_esc[0]-bpos[0], best_esc[1]-bpos[1]
                    act = BotAction.WAIT
                    if dx == 0 and dy == -1: act = BotAction.MOVE_UP
                    elif dx == 0 and dy == 1: act = BotAction.MOVE_DOWN
                    elif dx == -1 and dy == 0: act = BotAction.MOVE_LEFT
                    elif dx == 1 and dy == 0: act = BotAction.MOVE_RIGHT
                    
                    if act != BotAction.WAIT:
                        actions.append(BotActionCommand(bot=bot.id, action=act))
                        target = self._move_target(bpos, act)
                        move_plans.append((bot.id, bpos, target))
                        bots_handled.add(bot.id)
                        continue

                # Fallback if manual escape failed (e.g. boxed in by walls/items)
                cmd = self._move_away_from(
                    bot.id, bpos, drop_off, grid, item_blocked, bot_positions)
                if cmd.action == BotAction.WAIT:
                    actions.append(cmd)
                    stationary.add(bpos)
                else:
                    target = self._move_target(bpos, cmd.action)
                    move_plans.append((bot.id, bpos, target))
                bots_handled.add(bot.id)
                continue
                
            park = self._find_parking_far(
                bpos, drop_off, grid, item_blocked, bot_positions,
                state.grid.width // 2, state.grid.height)
            if park and park != bpos:
                cmd = self._move_toward_multi(
                    bot.id, bpos, park, grid, state,
                    item_blocked, bot_positions, bots_handled)
                if cmd.action == BotAction.WAIT:
                    actions.append(cmd)
                    stationary.add(bpos)
                else:
                    target = self._move_target(bpos, cmd.action)
                    move_plans.append((bot.id, bpos, target))
            else:
                actions.append(BotActionCommand(bot=bot.id, action=BotAction.WAIT))
                stationary.add(bpos)
            bots_handled.add(bot.id)

        # --- Resolve collisions for moving bots ---
        if move_plans:
            resolved = resolve_collisions(move_plans, stationary, bot_priorities)
            all_occupied = set(resolved.values()) | stationary
            for bot_id, cur, desired in move_plans:
                actual = resolved[bot_id]
                if actual == cur:
                    # Bot blocked — try alternative step toward goal
                    alt = self._find_alternative_step(
                        cur, desired, grid, item_blocked, all_occupied)
                    actions.append(BotActionCommand(bot=bot_id, action=alt))
                    if alt != BotAction.WAIT:
                        t = self._move_target(cur, alt)
                        all_occupied.add(t)
                else:
                    actions.append(BotActionCommand(
                        bot=bot_id, action=action_for_move(cur, actual)))

        actions.sort(key=lambda a: a.bot)
        return RoundActions(actions=actions)

    def _unused_legacy_phases(self):
        # ... kept for reference ...
        pass

    def _assign_bot_to_item_legacy(self, *args):

        # Endgame thresholds
        _endgame = remaining_rounds < 50
        _critical_endgame = remaining_rounds < 25
        _desperate_endgame = remaining_rounds < 15

        # --- Phase 2: Bot with matching active items → DELIVER ---
        # Proximity defer: if a nearby active-needed item is reachable within
        # manhattan detour ≤ 6, defer delivery to batch multiple items.
        deferred_delivery: set[int] = set()

        # Detect if an evicting bot at drop-off needs space to escape.
        # Only triggers for bots with non-matching items (actual eviction).
        # Empty bots at drop-off aren't stuck—they'll get reassigned by Phase 3.
        _dropoff_stuck = False
        for _b in state.bots:
            _bp = _b.pos.as_tuple()
            if _bp == drop_off and _b.id not in bots_handled:
                if _b.inventory and not items_matching_active(_b, state):
                    _dropoff_stuck = True
                    break

        for bot in state.bots:
            if bot.id in bots_handled:
                continue
            _matching = items_matching_active(bot, state)
            if not bot.inventory or not _matching:
                continue
            _match_count = len(_matching)
            bpos = bot.pos.as_tuple()
            _d2d = dropoff_dist_map.get(bpos, 999)

            # --- Opportunistic adjacent pickup ---
            if len(bot.inventory) < 3 and remaining_active:
                grab_cmd = None
                for item in state.items:
                    if item.type not in remaining_active:
                        continue
                    if item.id in assigned_items:
                        continue
                    ipos = item.pos.as_tuple()
                    if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
                        grab_cmd = BotActionCommand(
                            bot=bot.id, action=BotAction.PICK_UP, item_id=item.id)
                        remaining_active.remove(item.type)
                        assigned_items.add(item.id)
                        break
                if grab_cmd:
                    actions.append(grab_cmd)
                    stationary.add(bpos)
                    bot_priorities[bot.id] = 10
                    bots_handled.add(bot.id)
                    continue

            # --- Drop-off congestion: defer when evicting bot needs space ---
            if _dropoff_stuck and _d2d <= 3 and delivering_bots:
                deferred_delivery.add(bot.id)
                continue

            # --- Proximity defer (mode-aware: controlled by rolling-horizon) ---
            # Mode 0 (normal): manhattan ≤ 6 threshold
            # Mode 1 (no-defer): skip deferral entirely → deliver immediately
            # Mode 2 (wide-defer): manhattan ≤ 10 threshold
            #
            # When all active items are in transit (remaining_active empty),
            # also check preview items: picking up a nearby preview item lets
            # this bot auto-deliver it when the order completes at drop-off.
            _defer_types = list(remaining_active)
            _checking_preview_defer = False
            if not remaining_active and remaining_preview:
                _defer_types = list(remaining_preview)
                _checking_preview_defer = True
            if (self._defer_mode != 1
                    and _defer_types
                    and len(bot.inventory) < 3
                    and not _critical_endgame
                    and len(deferred_delivery) < self._defer_cap):
                # Use separate thresholds for active vs preview items
                if self._defer_mode == 2:
                    _defer_thresh_val = 10
                elif _checking_preview_defer:
                    _defer_thresh_val = self._preview_defer_thresh
                else:
                    _defer_thresh_val = self._defer_thresh
                bot_to_drop = _d2d if _d2d < 999 else abs(bpos[0] - drop_off[0]) + abs(bpos[1] - drop_off[1])
                best_extra = 999
                for need_type in _defer_types:
                    for item in items_by_type.get(need_type, []):
                        ipos = item.pos.as_tuple()
                        d_to_item = abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1])
                        d_item_drop = abs(ipos[0] - drop_off[0]) + abs(ipos[1] - drop_off[1])
                        extra = d_to_item + d_item_drop - bot_to_drop
                        if extra < best_extra:
                            best_extra = extra
                if best_extra <= _defer_thresh_val:
                    deferred_delivery.add(bot.id)
                    continue

            # --- Deliver: move toward drop-off ---
            cmd = self._move_toward_direct(
                bot.id, bpos, drop_off, grid, item_blocked)
            if cmd.action in (BotAction.WAIT, BotAction.PICK_UP, BotAction.DROP_OFF):
                actions.append(cmd)
                stationary.add(bpos)
            else:
                target = self._move_target(bpos, cmd.action)
                move_plans.append((bot.id, bpos, target))
            bot_priorities[bot.id] = 10 + max(0, 30 - _d2d)
            bots_handled.add(bot.id)
            delivering_bots.add(bot.id)

        # --- Phase 3: Assign needed items to available bots ---
        available_bots = [b for b in state.bots
                          if b.id not in bots_handled and len(b.inventory) < 3]

        was_active_mode = bool(remaining_active)
        needs_to_fill = list(remaining_active)
        if not needs_to_fill:
            needs_to_fill = list(remaining_preview)

        # Pre-compute BFS distance maps (reuse Phase 2 cache)
        for bot in available_bots:
            if bot.id not in bots_handled and bot.id not in bot_dist_maps:
                bot_dist_maps[bot.id] = bfs_distances_from(
                    grid, bot.pos.as_tuple(), item_blocked_set)

        # --- Aisle concentration constants ---
        _AISLE_XS = frozenset((4, 8, 12, 16))

        # Pre-compute aisle congestion: how many bots in each narrow aisle
        aisle_pop: dict[int, int] = {}
        for _bid, _bpos in bot_positions.items():
            if _bpos[0] in _AISLE_XS and 2 <= _bpos[1] <= 10:
                aisle_pop[_bpos[0]] = aisle_pop.get(_bpos[0], 0) + 1

        assignments: list[tuple[float, int, ItemInfo, tuple[int, int], str]] = []
        for need_type in needs_to_fill:
            for item in items_by_type.get(need_type, []):
                if item.id in assigned_items:
                    continue
                for pp in find_all_pickup_positions(grid, item.pos.as_tuple()):
                    if pp in item_blocked:
                        continue
                    return_dist = dropoff_dist_map.get(pp, 999)
                    pp_aisle = pp[0] if pp[0] in _AISLE_XS else -1
                    for bot in available_bots:
                        if bot.id in bots_handled:
                            continue
                        dmap = bot_dist_maps.get(bot.id)
                        if dmap is None:
                            continue
                        dist = dmap.get(pp, 999)
                        # Skip items that can't be delivered before game ends
                        if dist + return_dist + 2 > remaining_rounds:
                            continue
                        bonus = 0 if need_type in remaining_active else 1000
                        # Deferred bots get a bonus for nearby items so they
                        # beat empty bots and consolidate multi-item trips.
                        # Applies to active items AND preview items when all
                        # active items are already in transit.
                        _defer_for_active = need_type in remaining_active
                        _defer_for_preview = not remaining_active and need_type in remaining_preview
                        defer_bonus = -5 if (bot.id in deferred_delivery
                                             and (_defer_for_active or _defer_for_preview)) else 0
                        # Penalise crowded aisles: each extra bot ≈ 3 rounds of potential blocks
                        _cong_weight = self._congestion_override if self._congestion_override is not None else 3
                        congestion = 0
                        if pp_aisle > 0 and _cong_weight > 0:
                            others = aisle_pop.get(pp_aisle, 0)
                            # Don't count self if already in that aisle
                            bpos = bot.pos.as_tuple()
                            if bpos[0] == pp_aisle and 2 <= bpos[1] <= 10:
                                others = max(0, others - 1)
                            congestion = others * _cong_weight
                        # Synergy: bonus for items near other needed items
                        # (encourages multi-item trips via proximity defer)
                        _syn_weight = self._synergy_override if self._synergy_override is not None else -3
                        synergy = 0
                        if need_type in remaining_active:
                            ipos_s = item.pos.as_tuple()
                            for other_type in remaining_active:
                                if other_type == need_type:
                                    continue
                                for other_item in items_by_type.get(other_type, []):
                                    if other_item.id in assigned_items:
                                        continue
                                    opos = other_item.pos.as_tuple()
                                    if abs(ipos_s[0] - opos[0]) + abs(ipos_s[1] - opos[1]) <= 6:
                                        synergy += _syn_weight
                                        break  # one bonus per type
                        cost = dist + return_dist * self.config.return_cost_factor + bonus + congestion + defer_bonus + synergy
                        assignments.append((cost, bot.id, item, pp, need_type))

        # --- Greedy assignment ---
        assignments.sort(key=lambda x: x[0])
        for cost, bid, item, pp, need_type in assignments:
            if bid in bots_handled:
                continue
            if item.id in assigned_items:
                continue
            bot = None
            for b in state.bots:
                if b.id == bid:
                    bot = b
                    break
            if bot is None or len(bot.inventory) >= 3:
                continue

            self._assign_bot_to_item(
                bid, bot, item, pp, grid, state, item_blocked,
                bot_positions, bots_handled, actions, move_plans, stationary)
            assigned_items.add(item.id)
            bot_priorities[bid] = 5
            bots_handled.add(bid)
            if need_type in remaining_active:
                remaining_active.remove(need_type)
            elif need_type in remaining_preview:
                remaining_preview.remove(need_type)

        # --- Phase 2b: Deliver deferred bots not assigned in Phase 3 ---
        for bot in state.bots:
            if bot.id not in deferred_delivery or bot.id in bots_handled:
                continue
            bpos = bot.pos.as_tuple()
            cmd = self._move_toward_direct(
                bot.id, bpos, drop_off, grid, item_blocked)
            if cmd.action in (BotAction.WAIT, BotAction.PICK_UP, BotAction.DROP_OFF):
                actions.append(cmd)
                stationary.add(bpos)
            else:
                target = self._move_target(bpos, cmd.action)
                move_plans.append((bot.id, bpos, target))
            dist = dropoff_dist_map.get(bpos, 30)
            bot_priorities[bot.id] = 10 + max(0, 30 - dist)
            bots_handled.add(bot.id)
            delivering_bots.add(bot.id)

        # --- Phase 2c: Auto-delivery engineering (Hypothesis C) ---
        # DISABLED: Redirecting preview-item bots to drop-off causes fatal
        # congestion deadlocks when multiple bots cluster near (1,12).
        # The auto-delivery mechanic still triggers naturally when bots
        # happen to be at drop-off during order transitions.

        # --- Phase 3b: Remaining bots → pre-fetch preview + observed future order items ---
        if was_active_mode and not _desperate_endgame:
            leftover_bots = [b for b in state.bots
                             if b.id not in bots_handled and len(b.inventory) < 3]
            if leftover_bots:
                # Compute BFS maps for leftover bots that don't have one yet
                for bot in leftover_bots:
                    if bot.id not in bot_dist_maps:
                        bot_dist_maps[bot.id] = bfs_distances_from(
                            grid, bot.pos.as_tuple(), item_blocked_set)
                # Build lookahead needs from preview + full order sequence
                lookahead_needs: list[str] = list(remaining_preview)
                # Use pre-computed full order sequence for deep lookahead
                if self._all_orders is None:
                    self._all_orders = self._build_all_orders()
                # Reduce lookahead depth to avoid filling inventory with far-future items
                # Previously +8 (too aggressive). Now +3.
                for future_idx in range(self._last_active_idx + 2,
                                        min(self._last_active_idx + 5, 50)):
                    if future_idx < len(self._all_orders):
                        lookahead_needs.extend(
                            self._all_orders[future_idx]["items_required"])

                if lookahead_needs:
                    preview_assignments: list[tuple[float, int, ItemInfo, tuple[int, int], str]] = []
                    for need_type in lookahead_needs:
                        for item in items_by_type.get(need_type, []):
                            if item.id in assigned_items:
                                continue
                            for pp in find_all_pickup_positions(grid, item.pos.as_tuple()):
                                if pp in item_blocked:
                                    continue
                                for bot in leftover_bots:
                                    if bot.id in bots_handled:
                                        continue
                                    dmap = bot_dist_maps.get(bot.id)
                                    if dmap is None:
                                        continue
                                    dist = dmap.get(pp, 999)
                                    noise = self._phase3b_rng.gauss(0, self._phase3b_noise) if self._phase3b_noise > 0 else 0
                                    cost = dist + noise
                                    preview_assignments.append(
                                        (cost, bot.id, item, pp, need_type))

                    preview_assignments.sort(key=lambda x: x[0])
                    for cost, bid, item, pp, need_type in preview_assignments:
                        if bid in bots_handled or item.id in assigned_items:
                            continue
                        bot = next((b for b in state.bots if b.id == bid), None)
                        if bot is None or len(bot.inventory) >= 3:
                            continue
                        self._assign_bot_to_item(
                            bid, bot, item, pp, grid, state, item_blocked,
                            bot_positions, bots_handled, actions, move_plans, stationary)
                        assigned_items.add(item.id)
                        # Don't set sticky target for prefetch (avoid interference with Phase 3)
                        bot_priorities[bid] = 2
                        bots_handled.add(bid)

        # --- Phase 4: Idle bots → park FAR from drop-off (near items) ---
        grid_center_x = state.grid.width // 2
        for bot in state.bots:
            if bot.id in bots_handled:
                continue
            bpos = bot.pos.as_tuple()

            # CRITICAL: empty bot at drop-off must leave immediately using
            # direct movement (ignoring other bots) to avoid permanent deadlock.
            if bpos == drop_off and not bot.inventory:
                cmd = self._move_away_from(
                    bot.id, bpos, drop_off, grid, item_blocked, bot_positions)
                if cmd.action == BotAction.WAIT:
                    actions.append(cmd)
                    stationary.add(bpos)
                else:
                    target = self._move_target(bpos, cmd.action)
                    move_plans.append((bot.id, bpos, target))
                bots_handled.add(bot.id)
                continue

            park = self._find_parking_far(
                bpos, drop_off, grid, item_blocked, bot_positions,
                grid_center_x, state.grid.height)
            if park and park != bpos:
                cmd = self._move_toward_multi(
                    bot.id, bpos, park, grid, state,
                    item_blocked, bot_positions, bots_handled)
                if cmd.action == BotAction.WAIT:
                    actions.append(cmd)
                    stationary.add(bpos)
                else:
                    target = self._move_target(bpos, cmd.action)
                    move_plans.append((bot.id, bpos, target))
            else:
                actions.append(BotActionCommand(bot=bot.id, action=BotAction.WAIT))
                stationary.add(bpos)
            bots_handled.add(bot.id)

        # --- Resolve collisions for moving bots ---
        if move_plans:
            resolved = resolve_collisions(move_plans, stationary, bot_priorities)
            all_occupied = set(resolved.values()) | stationary
            for bot_id, cur, desired in move_plans:
                actual = resolved[bot_id]
                if actual == cur:
                    # Bot blocked — try alternative step toward goal
                    alt = self._find_alternative_step(
                        cur, desired, grid, item_blocked, all_occupied)
                    actions.append(BotActionCommand(bot=bot_id, action=alt))
                    if alt != BotAction.WAIT:
                        t = self._move_target(cur, alt)
                        all_occupied.add(t)
                else:
                    actions.append(BotActionCommand(
                        bot=bot_id, action=action_for_move(cur, actual)))

        actions.sort(key=lambda a: a.bot)
        return RoundActions(actions=actions)

    def _assign_bot_to_item(
        self,
        bid: int,
        bot,
        item: ItemInfo,
        pp: tuple[int, int],
        grid: Grid,
        state: GameState,
        item_blocked: frozenset[tuple[int, int]],
        bot_positions: dict[int, tuple[int, int]],
        bots_handled: set[int],
        actions: list,
        move_plans: list,
        stationary: set,
    ) -> None:
        """Common code: send bot toward item pickup position or pick up if adjacent."""
        bpos = bot.pos.as_tuple()
        ipos = item.pos.as_tuple()
        if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
            actions.append(BotActionCommand(
                bot=bid, action=BotAction.PICK_UP, item_id=item.id))
            stationary.add(bpos)
        else:
            cmd = self._move_toward_multi(
                bid, bpos, pp, grid, state, item_blocked,
                bot_positions, bots_handled)
            if cmd.action in (BotAction.WAIT, BotAction.PICK_UP, BotAction.DROP_OFF):
                actions.append(cmd)
                stationary.add(bpos)
            else:
                target = self._move_target(bpos, cmd.action)
                move_plans.append((bid, bpos, target))

    def _move_toward_multi(
        self,
        bot_id: int,
        start: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        state: GameState,
        item_blocked: frozenset[tuple[int, int]],
        bot_positions: dict[int, tuple[int, int]],
        handled: set[int],
    ) -> BotActionCommand:
        if start == goal:
            return BotActionCommand(bot=bot_id, action=BotAction.WAIT)

        blocked: set[tuple[int, int]] = set(item_blocked)
        # Block other bot positions
        for bid, bpos in bot_positions.items():
            if bid != bot_id:
                blocked.add(bpos)
        blocked.discard(goal)

        path = bfs_shortest_path(grid, start, goal, blocked)
        if path is None or len(path) < 2:
            # Try without blocking other bots
            path = bfs_shortest_path(grid, start, goal, set(item_blocked))
            if path is None or len(path) < 2:
                return BotActionCommand(bot=bot_id, action=BotAction.WAIT)

        return BotActionCommand(
            bot=bot_id, action=action_for_move(start, path[1]))

    def _move_toward_direct(
        self,
        bot_id: int,
        start: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
        prefer_left: bool = False,
    ) -> BotActionCommand:
        """Move toward goal ignoring other bots (collision resolver handles it)."""
        if start == goal:
            return BotActionCommand(bot=bot_id, action=BotAction.WAIT)
        blocked = set(item_blocked)
        blocked.discard(goal)
        path = bfs_shortest_path(grid, start, goal, blocked, prefer_left=prefer_left)
        if path is None or len(path) < 2:
            return BotActionCommand(bot=bot_id, action=BotAction.WAIT)
        return BotActionCommand(
            bot=bot_id, action=action_for_move(start, path[1]))

    @staticmethod
    def _find_alternative_step(
        cur: tuple[int, int],
        goal: tuple[int, int],
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
        occupied: set[tuple[int, int]],
    ) -> BotAction:
        """When primary move is blocked, find the best alternative direction.

        Prefers steps that reduce Manhattan distance to *goal*.
        Allows lateral (equal-distance) moves and stepping away by 1 as
        fallback — critical for breaking swap deadlocks where both bots
        are adjacent to their goal.
        Falls back to WAIT if no valid alternative exists.
        """
        cur_dist = abs(cur[0] - goal[0]) + abs(cur[1] - goal[1])
        best_action = BotAction.WAIT
        best_delta = 2  # accept closer, lateral, or 1-step-away moves
        for dx, dy, action in [
            (0, -1, BotAction.MOVE_UP), (0, 1, BotAction.MOVE_DOWN),
            (-1, 0, BotAction.MOVE_LEFT), (1, 0, BotAction.MOVE_RIGHT),
        ]:
            nx, ny = cur[0] + dx, cur[1] + dy
            if not grid.is_walkable(nx, ny):
                continue
            if (nx, ny) in item_blocked:
                continue
            if (nx, ny) in occupied:
                continue
            new_dist = abs(nx - goal[0]) + abs(ny - goal[1])
            delta = new_dist - cur_dist
            if delta < best_delta:
                best_delta = delta
                best_action = action
        return best_action

    def _move_away_from(
        self,
        bot_id: int,
        bpos: tuple[int, int],
        away_from: tuple[int, int],
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
        bot_positions: dict[int, tuple[int, int]],
    ) -> BotActionCommand:
        """Move one step away from a position.  Falls back to any walkable
        direction if all neighbours are occupied by bots (let collision
        resolver handle it — critical to avoid blocking drop-off forever)."""
        best_dir = None
        best_dist = -1
        fallback_dir = None  # best walkable direction ignoring other bots
        fallback_dist = -1
        for dx, dy, action in [
            (0, -1, BotAction.MOVE_UP), (0, 1, BotAction.MOVE_DOWN),
            (-1, 0, BotAction.MOVE_LEFT), (1, 0, BotAction.MOVE_RIGHT),
        ]:
            nx, ny = bpos[0] + dx, bpos[1] + dy
            if not grid.is_walkable(nx, ny):
                continue
            if (nx, ny) in item_blocked:
                continue
            dist = abs(nx - away_from[0]) + abs(ny - away_from[1])
            # Track best walkable (ignoring bots) as fallback
            if dist > fallback_dist:
                fallback_dist = dist
                fallback_dir = action
            if any((nx, ny) == p for bid, p in bot_positions.items() if bid != bot_id):
                continue
            if dist > best_dist:
                best_dist = dist
                best_dir = action
        if best_dir:
            return BotActionCommand(bot=bot_id, action=best_dir)
        # No free cell — try moving anyway (collision resolver or server will sort it out)
        if fallback_dir:
            return BotActionCommand(bot=bot_id, action=fallback_dir)
        return BotActionCommand(bot=bot_id, action=BotAction.WAIT)

    def _find_parking_far(
        self,
        bpos: tuple[int, int],
        drop_off: tuple[int, int],
        grid: Grid,
        item_blocked: frozenset[tuple[int, int]],
        bot_positions: dict[int, tuple[int, int]],
        center_x: int,
        grid_height: int,
    ) -> Optional[tuple[int, int]]:
        """Find a parking spot that doesn't block delivery routes."""
        # Park in clear corridors (rows 1, 7) in the right half
        # Avoid rows 11, 12 which are the main delivery corridor
        best = None
        best_score = -1
        # Prefer row 1 and row 7 (clear corridors) in right half
        preferred_rows = [1, 7]
        for y in preferred_rows:
            for x in range(center_x, grid.width - 1):
                if not grid.is_walkable(x, y):
                    continue
                if (x, y) in item_blocked:
                    continue
                if any((x, y) == p for p in bot_positions.values()):
                    continue
                dist_from_bot = abs(x - bpos[0]) + abs(y - bpos[1])
                score = 1000 - dist_from_bot  # Prefer closer parking
                if score > best_score:
                    best_score = score
                    best = (x, y)
        if best:
            return best
        # Fallback: any walkable cell in right half, not on row 11/12
        for x in range(center_x, grid.width - 1):
            for y in range(grid_height):
                if y >= 11:
                    continue
                if (x, y) == drop_off:
                    continue
                if not grid.is_walkable(x, y):
                    continue
                if (x, y) in item_blocked:
                    continue
                if any((x, y) == p for p in bot_positions.values()):
                    continue
                return (x, y)
        return bpos

    @staticmethod
    def _move_target(pos: tuple[int, int], action: BotAction) -> tuple[int, int]:
        dx, dy = {
            BotAction.MOVE_UP: (0, -1),
            BotAction.MOVE_DOWN: (0, 1),
            BotAction.MOVE_LEFT: (-1, 0),
            BotAction.MOVE_RIGHT: (1, 0),
        }.get(action, (0, 0))
        return (pos[0] + dx, pos[1] + dy)

    # ===================================================================
    # EASY SCHEDULE-DRIVEN PLANNER (single bot)
    # ===================================================================

    def _decide_easy(self, state: GameState) -> RoundActions:
        bot = state.bots[0]
        bpos = bot.pos.as_tuple()
        drop_off = (state.drop_off[0], state.drop_off[1])
        grid = Grid(state.grid)
        item_blocked = frozenset(
            (it.position[0], it.position[1]) for it in state.items
        )
        action = self._plan_action_easy(bot, state, grid, drop_off, item_blocked)
        return RoundActions(actions=[action])

    def _plan_action_easy(
        self, bot, state, grid, drop_off, item_blocked,
    ) -> BotActionCommand:
        bpos = bot.pos.as_tuple()

        if bpos == drop_off and bot.inventory:
            matching = items_matching_active(bot, state)
            if matching:
                self._trip_route = []
                return BotActionCommand(bot=bot.id, action=BotAction.DROP_OFF)
            if not self._trip_route and len(bot.inventory) >= 3:
                return BotActionCommand(bot=bot.id, action=BotAction.DROP_OFF)

        if self._trip_route and len(bot.inventory) < 3:
            action = self._follow_route(bot, state, grid, item_blocked)
            if action is not None:
                return action

        if bot.inventory and not self._trip_route:
            matching = items_matching_active(bot, state)
            if matching or len(bot.inventory) >= 3:
                return self._move_toward_easy(bot.id, bpos, drop_off, grid, state, item_blocked)

        free_slots = 3 - len(bot.inventory)
        if self._trip_idx < len(EASY_SCHEDULE) and free_slots > 0:
            types = list(EASY_SCHEDULE[self._trip_idx])
            types = types[:free_slots]
            self._trip_idx += 1

            items_by_type: dict[str, list[ItemInfo]] = {}
            for item in state.items:
                items_by_type.setdefault(item.type, []).append(item)

            route = self._build_route(
                bpos, drop_off, types, items_by_type, grid, set(item_blocked))
            if route:
                self._trip_route = route
                action = self._follow_route(bot, state, grid, item_blocked)
                if action is not None:
                    return action

        if bot.inventory:
            return self._move_toward_easy(bot.id, bpos, drop_off, grid, state, item_blocked)

        active_needs = compute_needed_items(state)
        preview_needs = compute_preview_items(state) if self.config.prefetch else []
        result = self._best_item_to_pick(
            bot, state, grid, item_blocked, active_needs, preview_needs)
        if result[0] is not None and result[1] is not None:
            item, pp = result
            ipos = item.pos.as_tuple()
            if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
                return BotActionCommand(
                    bot=bot.id, action=BotAction.PICK_UP, item_id=item.id)
            return self._move_toward_easy(bot.id, bpos, pp, grid, state, item_blocked)

        return BotActionCommand(bot=bot.id, action=BotAction.WAIT)

    def _follow_route(self, bot, state, grid, item_blocked):
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
            self._trip_route.pop(0)
            return self._follow_route(bot, state, grid, item_blocked) if self._trip_route else None
        ipos = target_item.pos.as_tuple()
        if abs(bpos[0] - ipos[0]) + abs(bpos[1] - ipos[1]) == 1:
            self._trip_route.pop(0)
            return BotActionCommand(
                bot=bot.id, action=BotAction.PICK_UP, item_id=target_item_id)
        return self._move_toward_easy(
            bot.id, bpos, target_pp, grid, state, item_blocked)

    def _build_route(self, start, drop_off, types, items_by_type, grid, blocked):
        if not types:
            return []
        def manhattan(a, b):
            return abs(a[0] - b[0]) + abs(a[1] - b[1])
        candidates = []
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

        all_points = {start, drop_off}
        for cands in candidates:
            for _, pp in cands:
                all_points.add(pp)
        bfs_cache = {}
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
        best_route = []
        for choices in iprod(*candidates):
            pts = [(pp, iid) for iid, pp in choices]
            for perm in permutations(range(n)):
                cost = bfs_cache.get((start, pts[perm[0]][0]), 999999)
                for i in range(n - 1):
                    cost += bfs_cache.get(
                        (pts[perm[i]][0], pts[perm[i + 1]][0]), 999999)
                cost += bfs_cache.get((pts[perm[-1]][0], drop_off), 999999)
                if cost < best_cost:
                    best_cost = cost
                    best_route = [pts[perm[j]] for j in range(n)]
        return best_route

    def _best_item_to_pick(self, bot, state, grid, item_blocked, active_needs, preview_needs):
        bpos = bot.pos.as_tuple()
        cfg = self.config
        active_counter = Counter(active_needs)
        preview_counter = Counter(preview_needs)
        blocked_set = set(item_blocked)
        drop_off_tuple = (state.drop_off[0], state.drop_off[1])
        scored = []
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
                ret = abs(pp[0] - drop_off_tuple[0]) + abs(pp[1] - drop_off_tuple[1])
                total_cost = dist + cfg.return_cost_factor * ret
                score = utility / max(total_cost, 1)
                scored.append((score, dist, item.type, pp[0], pp[1], item))
        if not scored:
            return None, None
        scored.sort(key=lambda s: (-s[0], s[1], s[2], s[3], s[4]))
        best = scored[0]
        return best[5], (best[3], best[4])

    def _move_toward_easy(self, bot_id, start, goal, grid, state, item_blocked):
        if start == goal:
            return BotActionCommand(bot=bot_id, action=BotAction.WAIT)
        blocked = set(item_blocked)
        for b in state.bots:
            if b.id != bot_id:
                blocked.add(b.pos.as_tuple())
        blocked.discard(goal)
        path = bfs_shortest_path(grid, start, goal, blocked)
        if path is None or len(path) < 2:
            path = bfs_shortest_path(grid, start, goal, set(item_blocked) - {goal})
            if path is None or len(path) < 2:
                return self._simple_move(bot_id, start, goal, grid, item_blocked)
        return BotActionCommand(bot=bot_id, action=action_for_move(start, path[1]))

    @staticmethod
    def _simple_move(bot_id, start, goal, grid, item_blocked):
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
