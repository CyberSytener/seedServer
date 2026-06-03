"""Test cost component ablation: synergy & congestion."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from pathlib import Path
import statistics

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]
N = 30

# Variant A: baseline (syn=-3, cong=3)
# Variant B: no synergy (syn=0)
# Variant C: no congestion (cong=0)
# Variant D: no synergy, no congestion
# Variant E: stronger synergy (syn=-5)
# Variant F: stronger congestion (cong=5)

variants = [
    ("baseline",   None, None),
    ("syn=0",      0,    None),
    ("cong=0",     None, 0),
    ("both=0",     0,    0),
    ("syn=-5",     -5,   None),
    ("cong=5",     None, 5),
]

for name, syn, cong in variants:
    scores = []
    for i in range(N):
        game = MultiBotGame.from_log(valid[i])
        engine = OptimizedEngine(debug=False)
        if syn is not None:
            engine._synergy_override = syn
        if cong is not None:
            engine._congestion_override = cong
        while not game.game_over:
            state = game.get_state()
            actions = engine.decide(state)
            game.step(actions)
        scores.append(game.score)
    avg = statistics.mean(scores)
    mn, mx = min(scores), max(scores)
    std = statistics.stdev(scores)
    print(f"{name:12s}: Avg={avg:.1f} Min={mn} Max={mx} StdDev={std:.1f}")
