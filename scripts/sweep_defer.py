"""Sweep defer cap and threshold values."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from pathlib import Path
import statistics

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]
N = 30

configs = [
    # (cap, thresh, label)
    (2, 6, "baseline cap=2 th=6"),
    (3, 6, "cap=3 th=6"),
    (4, 6, "cap=4 th=6"),
    (5, 6, "cap=5 th=6"),
    (2, 4, "cap=2 th=4"),
    (2, 8, "cap=2 th=8"),
    (3, 8, "cap=3 th=8"),
    (4, 8, "cap=4 th=8"),
    (3, 4, "cap=3 th=4"),
]

for cap, thresh, label in configs:
    scores = []
    for i in range(N):
        game = MultiBotGame.from_log(valid[i])
        engine = OptimizedEngine(debug=False)
        engine._defer_cap = cap
        engine._defer_thresh = thresh
        while not game.game_over:
            state = game.get_state()
            actions = engine.decide(state)
            game.step(actions)
        scores.append(game.score)
    avg = statistics.mean(scores)
    mn, mx = min(scores), max(scores)
    std = statistics.stdev(scores)
    print(f"{label:25s}: Avg={avg:.1f} Min={mn} Max={mx} Std={std:.1f}")
