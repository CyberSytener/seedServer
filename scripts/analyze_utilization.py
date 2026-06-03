"""Analyze per-round bot utilization: how many bots are productively assigned?"""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from modules.bot.orders import get_active_order, compute_needed_items
from pathlib import Path

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

MOVE_ACTIONS = {BotAction.MOVE_UP, BotAction.MOVE_DOWN, BotAction.MOVE_LEFT, BotAction.MOVE_RIGHT}

for seed_idx in [0]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = OptimizedEngine(debug=False)

    phase_counts = {"delivering": 0, "picking_active": 0, "picking_preview": 0, "parking": 0, "evicting": 0}
    per_round_active = []  # how many bots have active-related tasks

    while not game.game_over:
        state = game.get_state()
        drop_off = (state.drop_off[0], state.drop_off[1])
        active_needs = compute_needed_items(state)

        actions = engine.decide(state)

        # Categorize each bot's action
        bots_delivering = 0
        bots_picking_active = 0
        bots_picking_preview = 0
        bots_parking = 0

        for a in actions.actions:
            bot = next(b for b in state.bots if b.id == a.bot)
            bpos = bot.pos.as_tuple()
            has_inventory = len(bot.inventory) > 0
            has_matching = any(t in active_needs for t in bot.inventory) if has_inventory else False

            if a.action == BotAction.DROP_OFF:
                bots_delivering += 1
            elif a.action == BotAction.PICK_UP:
                # Is this an active or preview item?
                if a.item_id:
                    item = next((it for it in state.items if it.id == a.item_id), None)
                    if item and item.type in active_needs:
                        bots_picking_active += 1
                    else:
                        bots_picking_preview += 1
                else:
                    bots_picking_active += 1
            elif a.action in MOVE_ACTIONS:
                # Moving: toward drop-off (delivering) or toward item (picking)?
                if has_inventory and has_matching:
                    bots_delivering += 1
                elif has_inventory:
                    # Has non-matching items - evicting or delivering preview
                    bots_picking_preview += 1
                else:
                    # Empty bot moving toward something
                    bots_picking_active += 1  # assume assigned
            else:  # WAIT
                bots_parking += 1

        productive = bots_delivering + bots_picking_active
        per_round_active.append(productive)

        game.step(actions)

    # Summary
    import statistics
    avg_productive = statistics.mean(per_round_active)
    print(f"Seed {seed_idx}: score={game.score}")
    print(f"  Avg productive bots/round: {avg_productive:.2f} / 5")
    print(f"  Productive distribution:")
    from collections import Counter
    dist = Counter(per_round_active)
    for k in sorted(dist):
        pct = dist[k] * 100 / len(per_round_active)
        bar = "#" * int(pct / 2)
        print(f"    {k} bots: {dist[k]:4d} rounds ({pct:.1f}%) {bar}")

    # Per-50-round breakdown
    print(f"\n  Per-50-round productive bot average:")
    for start in range(0, 300, 50):
        chunk = per_round_active[start:start+50]
        if chunk:
            avg = statistics.mean(chunk)
            print(f"    R{start:3d}-{start+49}: {avg:.2f} productive bots/round")
