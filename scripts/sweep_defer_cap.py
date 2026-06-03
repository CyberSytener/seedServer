"""Sweep defer cap values: 1,2,3,4,5 and measure impact on items/trip and score."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from modules.bot.orders import items_matching_active
from pathlib import Path
import statistics
from collections import Counter

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]
N = 15  # quick sweep

# Monkey-patch the Phase 2 defer cap
import types

def make_decide_multi_with_cap(cap):
    """Return a patched _decide_multi that uses the given defer cap."""
    original = OptimizedEngine._decide_multi.__code__
    # Can't easily patch the source. Instead, set an attribute.
    pass

# Simpler approach: set the cap as an instance attribute and read it in the code.
# But code reads `len(deferred_delivery) < 2` which is hardcoded.
# Let me just modify planner.py to use self._defer_cap, test, then revert.

print("Need to modify planner.py first. Running with default cap=2 as baseline...")

for cap_val in [1, 2, 3, 4, 5]:
    print(f"\n--- defer_cap={cap_val} --- (requires planner modification)")
