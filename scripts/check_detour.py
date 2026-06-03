"""Check how often the detour routing triggers and what detour costs look like."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from modules.bot.orders import compute_needed_items, items_matching_active
from modules.bot.grid import Grid
from modules.bot.pathfinding import find_all_pickup_positions, bfs_distances_from
from pathlib import Path
from collections import Counter

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

game = MultiBotGame.from_log(valid[0])
engine = OptimizedEngine(debug=False)

detour_costs = []  # all computed detour costs for delivering bots

while not game.game_over:
    state = game.get_state()
    grid = Grid(state.grid)
    drop_off = (state.drop_off[0], state.drop_off[1])
    item_blocked = frozenset((it.position[0], it.position[1]) for it in state.items)
    item_blocked_set = set(item_blocked)
    dropoff_dist_map = bfs_distances_from(grid, drop_off, item_blocked_set)
    
    active_needs = compute_needed_items(state)
    items_by_type = {}
    for item in state.items:
        items_by_type.setdefault(item.type, []).append(item)
    
    for bot in state.bots:
        matching = items_matching_active(bot, state)
        if not bot.inventory or not matching:
            continue
        if len(bot.inventory) >= 3:
            continue
        
        bpos = bot.pos.as_tuple()
        d2d = dropoff_dist_map.get(bpos, 999)
        if d2d <= 5:
            continue
        
        for need_type in active_needs:
            for item in items_by_type.get(need_type, []):
                for pp in find_all_pickup_positions(grid, item.pos.as_tuple()):
                    if pp in item_blocked:
                        continue
                    d_bot_pp = abs(bpos[0] - pp[0]) + abs(bpos[1] - pp[1])
                    d_pp_drop = dropoff_dist_map.get(pp, 999)
                    detour = d_bot_pp + d_pp_drop - d2d
                    if detour < 20:  # only reasonable detours
                        detour_costs.append(detour)
    
    actions = engine.decide(state)
    game.step(actions)

print(f"Detour cost distribution (total {len(detour_costs)} evaluations):")
dist = Counter()
for d in detour_costs:
    bucket = max(-2, min(15, d))
    dist[bucket] += 1
for k in sorted(dist):
    bar = "#" * (dist[k] // 5)
    print(f"  detour={k:3d}: {dist[k]:5d} {bar}")

p25 = sorted(detour_costs)[len(detour_costs)//4] if detour_costs else 0
p50 = sorted(detour_costs)[len(detour_costs)//2] if detour_costs else 0
p75 = sorted(detour_costs)[3*len(detour_costs)//4] if detour_costs else 0
print(f"\nPercentiles: p25={p25} p50={p50} p75={p75}")
print(f"Total ≤ 3: {sum(1 for d in detour_costs if d <= 3)}")
print(f"Total ≤ 5: {sum(1 for d in detour_costs if d <= 5)}")
print(f"Total ≤ 8: {sum(1 for d in detour_costs if d <= 8)}")
