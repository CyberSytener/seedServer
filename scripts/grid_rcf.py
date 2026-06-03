"""Grid scan: try different return_cost_factor values."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine, PlannerConfig
from pathlib import Path
import statistics

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

N = 30

for rcf in [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5]:
    config = PlannerConfig(return_cost_factor=rcf)
    scores = []
    for i in range(N):
        game = MultiBotGame.from_log(valid[i])
        engine = OptimizedEngine(config=config, debug=False)
        while not game.game_over:
            state = game.get_state()
            actions = engine.decide(state)
            game.step(actions)
        scores.append(game.score)
    avg = statistics.mean(scores)
    mn = min(scores)
    mx = max(scores)
    std = statistics.stdev(scores)
    print(f"rcf={rcf:.1f}: Avg={avg:.1f} Min={mn} Max={mx} StdDev={std:.1f}")
