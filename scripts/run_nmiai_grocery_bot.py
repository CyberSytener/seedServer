#!/usr/bin/env python
"""Run the NMiAI Grocery Bot — auto-obtains a game session from the API.

Usage examples::

    # Easy difficulty with optimised planner (default)
    python scripts/run_nmiai_grocery_bot.py

    # Use legacy baseline engine
    python scripts/run_nmiai_grocery_bot.py --legacy

    # Show max-score estimate and exit
    python scripts/run_nmiai_grocery_bot.py --show-max

    # Load best config found by autotune
    python scripts/run_nmiai_grocery_bot.py --use-best

    # Run autotune (search for best config)
    python scripts/run_nmiai_grocery_bot.py --autotune-easy --max-runs 30

    # All four difficulties back-to-back
    python scripts/run_nmiai_grocery_bot.py --all

    # Medium difficulty
    python scripts/run_nmiai_grocery_bot.py --difficulty medium

    # Pre-existing WebSocket URL (skip session request)
    python scripts/run_nmiai_grocery_bot.py --url "wss://game.ainm.no/ws?token=…"

Environment:
    AINM_ACCESS_TOKEN  — set in .env (format: access_token=<jwt>)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os

# Ensure the project root is on sys.path so that both ``modules.bot``
# and ``app.integrations`` are importable.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.integrations.nmiai_grocery_bot.endpoint import (
    DIFFICULTY_MAP_IDS,
    request_game_session,
    list_maps,
)
from app.integrations.nmiai_grocery_bot.ws_client import run_game_async, GameResult


DIFFICULTIES = list(DIFFICULTY_MAP_IDS.keys())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NMiAI Grocery Bot — auto-session runner",
    )
    p.add_argument(
        "--difficulty", "-d",
        type=str,
        default="easy",
        choices=DIFFICULTIES,
        help="Map difficulty (default: easy)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run all four difficulties sequentially",
    )
    p.add_argument(
        "--url",
        type=str,
        default=None,
        help="Pre-existing WebSocket URL (skips session request)",
    )
    p.add_argument(
        "--use-astar",
        action="store_true",
        help="Use A* instead of BFS for pathfinding",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        default=True,
        help="Print round-by-round debug output (default: on)",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-round output",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Extra decision-engine detail",
    )
    p.add_argument(
        "--log-dir",
        type=str,
        default="logs/bot",
        help="Directory for JSONL game logs",
    )
    p.add_argument(
        "--list-maps",
        action="store_true",
        help="Print available maps and exit",
    )
    # ── Max-score / optimised planner flags ────────────────────────────
    p.add_argument(
        "--show-max",
        action="store_true",
        help="Print max-score estimate and exit (requests one session to read round-0 state)",
    )
    p.add_argument(
        "--legacy",
        action="store_true",
        help="Use the baseline DecisionEngine instead of OptimizedEngine",
    )
    p.add_argument(
        "--use-best",
        action="store_true",
        help="Load the best config found by autotune",
    )
    p.add_argument(
        "--autotune-easy",
        action="store_true",
        help="Run autotune to find best config for Easy difficulty",
    )
    p.add_argument(
        "--max-runs",
        type=int,
        default=30,
        help="Max autotune runs (default: 30)",
    )
    p.add_argument(
        "--target-score",
        type=int,
        default=None,
        help="Autotune stops early when this score is reached",
    )
    return p.parse_args()


def print_result(result: GameResult) -> None:
    print(f"\n{'='*50}")
    print(f"  Difficulty      : {result.difficulty}")
    print(f"  Final Score     : {result.score}")
    print(f"  Items Delivered : {result.items_delivered}")
    print(f"  Orders Complete : {result.orders_completed}")
    print(f"  Rounds Played   : {result.rounds_played}")
    print(f"  Avg Decision    : {result.avg_decision_ms:.1f} ms")
    print(f"  Max Decision    : {result.max_decision_ms:.1f} ms")
    if result.log_path:
        print(f"  Log             : {result.log_path}")
    if result.error:
        print(f"  Error           : {result.error}")
    print(f"{'='*50}\n")


def _build_engine(args: argparse.Namespace, debug: bool):
    """Build the appropriate engine based on CLI flags."""
    if args.legacy:
        from modules.bot.decision_engine import DecisionEngine
        return DecisionEngine(
            use_astar=args.use_astar,
            debug=debug,
            verbose=args.verbose,
        )

    from modules.bot.planner import OptimizedEngine, PlannerConfig

    if args.use_best:
        from modules.bot.autotune import load_best_config
        config = load_best_config(args.difficulty)
        print(f"  [Loaded best config: {config.to_dict()}]")
    else:
        config = PlannerConfig()

    return OptimizedEngine(config=config, debug=debug, verbose=args.verbose)


async def run_one(
    difficulty: str,
    args: argparse.Namespace,
) -> GameResult:
    debug = args.debug and not args.quiet
    print(f"\n>>> Starting game — {difficulty.upper()} <<<\n")
    engine = _build_engine(args, debug)
    result = await run_game_async(
        difficulty,
        ws_url=args.url,
        debug=debug,
        verbose=args.verbose,
        log_dir=args.log_dir,
        engine=engine,
    )
    print_result(result)
    return result


async def handle_show_max(args: argparse.Namespace) -> None:
    """Request a game, read round-0 state, compute max-score estimate."""
    import websockets
    from modules.bot.models import GameState
    from modules.bot.max_score import estimate_max_score, score_upper_bound

    session = request_game_session(args.difficulty)
    print(f"  Map       : {session.map_label} ({session.difficulty})")

    async with websockets.connect(session.ws_url, max_size=2**20, close_timeout=5) as ws:
        raw = await ws.recv()
        msg = json.loads(raw)
        state = GameState(**msg)

    est = estimate_max_score(state)
    ub = score_upper_bound(state.total_orders)

    print(f"\n  === Max Score Estimate ({args.difficulty}) ===")
    print(f"  Total orders      : {est.total_orders}")
    print(f"  Max rounds        : {est.max_rounds}")
    print(f"  Avg order size    : {est.avg_order_size}")
    print(f"  Visible orders    : {est.visible_order_sizes}")
    print(f"  ──────────────────────────────────")
    print(f"  Upper bound (all) : {ub}")
    print(f"  Est. cycles       : {est.est_cycles}")
    print(f"  Est. items deliv. : {est.est_items_delivered}")
    print(f"  Est. orders compl.: {est.est_orders_completed}")
    print(f"  Est. achievable   : {est.est_achievable_score}")
    print()


async def handle_autotune(args: argparse.Namespace) -> None:
    from modules.bot.autotune import autotune

    best = await autotune(
        "easy",
        max_runs=args.max_runs,
        target_score=args.target_score,
        debug=True,
    )
    if best:
        print(f"\n  Best score: {best.score}")
        print(f"  Config: {best.config.to_dict()}")


async def async_main() -> None:
    args = parse_args()

    if args.list_maps:
        maps = list_maps()
        for m in maps:
            print(f"  {m.difficulty:8s}  {m.label:10s}  {m.id}  seed={m.seed}")
        return

    if args.show_max:
        await handle_show_max(args)
        return

    if args.autotune_easy:
        await handle_autotune(args)
        return

    if args.all:
        results: list[GameResult] = []
        for diff in DIFFICULTIES:
            args.difficulty = diff
            r = await run_one(diff, args)
            results.append(r)

        # Summary table
        print("\n" + "="*60)
        print("  SUMMARY")
        print("="*60)
        print(f"  {'Difficulty':<10} {'Score':>6} {'Items':>6} {'Orders':>7} {'Avg ms':>8}")
        print(f"  {'-'*10} {'-'*6} {'-'*6} {'-'*7} {'-'*8}")
        for r in results:
            print(f"  {r.difficulty:<10} {r.score:>6} "
                  f"{r.items_delivered:>6} {r.orders_completed:>7} "
                  f"{r.avg_decision_ms:>7.1f}")
        total = sum(r.score for r in results)
        print(f"  {'TOTAL':<10} {total:>6}")
        print("="*60)
    else:
        await run_one(args.difficulty, args)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
