"""Analyze score distribution across games."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from pathlib import Path
import statistics
from collections import Counter

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

scores = []
details = []
for i, log_path in enumerate(valid[:30]):
    game = MultiBotGame.from_log(log_path)
    engine = OptimizedEngine(debug=False)
    while not game.game_over:
        state = game.get_state()
        actions = engine.decide(state)
        game.step(actions)
    scores.append(game.score)
    items = game.items_delivered
    orders = game.orders_completed
    details.append((game.score, items, orders))
    print(f'Game {i:3d}: score={game.score:3d}  items={items:2d}  orders={orders:2d}')

print(f'\nN={len(scores)} Avg={statistics.mean(scores):.1f} Med={statistics.median(scores):.0f} '
      f'StdDev={statistics.stdev(scores):.1f} Min={min(scores)} Max={max(scores)}')

buckets = Counter()
for s in scores:
    buckets[s // 10 * 10] += 1
for b in sorted(buckets):
    bar = '#' * buckets[b]
    print(f'  {b:3d}-{b+9}: {bar} ({buckets[b]})')
