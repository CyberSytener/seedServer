"""Trace game log to find score transitions and diagnose stalls."""
import json
import sys

logfile = sys.argv[1] if len(sys.argv) > 1 else "logs/bot/game_20260228_071512_easy.jsonl"
prev_score = -1

with open(logfile) as f:
    for line in f:
        d = json.loads(line)
        r = d["round"]
        score = d["score"]
        actions = d["actions"]
        state = d.get("state", {})
        orders = state.get("orders", [])
        items = state.get("items", [])
        bots = state.get("bots", [])

        # Show score transitions and rounds 28-35
        show = (score != prev_score) or (28 <= r <= 35) or r == 0
        if show:
            bot = bots[0] if bots else {}
            pos = bot.get("position", "?")
            inv = bot.get("inventory", [])
            print(f"Round {r:3d}: score={score:3d} pos={pos} inv={inv}")
            print(f"  Actions: {actions}")
            if orders:
                for o in orders:
                    print(f"  Order {o['id']}: status={o['status']} "
                          f"req={o['items_required']} "
                          f"del={o['items_delivered']} "
                          f"complete={o['complete']}")
            print(f"  Items on map: {len(items)}")
            if score != prev_score:
                print(f"  ** SCORE CHANGED: {prev_score} -> {score} **")
            print()
        prev_score = score
