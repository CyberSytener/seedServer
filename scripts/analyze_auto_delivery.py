#!/usr/bin/env python3
"""Analyze auto-delivery events and order transition timing.

Shows how many items auto-deliver on order transitions and the gap between
consecutive order completions.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "bot"

def get_hard_logs(n=10):
    logs = sorted(LOG_DIR.glob("game_*hard*.jsonl"), key=lambda p: p.name)
    valid = [l for l in logs if l.stat().st_size > 500000]
    return valid[:n]

def analyze_game(log_path):
    game = MultiBotGame.from_log(log_path)
    eng = OptimizedEngine()

    # Track order completions and auto-deliveries
    prev_score = 0
    prev_orders = 0
    prev_items = 0
    order_events = []  # (round, orders_completed, items_delivered, auto_items_guess)

    while not game.game_over:
        state = game.get_state()
        actions = eng.decide(state)
        game.step(actions)

        # Detect order completion
        if game.orders_completed > prev_orders:
            delta_items = game.items_delivered - prev_items
            delta_orders = game.orders_completed - prev_orders
            # Items beyond what the current order needed are auto-delivered
            order_events.append({
                'round': game.round,
                'new_orders': delta_orders,
                'new_items': delta_items,
                'total_orders': game.orders_completed,
                'total_items': game.items_delivered,
                'score': game.score,
            })
            prev_orders = game.orders_completed
            prev_items = game.items_delivered
        prev_score = game.score

    return {
        'score': game.score,
        'orders': game.orders_completed,
        'items': game.items_delivered,
        'events': order_events,
    }

if __name__ == "__main__":
    logs = get_hard_logs(10)
    all_gaps = []
    all_auto = []

    for log in logs:
        result = analyze_game(log)
        print(f"\n{log.name}: score={result['score']} orders={result['orders']} items={result['items']}")

        events = result['events']
        for i, evt in enumerate(events):
            gap = evt['round'] - (events[i-1]['round'] if i > 0 else 0)
            # If new_orders > 1 or new_items > expected, auto-delivery happened
            chain = " CHAIN!" if evt['new_orders'] > 1 else ""
            print(f"  R{evt['round']:3d}: +{evt['new_orders']}ord +{evt['new_items']}items{chain}")
            all_gaps.append(gap)

    print(f"\n--- Summary ---")
    print(f"Order gaps: avg={sum(all_gaps)/len(all_gaps):.1f} min={min(all_gaps)} max={max(all_gaps)}")
    print(f"Total order events: {len(all_gaps)}")
