#!/usr/bin/env python3
"""Measure slack and missed preview opportunities.

Replays games and calculates how early items arrive before order completion.
If (OrderEnd - Arrival) > (DistToPreview * 2), it's a missed opportunity.
"""
import sys, os, json
from collections import defaultdict, Counter
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import (
    BotAction,
    BotActionCommand,
    BotInfo,
    GameState,
    GridInfo,
    ItemInfo,
    OrderInfo,
    OrderStatus,
    Pos,
    RoundActions,
)

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "bot"

def get_hard_logs(n=10):
    logs = sorted(LOG_DIR.glob("game_*hard*.jsonl"), key=lambda p: p.name)
    valid = [l for l in logs if l.stat().st_size > 500000]
    return valid[-n:]

class InstrumentedGame(MultiBotGame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delivery_log = []  # [(round, oid, item_type, bot_id)]
        self.order_completion_rounds = {} # oid -> round

    def _try_dropoff(self, bot_id: int):
        bpos = self.bot_positions[bot_id]
        if bpos != list(self.drop_off):
            return
        if not self.bot_inventories[bot_id]:
            return
        if self._order_idx >= len(self.all_orders):
            return

        inv_before = list(self.bot_inventories[bot_id])
        active = self.all_orders[self._order_idx]
        oid = active["id"]
        
        # Call original (this mutates state!)
        # We need to hook precisely into the logic, but the original logic
        # removes items from inventory and adds to _order_deliveries.
        
        # To avoid duplicating logic, we observe state change.
        prev_deliveries_len = len(self._order_deliveries[oid])
        prev_orders_done = self.orders_completed

        remaining = list(active["items_required"])
        for d in self._order_deliveries[oid]:
             if d in remaining: remaining.remove(d)

        # Re-implement core logic to capture details (risky if logic drifts)
        # Better: Snapshot inventory, run logic, compare.
        
        inv_before_counts = Counter(inv_before)
        
        # --- Run original ---
        super()._try_dropoff(bot_id)
        # --------------------
        
        inv_after_counts = Counter(self.bot_inventories[bot_id])
        
        # Diff
        delivered_items = []
        for k in inv_before_counts:
            diff = inv_before_counts[k] - inv_after_counts[k]
            for _ in range(diff):
                # It was delivered to CURRENT order (oid)
                # Note: If order completed, _order_idx increased.
                # If distinct items were delivered, they went to `oid` unless `super` proceeded to next order
                # via recursion.
                # This is tricky. 
                # Assuming simple case: delivered to `oid`.
                self.delivery_log.append({
                    'round': self.round,
                    'oid': oid,
                    'item': k,
                    'bot': bot_id
                })

        if self.orders_completed > prev_orders_done:
            self.order_completion_rounds[oid] = self.round

    def _auto_deliver_all_bots(self):
        # Hook auto-delivery too
        # This is called recursively.
        # We need to know which order is being auto-delivered.
        if self._order_idx >= len(self.all_orders):
            return
        oid = self.all_orders[self._order_idx]["id"]
        
        # Snapshot all inv
        inv_before = [list(i) for i in self.bot_inventories]
        
        super()._auto_deliver_all_bots()
        
        # Review changes
        for bid in range(self.num_bots):
            c1 = Counter(inv_before[bid])
            c2 = Counter(self.bot_inventories[bid])
            for k in c1:
                diff = c1[k] - c2[k]
                for _ in range(diff):
                    self.delivery_log.append({
                        'round': self.round,
                        'oid': oid, # This might be wrong if multiple orders clear in one go?
                        'item': k,
                        'bot': bid,
                        'auto': True
                    })
        
        # Check completion
        # If we completed the order:
        # We can't easily detect which order completed inside the recursive call
        # but we can deduce it later.

def trace_game(log_path):
    # Setup
    with open(log_path) as f:
        first = json.loads(f.readline())
    
    # Re-init game
    st = first['state']
    grid_info = GridInfo(
        width=st['grid']['width'],
        height=st['grid']['height'],
        walls=st['grid']['walls'],
    )
    
    game = InstrumentedGame(
        grid=grid_info,
        items=st['items'],
        orders=st['orders'],
        drop_off=st['drop_off'],
        bot_starts=[b['position'] for b in st['bots']],
        max_rounds=300
    )
    
    eng = OptimizedEngine()
    
    # Replay
    while not game.game_over:
        state = game.get_state()
        actions = eng.decide(state)
        game.step(actions)
        
    return game

def analyze_opportunities(game):
    # Analyze delivery log
    # Group by Order
    orders = defaultdict(list)
    for entry in game.delivery_log:
        orders[entry['oid']].append(entry)
        
    missed_ops = 0
    total_slack = 0
    
    # Pre-compute preview locations for each round (expensive)
    # Simplified: use final game state? No, items disappear.
    # Use initial item locations (static unless picked).
    # Static items is close enough approximation for now.
    
    item_locs = {it['id']: tuple(it['position']) for it in game.item_defs}
    item_types = {it['id']: it['type'] for it in game.item_defs}
    
    # Flatten items by type
    items_by_type = defaultdict(list)
    for iid, pos in item_locs.items():
        items_by_type[item_types[iid]].append(pos)
        
    print(f"{'OID':<8} {'CompT':<5} {'Slack':<5} {'Missed Ops'}")
    
    for oid in sorted(orders.keys(), key=lambda x: int(x.split('_')[1])):
        entries = orders[oid]
        completion_round = max(e['round'] for e in entries)
        
        # Next order preview items?
        # Get next order ID
        curr_idx = int(oid.split('_')[1])
        next_oid = f"order_{curr_idx+1}"
        
        # Find required items for next order
        # Need to know what next order needs.
        # We can look up in game.all_orders
        
        next_order_reqs = []
        if curr_idx + 1 < len(game.all_orders):
            next_order_reqs = game.all_orders[curr_idx+1]['items_required']
            
        ops_found = []
            
        for e in entries:
            slack = completion_round - e['round']
            if slack > 2: # Significant slack
                total_slack += slack
                # Could this bot have picked up a preview item?
                # Max detour = slack // 2 (approx, assuming 1 step = 1 round)
                radius = slack // 2
                
                # Check neighbors of path?
                # Simplified: Check items near DropOff (dist < radius + 3?)
                # Actually, check items near DropOff.
                # Distance from DropOff to Item + Return < Slack?
                # Dist * 2 < Slack.
                
                drop_off = tuple(game.drop_off)
                
                for req_type in set(next_order_reqs): # unique types needed
                     for ipos in items_by_type[req_type]:
                         dist = abs(ipos[0] - drop_off[0]) + abs(ipos[1] - drop_off[1])
                         if dist * 2 <= slack:
                             ops_found.append(f"{req_type}@{dist}")
                             break # One is enough to prove opportunity
        
        if ops_found:
            missed_ops += 1
            print(f"{oid:<8} {completion_round:<5} {total_slack:<5} {len(ops_found)} ops: {ops_found[:3]}...")
            
    print(f"Total Slack Rounds: {total_slack}")
    print(f"Orders with Missed Ops: {missed_ops}")

if __name__ == "__main__":
    logs = get_hard_logs(1) # Just check one game
    for log in logs:
        print(f"Analyzing {log.name}...")
        game = trace_game(log)
        analyze_opportunities(game)
