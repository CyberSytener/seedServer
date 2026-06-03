"""Instrument planner phases to see what each bot does per round."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from pathlib import Path
from collections import Counter

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

# Monkey-patch _decide_multi to track phase assignments
original_decide = OptimizedEngine._decide_multi

phase_log = []

def instrumented_decide(self, state):
    # Before calling original, record which bots exist
    bot_ids = {b.id for b in state.bots}
    result = original_decide(self, state)
    
    # After decide, check what each bot was assigned to do
    action_map = {a.bot: a for a in result.actions}
    drop_off = (state.drop_off[0], state.drop_off[1])
    
    bot_phases = {}
    for b in state.bots:
        a = action_map.get(b.id)
        if a is None:
            bot_phases[b.id] = "MISSING"
            continue
        bpos = b.pos.as_tuple()
        has_inv = len(b.inventory) > 0
        
        if a.action == BotAction.DROP_OFF:
            bot_phases[b.id] = "DROP_OFF"
        elif a.action == BotAction.PICK_UP:
            bot_phases[b.id] = "PICKUP"
        elif a.action == BotAction.WAIT:
            bot_phases[b.id] = "WAIT"
        else:
            # Moving - infer purpose from state
            if has_inv:
                bot_phases[b.id] = "DELIVER"  # carrying items, heading to drop-off
            else:
                bot_phases[b.id] = "FETCH"  # empty, heading to pick up
    
    phase_log.append((state.round, dict(bot_phases)))
    return result

OptimizedEngine._decide_multi = instrumented_decide

game = MultiBotGame.from_log(valid[0])
engine = OptimizedEngine(debug=False)
while not game.game_over:
    state = game.get_state()
    actions = engine.decide(state)
    game.step(actions)

print(f"Score: {game.score}, Orders: {game.orders_completed}")

# Count per-phase
total_phases = Counter()
for rnd, phases in phase_log:
    for bid, phase in phases.items():
        total_phases[phase] += 1

total = sum(total_phases.values())
print(f"\nPer-phase distribution (over {len(phase_log)} rounds x 5 bots = {total} bot-actions):")
for phase in ["DROP_OFF", "PICKUP", "DELIVER", "FETCH", "WAIT", "MISSING"]:
    cnt = total_phases.get(phase, 0)
    pct = cnt * 100 / total
    print(f"  {phase:10s}: {cnt:5d} ({pct:5.1f}%)")

# How many bots are FETCH (empty, heading to item) vs DELIVER per round?
print(f"\nPer-round distribution of bot roles:")
deliver_per_round = []
fetch_per_round = []
wait_per_round = []
for rnd, phases in phase_log:
    deliver_per_round.append(sum(1 for p in phases.values() if p in ("DELIVER", "DROP_OFF")))
    fetch_per_round.append(sum(1 for p in phases.values() if p in ("FETCH", "PICKUP")))
    wait_per_round.append(sum(1 for p in phases.values() if p == "WAIT"))

import statistics
print(f"  Delivering: avg={statistics.mean(deliver_per_round):.2f}  (drop_off or carrying items)")
print(f"  Fetching:   avg={statistics.mean(fetch_per_round):.2f}  (empty, heading to item)")
print(f"  Waiting:    avg={statistics.mean(wait_per_round):.2f}")
print(f"  Total active: avg={statistics.mean(deliver_per_round)+statistics.mean(fetch_per_round):.2f}")

# Show first 30 rounds
print(f"\nRound-by-round (first 40 rounds):")
for rnd, phases in phase_log[:40]:
    summary = " ".join(f"B{bid}:{p}" for bid, p in sorted(phases.items()))
    print(f"  R{rnd:3d}: {summary}")

# Show rounds where bots are waiting
wait_rounds = [(rnd, phases) for rnd, phases in phase_log if any(p == "WAIT" for p in phases.values())]
print(f"\nRounds with WAITing bots: {len(wait_rounds)} / {len(phase_log)}")
for rnd, phases in wait_rounds[:10]:
    waiting = [bid for bid, p in phases.items() if p == "WAIT"]
    print(f"  R{rnd:3d}: bots {waiting} waiting")
