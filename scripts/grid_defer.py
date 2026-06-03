"""Grid search over defer cap and threshold."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from pathlib import Path
import statistics

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]
N = 30

# We'll monkey-patch the Phase 2 defer logic
# Baseline: cap=2, threshold=6
# Test: cap=1,2,3,4; threshold=4,5,6,7,8

import types

def make_engine_with_defer(defer_cap: int, defer_thresh: int):
    """Create engine with custom defer parameters."""
    engine = OptimizedEngine(debug=False)
    engine._defer_cap = defer_cap
    engine._defer_thresh = defer_thresh
    return engine

# First let me check current code to understand where to patch
# The defer logic uses:
# len(deferred_delivery) < 2  --> defer cap
# manhattan threshold 6       --> defer threshold

results = []
for cap in [1, 2, 3, 4]:
    for thresh in [4, 5, 6, 7, 8]:
        scores = []
        for i in range(N):
            game = MultiBotGame.from_log(valid[i])
            engine = OptimizedEngine(debug=False)
            # Store config for monkey-patching
            engine._defer_cap_override = cap
            engine._defer_thresh_override = thresh
            while not game.game_over:
                state = game.get_state()
                actions = engine.decide(state)
                game.step(actions)
            scores.append(game.score)
        avg = statistics.mean(scores)
        mn, mx = min(scores), max(scores)
        print(f"cap={cap} thresh={thresh}: Avg={avg:.1f} Min={mn} Max={mx}")
        results.append((cap, thresh, avg, mn, mx))

# But we can't dynamically change the planner behavior without modifying it.
# Let me just test the baseline to verify.
print("\nNote: defer_cap_override and defer_thresh_override are not read by planner.")
print("Need to modify planner to support these overrides.")
print("Testing baseline only as sanity check.")
