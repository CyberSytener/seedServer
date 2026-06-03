"""Count collision-related wasted moves."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from pathlib import Path

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

MOVE_ACTIONS = {BotAction.MOVE_UP, BotAction.MOVE_DOWN, BotAction.MOVE_LEFT, BotAction.MOVE_RIGHT}

for seed_idx in [0, 5, 10]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = OptimizedEngine(debug=False)

    waits = 0
    moves = 0
    pickups = 0
    dropoffs = 0
    
    # Track if bots move AWAY from their apparent target
    prev_pos = {}
    direction_changes = 0
    
    while not game.game_over:
        state = game.get_state()
        actions = engine.decide(state)
        
        for a in actions.actions:
            bot = next(b for b in state.bots if b.id == a.bot)
            bpos = bot.pos.as_tuple()
            
            if a.action in MOVE_ACTIONS:
                moves += 1
            elif a.action == BotAction.PICK_UP:
                pickups += 1
            elif a.action == BotAction.DROP_OFF:
                dropoffs += 1
            else:  # WAIT
                waits += 1
        
        game.step(actions)

    total = moves + pickups + dropoffs + waits
    print(f"Seed {seed_idx}: moves={moves} pickups={pickups} dropoffs={dropoffs} waits={waits}")
    print(f"  Total={total}, waits={waits} ({waits*100/total:.1f}%)")
    print(f"  Score={game.score}")
    print()
