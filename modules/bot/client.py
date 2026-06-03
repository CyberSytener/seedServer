"""GameWSClient — outbound WebSocket client for the NMiAI game server."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, Optional

import websockets

from .decision_engine import DecisionEngine
from .models import GameOver, GameState, RoundActions
from .telemetry import RoundLogger


class GameWSClient:
    """Connects to the game server and runs the play loop."""

    def __init__(
        self,
        url: str,
        engine: DecisionEngine,
        *,
        timeout: float = 1.8,
        logger: Optional[RoundLogger] = None,
        debug: bool = False,
    ):
        self.url = url
        self.engine = engine
        self.timeout = timeout
        self.logger = logger
        self.debug = debug
        self.game_over: Optional[GameOver] = None

    async def play(self) -> GameOver | None:
        """Connect and play until game_over or disconnect."""
        debug_file = open("logs/bot/debug_states.jsonl", "w", encoding="utf-8") if self.debug else None
        try:
            async with websockets.connect(
                self.url,
                max_size=2**20,  # 1MB — plenty for game state
                close_timeout=5,
            ) as ws:
                if self.debug:
                    print(f"[GameWSClient] Connected to {self.url[:60]}...")

                _last_round = -1
                _skipped = 0
                _desync_count = 0
                _total_rt_ms = 0.0

                while True:
                    rt_start = time.perf_counter()

                    # Drain buffered messages — always process the LATEST state
                    raw = await ws.recv()
                    drained = 0
                    while True:
                        try:
                            newer = await asyncio.wait_for(ws.recv(), timeout=0.001)
                            raw = newer
                            drained += 1
                        except (asyncio.TimeoutError, asyncio.CancelledError):
                            break

                    msg = json.loads(raw)

                    if msg.get("type") == "game_over":
                        self.game_over = GameOver(**msg)
                        if self.debug:
                            print(f"\n[GameWSClient] Game Over! "
                                  f"Score: {self.game_over.score}"
                                  f" | Skipped: {_skipped}"
                                  f" | Desyncs: {_desync_count}"
                                  f" | Avg RT: {_total_rt_ms / max(_last_round, 1):.1f}ms")
                        if self.logger:
                            self.logger.finalize(
                                self.game_over.score,
                                items=self.game_over.items or 0,
                                orders=self.game_over.orders or 0,
                            )
                        return self.game_over

                    # Parse game state — direct call, no validation overhead
                    state = GameState.model_validate(msg)

                    # Detect desync: skipped rounds
                    if state.round > _last_round + 1 and _last_round >= 0:
                        _desync_count += 1
                        if self.debug and _desync_count <= 5:
                            print(f"  [DESYNC] Expected round {_last_round+1}, got {state.round} (skipped {state.round - _last_round - 1})")
                    if drained > 0:
                        _skipped += drained
                        if self.debug:
                            print(f"  [DRAIN] Skipped {drained} stale states at round {state.round}")
                    _last_round = state.round

                    # Decide SYNCHRONOUSLY — no executor overhead (compute is 1-4ms)
                    try:
                        actions = self.engine.decide(state)
                    except Exception as e:
                        from .models import BotAction, BotActionCommand
                        actions = RoundActions(actions=[
                            BotActionCommand(bot=b.id, action=BotAction.WAIT)
                            for b in state.bots
                        ])
                        if self.debug:
                            print(f"  [ERROR] round={state.round}: {e}")

                    # Send response ASAP — minimal serialization
                    payload = actions.to_payload()
                    await ws.send(json.dumps(payload))

                    rt_ms = (time.perf_counter() - rt_start) * 1000
                    _total_rt_ms += rt_ms

                    # Debug dump first 10 rounds to file
                    if debug_file and state.round < 10:
                        entry = {
                            "round": state.round,
                            "bot_pos": [b.position for b in state.bots],
                            "bot_inv": [b.inventory for b in state.bots],
                            "items": [(it.id, it.type, it.position) for it in state.items],
                            "orders": [(o.id, o.status.value, o.items_required, o.items_delivered) for o in state.orders],
                            "drop_off": state.drop_off,
                            "grid_size": [state.grid.width, state.grid.height],
                            "walls": state.grid.walls,
                            "score": state.score,
                            "actions": [a.to_dict() for a in actions.actions],
                        }
                        if state.round == 0:
                            entry["raw_keys"] = list(msg.keys())
                        debug_file.write(json.dumps(entry, ensure_ascii=True) + "\n")
                        debug_file.flush()

                    # Log
                    if self.logger:
                        self.logger.log_round(
                            round_num=state.round,
                            score=state.score,
                            decision_ms=self.engine.last_decision_ms,
                            actions=[a.to_dict() for a in actions.actions],
                            raw_state=msg if self.logger.save_states else None,
                        )

                    if self.debug and state.round % 10 == 0:
                        print(f"  Round {state.round:3d}/{state.max_rounds} "
                              f"score={state.score:4d} "
                              f"dt={self.engine.last_decision_ms:.1f}ms"
                              f" rt={rt_ms:.1f}ms")

        except websockets.ConnectionClosedError as e:
            if self.debug:
                print(f"[GameWSClient] Connection closed: {e}")
            return self.game_over
        except Exception as e:
            if self.debug:
                print(f"[GameWSClient] Error: {e}")
            raise
        finally:
            if debug_file:
                debug_file.close()
