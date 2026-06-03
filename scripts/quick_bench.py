"""Quick benchmark: run N games and report avg/min/max score."""
import sys
import statistics
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from pathlib import Path

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

scores = []
for i in range(min(N, len(valid))):
    game = MultiBotGame.from_log(valid[i])
    engine = OptimizedEngine(debug=False)
    while not game.game_over:
        state = game.get_state()
        actions = engine.decide(state)
        game.step(actions)
    scores.append(game.score)
    if i % 10 == 0:
        print(f"  {i}/{N}...", flush=True)

print(f"\nN={len(scores)} Avg={statistics.mean(scores):.1f} Med={statistics.median(scores):.0f} "
      f"StdDev={statistics.stdev(scores):.1f} Min={min(scores)} Max={max(scores)}")
