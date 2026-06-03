#!/usr/bin/env python3
"""Compare high-scoring vs low-scoring games to find what makes the difference.

Tracks per-game: order count, items, order gaps, items/trip, delivery times.
"""
import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "bot"

def get_hard_logs(n=30):
    logs = sorted(LOG_DIR.glob("game_*hard*.jsonl"), key=lambda p: p.name)
    valid = [l for l in logs if l.stat().st_size > 500000]
    return valid[:n]

def analyze_game(log_path):
    game = MultiBotGame.from_log(log_path)
    eng = OptimizedEngine()
    
    prev_orders = 0
    prev_items = 0
    order_rounds = []
    last_order_round = 0
    
    while not game.game_over:
        state = game.get_state()
        actions = eng.decide(state)
        game.step(actions)
        
        if game.orders_completed > prev_orders:
            gap = game.round - last_order_round
            delta_items = game.items_delivered - prev_items
            order_rounds.append((gap, delta_items))
            last_order_round = game.round
            prev_orders = game.orders_completed
            prev_items = game.items_delivered
    
    return {
        'score': game.score,
        'orders': game.orders_completed,
        'items': game.items_delivered,
        'order_gaps': [g for g, _ in order_rounds],
        'items_per_order': [i for _, i in order_rounds],
    }

if __name__ == "__main__":
    logs = get_hard_logs(30)
    results = []
    
    for log in logs:
        r = analyze_game(log)
        results.append(r)
    
    results.sort(key=lambda r: r['score'], reverse=True)
    
    print(f"{'Score':>5}  {'Ord':>3}  {'Items':>5}  {'Avg Gap':>7}  {'Min Gap':>7}  {'Max Gap':>7}  {'Avg I/O':>7}")
    print("-" * 60)
    for r in results:
        gaps = r['order_gaps']
        ipo = r['items_per_order']
        avg_gap = statistics.mean(gaps) if gaps else 0
        min_gap = min(gaps) if gaps else 0
        max_gap = max(gaps) if gaps else 0
        avg_ipo = statistics.mean(ipo) if ipo else 0
        print(f"{r['score']:5d}  {r['orders']:3d}  {r['items']:5d}  {avg_gap:7.1f}  {min_gap:7d}  {max_gap:7d}  {avg_ipo:7.1f}")
