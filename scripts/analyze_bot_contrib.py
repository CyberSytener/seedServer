"""Track which bots actually contribute to each order and items per trip."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from modules.bot.orders import get_active_order, compute_needed_items
from pathlib import Path
from collections import defaultdict

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

for seed_idx in [0]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = OptimizedEngine(debug=False)

    # Track per-order: which bots drop off, how many items each
    order_drops = defaultdict(lambda: defaultdict(int))  # order_id -> bot_id -> items_dropped
    current_order_id = None
    
    # Track per-bot trips: when does each bot pick up vs drop off?
    bot_last_pickup_round = {}
    bot_trip_items = defaultdict(int)  # items picked up since last drop
    trips = []  # (bot_id, items_carried, pickup_to_dropoff_rounds)

    while not game.game_over:
        state = game.get_state()
        active = get_active_order(state)
        if active:
            current_order_id = active.id
        
        actions = engine.decide(state)
        
        for a in actions.actions:
            bot = next(b for b in state.bots if b.id == a.bot)
            if a.action == BotAction.PICK_UP:
                if a.bot not in bot_last_pickup_round:
                    bot_last_pickup_round[a.bot] = state.round
                bot_trip_items[a.bot] += 1
            elif a.action == BotAction.DROP_OFF:
                items = len(bot.inventory)
                if current_order_id:
                    order_drops[current_order_id][a.bot] += items
                if a.bot in bot_last_pickup_round:
                    trip_len = state.round - bot_last_pickup_round[a.bot]
                    trips.append((a.bot, bot_trip_items[a.bot], trip_len))
                bot_last_pickup_round.pop(a.bot, None)
                bot_trip_items[a.bot] = 0
        
        game.step(actions)

    print(f"Score: {game.score}, Orders: {game.orders_completed}")
    print(f"\nPer-order bot contribution:")
    for oid in sorted(order_drops.keys(), key=lambda x: int(x.split('_')[1])):
        drops = order_drops[oid]
        n_bots = len(drops)
        total_items = sum(drops.values())
        bot_detail = " ".join(f"B{bid}:{cnt}" for bid, cnt in sorted(drops.items()))
        print(f"  {oid}: {n_bots} bots contributed {total_items} items  ({bot_detail})")

    print(f"\nTrip analysis ({len(trips)} trips):")
    items_per = [t[1] for t in trips]
    lens = [t[2] for t in trips]
    from statistics import mean
    print(f"  Avg items/trip: {mean(items_per):.2f}")
    print(f"  Avg trip length: {mean(lens):.1f} rounds")
    
    # Distribution of items per trip
    from collections import Counter
    item_dist = Counter(items_per)
    print(f"  Items/trip: {dict(sorted(item_dist.items()))}")
    
    # Per-bot trip count
    bot_trips = Counter(t[0] for t in trips)
    print(f"\n  Per-bot trip count: {dict(sorted(bot_trips.items()))}")
    
    # Per-bot items delivered
    bot_items = defaultdict(int)
    for bid, items, _ in trips:
        bot_items[bid] += items
    print(f"  Per-bot items: {dict(sorted(bot_items.items()))}")
