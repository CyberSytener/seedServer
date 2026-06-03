"""WebSocket game client for NMiAI Grocery Bot.

High-level ``run_game()`` function that:
  1. Obtains a game session via :func:`endpoint.request_game_session`
     (or accepts a pre-built ``ws_url``).
  2. Connects over WebSocket and plays 300 rounds with the
     :class:`~modules.bot.decision_engine.DecisionEngine`.
  3. Returns a :class:`GameResult` summary.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import websockets

from modules.bot.decision_engine import DecisionEngine
from modules.bot.models import BotAction, BotActionCommand, GameOver, GameState, RoundActions
from modules.bot.telemetry import RoundLogger

from .endpoint import GameSession, request_game_session


# ── Result ─────────────────────────────────────────────────────────────────

@dataclass
class GameResult:
    """Outcome of a single game run."""
    score: int = 0
    items_delivered: int = 0
    orders_completed: int = 0
    rounds_played: int = 0
    difficulty: str = "unknown"
    avg_decision_ms: float = 0.0
    max_decision_ms: float = 0.0
    log_path: Optional[str] = None
    error: Optional[str] = None
    decision_times: list[float] = field(default_factory=list, repr=False)


# ── Core game loop ─────────────────────────────────────────────────────────

async def _play(
    ws_url: str,
    engine: Any,  # DecisionEngine or OptimizedEngine — must have .decide(state)
    *,
    logger: Optional[RoundLogger] = None,
    debug: bool = False,
    timeout: float = 1.8,
) -> GameResult:
    """Connect to *ws_url* and play until ``game_over``."""
    result = GameResult()
    decision_times: list[float] = []

    try:
        async with websockets.connect(
            ws_url,
            max_size=2**20,
            close_timeout=5,
        ) as ws:
            if debug:
                print(f"[ws_client] Connected to {ws_url[:60]}…")

            while True:
                raw = await ws.recv()
                msg = json.loads(raw)

                if msg.get("type") == "game_over":
                    go = GameOver(**msg)
                    result.score = go.score
                    result.items_delivered = go.items or 0
                    result.orders_completed = go.orders or 0
                    if logger:
                        logger.finalize(go.score, items=go.items or 0, orders=go.orders or 0)
                    if debug:
                        print(f"[ws_client] Game Over — score={go.score}")
                    return result

                state = GameState(**msg)
                result.rounds_played = state.round + 1

                # Decide (with timeout guard)
                try:
                    actions = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, engine.decide, state,
                        ),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    actions = RoundActions(actions=[
                        BotActionCommand(bot=b.id, action=BotAction.WAIT)
                        for b in state.bots
                    ])
                    if debug:
                        print(f"  [TIMEOUT] round={state.round}")

                decision_times.append(engine.last_decision_ms)

                await ws.send(json.dumps(actions.to_payload()))

                if logger:
                    logger.log_round(
                        round_num=state.round,
                        score=state.score,
                        decision_ms=engine.last_decision_ms,
                        actions=[a.to_dict() for a in actions.actions],
                        raw_state=msg if logger.save_states else None,
                    )

                if debug and state.round % 50 == 0:
                    print(f"  R{state.round:3d}/{state.max_rounds}  "
                          f"score={state.score:4d}  "
                          f"dt={engine.last_decision_ms:.1f}ms")

    except websockets.ConnectionClosedError as exc:
        if debug:
            print(f"[ws_client] Connection closed: {exc}")
        result.error = str(exc)
    except Exception as exc:
        result.error = str(exc)
        if debug:
            print(f"[ws_client] Error: {exc}")
        raise

    finally:
        if decision_times:
            result.avg_decision_ms = sum(decision_times) / len(decision_times)
            result.max_decision_ms = max(decision_times)
        result.decision_times = decision_times

    return result


# ── Public API ─────────────────────────────────────────────────────────────

async def run_game_async(
    difficulty: str = "easy",
    *,
    ws_url: Optional[str] = None,
    access_token: Optional[str] = None,
    use_astar: bool = False,
    debug: bool = False,
    verbose: bool = False,
    log_dir: str = "logs/bot",
    engine: Any = None,
) -> GameResult:
    """Obtain a session and play one full game.

    Parameters
    ----------
    difficulty : str
        ``easy`` | ``medium`` | ``hard`` | ``expert``.
    ws_url : str, optional
        If provided, skips the HTTP session-request step.
    access_token : str, optional
        Bare JWT.  Resolved from ``.env`` when omitted.
    use_astar : bool
        Use A* instead of BFS for pathfinding.
    debug : bool
        Print round-by-round output.
    verbose : bool
        Extra decision-engine detail.
    log_dir : str
        Where to write JSONL game logs.
    engine : optional
        Pre-built engine (DecisionEngine or OptimizedEngine).  If None,
        a default DecisionEngine is used.

    Returns
    -------
    GameResult
    """
    if ws_url is None:
        session: GameSession = request_game_session(
            difficulty, access_token=access_token,
        )
        ws_url = session.ws_url
        difficulty = session.difficulty
        if debug:
            print(f"[ws_client] Session obtained — {session.map_label} "
                  f"({session.difficulty})")

    if engine is None:
        engine = DecisionEngine(use_astar=use_astar, debug=debug, verbose=verbose)
    logger = RoundLogger(log_dir=log_dir, difficulty=difficulty, save_states=True)

    result = await _play(ws_url, engine, logger=logger, debug=debug)
    result.difficulty = difficulty
    result.log_path = str(logger.log_path)
    return result


def run_game(
    difficulty: str = "easy",
    **kwargs,
) -> GameResult:
    """Synchronous wrapper around :func:`run_game_async`."""
    return asyncio.run(run_game_async(difficulty, **kwargs))
