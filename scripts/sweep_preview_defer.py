#!/usr/bin/env python3
"""Sweep preview defer threshold values for the preview-aware proximity defer.

The current proximity defer uses the same threshold for both active and
preview items. This sweep tests different thresholds specifically for
preview items to find the sweet spot.
"""
import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from scripts._simulator_hard import MultiBotGame, simulate_multi
from modules.bot.planner import OptimizedEngine

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "bot"
N = 20  # games per config

def get_hard_logs():
    logs = sorted(LOG_DIR.glob("game_*_hard.jsonl"))
    return logs[:N]

def bench(thresh_val: int) -> list[int]:
    logs = get_hard_logs()
    scores = []
    for log in logs:
        eng = OptimizedEngine()
        eng._defer_thresh = thresh_val
        scores.append(simulate_multi(eng, log))
    return scores

if __name__ == "__main__":
    thresholds = [3, 4, 5, 6, 7, 8, 10]
    for th in thresholds:
        scores = bench(th)
        avg = statistics.mean(scores)
        med = statistics.median(scores)
        sd = statistics.stdev(scores) if len(scores) > 1 else 0
        mn, mx = min(scores), max(scores)
        print(f"Thresh={th:2d}  N={N} Avg={avg:.1f} Med={med:.0f} StdDev={sd:.1f} Min={mn} Max={mx}")
