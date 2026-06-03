#!/usr/bin/env python3
"""Sweep preview_defer_thresh values while keeping active defer_thresh at 6."""
import sys, os, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "bot"
N = 20

def get_hard_logs():
    logs = sorted(LOG_DIR.glob("game_*hard*.jsonl"), key=lambda p: p.name)
    valid = [l for l in logs if l.stat().st_size > 500000]
    return valid[:N]

def bench(preview_thresh: int) -> list[int]:
    logs = get_hard_logs()
    scores = []
    for log in logs:
        game = MultiBotGame.from_log(log)
        eng = OptimizedEngine()
        eng._defer_thresh = 6
        eng._preview_defer_thresh = preview_thresh
        while not game.game_over:
            state = game.get_state()
            actions = eng.decide(state)
            game.step(actions)
        scores.append(game.score)
    return scores

if __name__ == "__main__":
    for pth in [0, 3, 4, 6, 8, 10, 14]:
        scores = bench(pth)
        avg = statistics.mean(scores)
        med = statistics.median(scores)
        sd = statistics.stdev(scores) if len(scores) > 1 else 0
        mn, mx = min(scores), max(scores)
        print(f"PreviewThresh={pth:2d}  N={N} Avg={avg:.1f} Med={med:.0f} StdDev={sd:.1f} Min={mn} Max={mx}")
