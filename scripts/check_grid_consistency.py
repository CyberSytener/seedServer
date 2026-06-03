import json

files = [
    "logs/bot/game_20260303_061422_hard.jsonl",
    "logs/bot/game_20260303_080415_hard.jsonl",
    "logs/bot/game_20260304_081241_hard.jsonl",
]
for fp in files:
    with open(fp) as f:
        state = json.loads(f.readline())["state"]
    grid = state["grid"]
    items = state["items"]
    drop = state["drop_off"]
    bots = [b["position"] for b in state["bots"]]
    item_types = sorted(set(it["type"] for it in items))
    wall_hash = hash(str(sorted([tuple(w) for w in grid["walls"]])))
    item_hash = hash(str(sorted([(it["type"], tuple(it["position"])) for it in items])))
    fname = fp.split("/")[-1]
    print(f"{fname}:")
    print(f"  Grid: {grid['width']}x{grid['height']}, walls={len(grid['walls'])}, items={len(items)}")
    print(f"  Drop: {drop}, Bots: {bots}")
    print(f"  Types: {item_types}")
    print(f"  Wall hash: {wall_hash}, Item hash: {item_hash}")
    print()
