"""Find bad seeds with stickiness and debug why."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from pathlib import Path

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

bad_seeds = []
for i in range(30):
    game = MultiBotGame.from_log(valid[i])
    engine = OptimizedEngine(debug=False)
    while not game.game_over:
        state = game.get_state()
        actions = engine.decide(state)
        game.step(actions)
    if game.score < 120:
        bad_seeds.append((i, game.score))
        print(f"BAD seed {i}: score={game.score} items={game.items_delivered} orders={game.orders_completed}")

print(f"\nTotal bad: {len(bad_seeds)} / 30")

# Now run first bad seed with debug to understand
if bad_seeds:
    idx = bad_seeds[0][0]
    print(f"\n--- Debug run seed {idx} ---")
    game = MultiBotGame.from_log(valid[idx])
    engine = OptimizedEngine(debug=False)
    
    last_targets = {}
    changes = 0
    r = 0
    while not game.game_over:
        state = game.get_state()
        actions = engine.decide(state)
        
        # Check stickiness effect
        cur_targets = dict(engine._prev_item_targets)
        for bid, iid in cur_targets.items():
            if bid in last_targets and last_targets[bid] != iid:
                if r < 50 or r % 50 == 0:
                    print(f"  R{r}: Bot {bid} switched {last_targets[bid][:20]} -> {iid[:20]}")
                changes += 1
        last_targets = dict(cur_targets)
        
        game.step(actions)
        r += 1
    
    print(f"Total target changes: {changes}")
