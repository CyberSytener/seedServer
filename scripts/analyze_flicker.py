"""Detect assignment flickering: bots switching targets between rounds."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from modules.bot.pathfinding import bfs_shortest_path
from modules.bot.grid import Grid
from pathlib import Path

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

MOVE_ACTIONS = {BotAction.MOVE_UP, BotAction.MOVE_DOWN, BotAction.MOVE_LEFT, BotAction.MOVE_RIGHT}
MOVE_DELTAS = {
    BotAction.MOVE_UP: (0, -1),
    BotAction.MOVE_DOWN: (0, 1),
    BotAction.MOVE_LEFT: (-1, 0),
    BotAction.MOVE_RIGHT: (1, 0),
}

for seed_idx in [0, 5, 10]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = OptimizedEngine(debug=False)

    # Track inferred targets per bot
    prev_targets: dict[int, tuple[int, int]] = {}
    flickers = 0
    total_moves = 0
    wasted_moves = 0  # moves that go AWAY from subsequent target

    round_num = 0
    while not game.game_over:
        state = game.get_state()
        actions = engine.decide(state)

        for a in actions.actions:
            bot = next(b for b in state.bots if b.id == a.bot)
            bpos = bot.pos.as_tuple()

            if a.action in MOVE_ACTIONS:
                total_moves += 1
                dx, dy = MOVE_DELTAS[a.action]
                new_pos = (bpos[0] + dx, bpos[1] + dy)

                # Infer target: the direction bot is moving
                # Track target as new_pos for simple direction check
                # Actually we can track the implied direction vector

        game.step(actions)
        round_num += 1

    print(f"Seed {seed_idx}: total_moves={total_moves}")

# Better approach: monkey-patch the planner to log assignments
print("\n--- Tracking actual Phase 3 assignments ---")

class InstrumentedEngine(OptimizedEngine):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._assigned_targets: dict[int, str] = {}  # bot_id -> item_id
        self._flicker_count = 0
        self._assign_count = 0
        self._round = 0

    def _assign_bot_to_item(self, bid, bot, item, pp, grid, state, item_blocked,
                            bot_positions, bots_handled, actions, move_plans, stationary):
        # Track assignment changes
        old_target = self._assigned_targets.get(bid)
        new_target = item.id
        self._assign_count += 1
        if old_target is not None and old_target != new_target:
            self._flicker_count += 1
        self._assigned_targets[bid] = new_target
        super()._assign_bot_to_item(bid, bot, item, pp, grid, state, item_blocked,
                                     bot_positions, bots_handled, actions, move_plans, stationary)

for seed_idx in [0, 5, 10, 15, 20]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = InstrumentedEngine(debug=False)
    while not game.game_over:
        state = game.get_state()
        engine._round = state.round
        actions = engine.decide(state)
        game.step(actions)

    pct = engine._flicker_count / max(1, engine._assign_count) * 100
    print(f"Seed {seed_idx}: score={game.score} assigns={engine._assign_count} flickers={engine._flicker_count} ({pct:.1f}%)")
