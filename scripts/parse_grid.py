"""Parse hard mode game log and visualize the grid."""
import json

with open("logs/bot/game_20260303_061422_hard.jsonl") as f:
    first = json.loads(f.readline())

state = first["state"]
W = state["grid"]["width"]
H = state["grid"]["height"]
walls_raw = state["grid"]["walls"]
drop_off = tuple(state["drop_off"])
bots = state["bots"]
items = state["items"]

print(f"Grid: {W}x{H}")
print(f"Drop-off: {drop_off}")
print(f"Walls: {len(walls_raw)}")
print(f"Bots: {len(bots)}")
print(f"Items: {len(items)}")
print()

# Build wall set
wall_set = set()
for w in walls_raw:
    wall_set.add((w[0], w[1]))

# Item map
item_map = {}
for it in items:
    pos = (it["position"][0], it["position"][1])
    item_map[pos] = it["type"]

# Bot map
bot_map = {}
for b in bots:
    pos = (b["position"][0], b["position"][1])
    bot_map[pos] = b["id"]

# Build visual grid
print("=== GRID VISUALIZATION ===")
print("Legend: # = wall, . = walkable, D = drop-off, 0-9 = bot, first letter = item on shelf")
print()

# Header with x coords
header = "   "
for x in range(W):
    header += f"{x:2d}"
print(header)

for y in range(H):
    row = f"{y:2d} "
    for x in range(W):
        pos = (x, y)
        if pos == drop_off:
            row += " D"
        elif pos in bot_map:
            row += f" {bot_map[pos]}"
        elif pos in item_map:
            row += f" {item_map[pos][0].upper()}"
        elif pos in wall_set:
            row += " #"
        else:
            row += " ."
    print(row)

print()
print("=== BOT START POSITIONS ===")
for b in bots:
    print(f"  Bot {b['id']}: ({b['position'][0]}, {b['position'][1]})")

print()
print("=== DROP-OFF ===")
print(f"  ({drop_off[0]}, {drop_off[1]})")

print()
print("=== ITEMS BY TYPE ===")
from collections import defaultdict
by_type = defaultdict(list)
for it in items:
    by_type[it["type"]].append((it["position"][0], it["position"][1]))
for t in sorted(by_type.keys()):
    positions = sorted(by_type[t])
    print(f"  {t}: {positions}")

print()
print("=== ITEMS BY POSITION (sorted by x, then y) ===")
for it in sorted(items, key=lambda i: (i["position"][0], i["position"][1])):
    print(f"  ({it['position'][0]:2d}, {it['position'][1]:2d}) = {it['type']:12s} [{it['id']}]")

# Analyze aisles
print()
print("=== AISLE ANALYSIS ===")
# Items are on wall cells. Find vertical columns that contain items
item_cols = defaultdict(list)
for it in items:
    item_cols[it["position"][0]].append(it["position"][1])

for col in sorted(item_cols.keys()):
    rows = sorted(item_cols[col])
    print(f"  Column x={col}: items at y={rows}")

# Find walkable columns between shelf columns
print()
print("=== WALKABLE COLUMNS (potential aisles) ===")
for x in range(W):
    walkable_count = sum(1 for y in range(H) if (x, y) not in wall_set)
    if walkable_count > H // 2:
        print(f"  Column x={x}: {walkable_count}/{H} walkable")

# Distance analysis
print()
print("=== DISTANCES FROM DROP-OFF ===")
from collections import deque
# BFS from drop-off
dist = {}
q = deque()
start = drop_off
dist[start] = 0
q.append(start)
while q:
    cx, cy = q.popleft()
    for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
        nx, ny = cx+dx, cy+dy
        if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in wall_set and (nx, ny) not in dist:
            dist[(nx, ny)] = dist[(cx, cy)] + 1
            q.append((nx, ny))

# For each item, find nearest walkable cell and its distance
print("Distance from drop-off to each item's adjacent walkable cell:")
for it in sorted(items, key=lambda i: i["type"]):
    ix, iy = it["position"]
    # Find adjacent walkable cells
    adj_dists = []
    for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
        nx, ny = ix+dx, iy+dy
        if (nx, ny) in dist:
            adj_dists.append(dist[(nx, ny)])
    min_dist = min(adj_dists) if adj_dists else -1
    print(f"  {it['type']:12s} at ({ix:2d},{iy:2d}): min_dist={min_dist}")

# Aisle distances summary
print()
print("=== AISLE DISTANCE SUMMARY ===")
aisle_groups = defaultdict(list)
for it in items:
    ix = it["position"][0]
    adj_dists = []
    for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
        nx, ny = ix+dx, it["position"][1]+dy
        if (nx, ny) in dist:
            adj_dists.append(dist[(nx, ny)])
    if adj_dists:
        aisle_groups[ix].append(min(adj_dists))

for col in sorted(aisle_groups.keys()):
    dists = aisle_groups[col]
    print(f"  Shelf column x={col}: avg_dist={sum(dists)/len(dists):.1f}, min={min(dists)}, max={max(dists)}")

# Bot distances
print()
print("=== BOT START DISTANCES FROM DROP-OFF ===")
for b in bots:
    bpos = (b["position"][0], b["position"][1])
    d = dist.get(bpos, -1)
    print(f"  Bot {b['id']} at {bpos}: distance={d}")
