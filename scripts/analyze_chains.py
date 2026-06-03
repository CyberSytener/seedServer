"""Measure auto-delivery chain frequency and potential."""
from scripts._simulator_hard import MultiBotGame
from modules.bot.planner import OptimizedEngine
from modules.bot.models import BotAction
from pathlib import Path

logs = sorted(Path('logs/bot').glob('game_*hard*.jsonl'), key=lambda p: p.name)
valid = [l for l in logs if l.stat().st_size > 500000]

for seed_idx in [0, 3, 5, 10, 15]:
    game = MultiBotGame.from_log(valid[seed_idx])
    engine = OptimizedEngine(debug=False)

    prev_orders = 0
    chain_events = []  # (round, orders_completed_this_round)
    bots_at_dropoff_when_order_completes = []

    while not game.game_over:
        state = game.get_state()
        
        # Track bots at dropoff with non-matching preview items
        drop_off = (state.drop_off[0], state.drop_off[1])
        bots_at_do = sum(1 for b in state.bots if b.pos.as_tuple() == drop_off)
        bots_with_items_at_do = sum(1 for b in state.bots 
                                     if b.pos.as_tuple() == drop_off and b.inventory)
        
        actions = engine.decide(state)
        game.step(actions)
        
        orders_now = game.orders_completed
        if orders_now > prev_orders:
            completed = orders_now - prev_orders
            if completed > 1:
                chain_events.append((state.round, completed))
            bots_at_dropoff_when_order_completes.append(
                (state.round, bots_at_do, bots_with_items_at_do, completed))
            prev_orders = orders_now

    print(f"Seed {seed_idx}: score={game.score} orders={game.orders_completed}")
    chains = sum(1 for _, _, _, c in bots_at_dropoff_when_order_completes if c > 1)
    total_chain_orders = sum(c - 1 for _, _, _, c in bots_at_dropoff_when_order_completes if c > 1)
    print(f"  Chain events: {chains} (giving {total_chain_orders} free orders)")
    
    # Analyze potential: how many times were multiple bots at dropoff during completion?
    multi_bot_completions = [(r, b, bi, c) for r, b, bi, c in bots_at_dropoff_when_order_completes if b >= 2]
    print(f"  Completions with 2+ bots at dropoff: {len(multi_bot_completions)}")
    for r, b, bi, c in multi_bot_completions[:5]:
        print(f"    R{r}: {b} bots at DO, {bi} with items, completed {c}")
    
    # Check how often active order is 1 item from completion
    # (when chains could be engineered)
    print()
