"""Analyze order pipeline: what % of next-order items are ready when previous completes?"""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from modules.bot.orders import get_active_order, get_preview_order
from pathlib import Path

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

for seed_idx in [0, 5, 10]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = OptimizedEngine(debug=False)

    prev_active_id = None
    order_transitions = []

    while not game.game_over:
        state = game.get_state()
        
        active = get_active_order(state)
        active_id = active.id if active else None
        
        # Detect order transition
        if active_id != prev_active_id and prev_active_id is not None:
            # Order just changed! Check what's ready for new order
            if active:
                needed = list(active.items_required)
                total_needed = len(needed)
                
                # Items already delivered for this order
                already_delivered = len(active.items_delivered)
                
                # Items in bot inventories matching new order
                items_in_transit = 0
                remaining = list(needed)
                for d in active.items_delivered:
                    if d in remaining:
                        remaining.remove(d)
                for bot in state.bots:
                    for item_type in bot.inventory:
                        if item_type in remaining:
                            remaining.remove(item_type)
                            items_in_transit += 1
                
                items_ready = already_delivered + items_in_transit
                pct = items_ready * 100 / total_needed if total_needed > 0 else 0
                order_transitions.append((state.round, active_id, total_needed, already_delivered, items_in_transit, pct))
        
        prev_active_id = active_id
        
        actions = engine.decide(state)
        game.step(actions)

    print(f"Seed {seed_idx}: score={game.score} orders={game.orders_completed}")
    for r, oid, total, delivered, transit, pct in order_transitions:
        print(f"  R{r:3d}: {oid} needs {total} items, {delivered} delivered + {transit} in transit = {delivered+transit}/{total} ({pct:.0f}% ready)")
    
    avg_pct = sum(t[5] for t in order_transitions) / len(order_transitions) if order_transitions else 0
    print(f"  Average pipeline readiness: {avg_pct:.1f}%")
    print()
