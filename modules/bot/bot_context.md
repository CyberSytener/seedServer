# bot_context.md — NMiAI Grocery Bot: AI Agent Onboarding Guide

> This document provides everything an AI coding agent needs to understand, modify,
> and extend the NMiAI Grocery Bot system. Read this FIRST before touching any code.

---

## Table of Contents

1. [What Is This System](#1-what-is-this-system)
2. [Repository Layout](#2-repository-layout)
3. [Game Rules & Mechanics](#3-game-rules--mechanics)
4. [Map Topology (Hard)](#4-map-topology-hard)
5. [Server Protocol & Timing](#5-server-protocol--timing)
6. [Core Architecture](#6-core-architecture)
7. [Decision Pipeline (Phase-by-Phase)](#7-decision-pipeline-phase-by-phase)
8. [Collision Resolution](#8-collision-resolution)
9. [Pathfinding](#9-pathfinding)
10. [Key Data Structures](#10-key-data-structures)
11. [WebSocket Client](#11-websocket-client)
12. [Simulator & Benchmarking](#12-simulator--benchmarking)
13. [Known Bugs & Pitfalls](#13-known-bugs--pitfalls)
14. [Performance Baselines](#14-performance-baselines)
15. [Modification Guidelines](#15-modification-guidelines)
16. [Quick Reference: Key Functions](#16-quick-reference-key-functions)

---

## 1. What Is This System

A competitive AI bot for the **NMiAI Grocery Bot** game (https://ainm.no).
5 bots navigate a grocery store grid, pick up items from shelves, and deliver
them to a drop-off zone to fulfill orders. Score = items×1 + orders×5.

**Current performance:** 124–149 on Hard difficulty (sim avg 133.7), up from
130–133 baseline. See `strategy.md` for the 5-hypothesis optimization roadmap.

---

## 2. Repository Layout

```
modules/bot/                    ← CORE BOT CODE (edit here)
├── planner.py         (~1000 lines)  Main engine — OptimizedEngine class
├── strategy.md         (644 lines)  Optimization roadmap (5 hypotheses A–E)
├── collision.py         (92 lines)  Priority-based collision resolver
├── pathfinding.py      (170 lines)  BFS, A*, distance maps
├── grid.py              (56 lines)  Grid walkability + neighbors
├── orders.py           (103 lines)  Order need computation
├── models.py           (137 lines)  Pydantic models (GameState, BotAction, etc.)
├── client.py           (163 lines)  WebSocket client (latency-optimized)
├── max_score.py        (150 lines)  Score estimation + OrderTracker
├── telemetry.py        (113 lines)  JSONL game logger
├── runner.py            (88 lines)  CLI entry point
├── decision_engine.py  (358 lines)  Legacy engine (NOT used for hard)
├── assignment.py       (~120 lines) Legacy assignment (NOT used for hard)
├── autotune.py          (~80 lines) Parameter search utilities
├── planner_easy_138.py              Frozen easy planner snapshot
├── actions_schema.json              Action JSON schema
├── game_state_schema.json           State JSON schema
├── GROCERY_BOT_PROTOCOL.md          Protocol documentation
├── BOT_DASHBOARD.md                 Performance dashboard
└── BOT_ARCHITECTURE.md              Architecture diagrams (Mermaid)

scripts/                        ← TOOLING (analysis, debugging, benchmarking)
├── _live_hard.py                Run single live game
├── _bench.py                    Batch sim benchmark across saved logs
├── _simulator_hard.py           Offline game simulator (server-accurate collision)
├── _block_analysis.py           Analyze server-side move blocks
├── _wrong_dir.py                Detect wrong-direction moves (desync indicator)
├── _delay_theory.py             Test 1-round delay hypothesis
├── _game_summary.py             Action counts per bot from game log
├── _debug_27.py                 Debug 27-score outlier game
├── _grid_vis.py                 Visualize grid state
├── _trace_hard.py               Round-by-round trace for hard games
├── bot/diagnose.py              Bot diagnostic tool
├── bot/trace_log.py             Log tracer
└── ... (~100+ analysis/debug scripts)

app/integrations/nmiai_grocery_bot/   ← SERVER INTEGRATION
├── endpoint.py          (178 lines)  HTTP API: get game session / token → ws_url
├── protocol.py                       Protocol definitions
├── ws_client.py                      Alternative WS client (not main)
└── __init__.py

logs/bot/                       ← GAME LOGS (JSONL, ~100+ files)
├── game_YYYYMMDD_HHMMSS_hard.jsonl   Per-game logs with states + actions
├── debug_states.jsonl                 Debug state dumps
└── live_*.txt                         Live run stdout captures
```

---

## 3. Game Rules & Mechanics

| Property | Value |
|---|---|
| Grid | 22 × 14 cells |
| Bots | 5 (hard), start at (20,12) |
| Drop-off | (1, 12) |
| Max Rounds | 300 |
| Total Orders | 50 |
| Inventory Cap | 3 items per bot |
| Item Types | 12: cheese, milk, flour, oats, butter, cream, yogurt, pasta, rice, cereal, bread, eggs |
| Total Items | 64 on map |
| Score | items_delivered × 1 + orders_completed × 5 |

### Order Mechanics
- **Active order**: Must deliver ALL required items to complete. Only then does the next order activate.
- **Preview order**: Next order — visible but can't be directly completed yet.
- Completing an order earns the order bonus (5 points) PLUS 1 point per item delivered.
- Items are delivered individually via DROP_OFF at drop-off cell.
- Only items matching the **active order** count as delivered.

### Bot Actions (per round)
Each bot submits ONE action per round:
- `MOVE_UP` / `MOVE_DOWN` / `MOVE_LEFT` / `MOVE_RIGHT` — move 1 cell
- `PICK_UP` — pick up adjacent item (must be adjacent to shelf cell, provide `item_id`)
- `DROP_OFF` — deliver inventory at drop-off cell (must be standing on drop-off)
- `WAIT` — do nothing

### Order Sequence (Hard)
The first 25 orders are hardcoded and known. Remaining 25 are generated via `Random(42)` seed.
Full list in `planner.py` → `HARD_ORDERS` array.

---

## 4. Map Topology (Hard)

```
Y  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21
─────────────────────────────────────────────────────────────────────
0  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W
1  W  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  W
2  W  ·  W  S  A  S  W  ·  W  S  A  S  W  ·  W  S  A  S  W  ·  ·  W
...(rows 3-6 same pattern as row 2)
7  W  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  W
8  W  ·  W  S  A  S  W  ·  W  S  A  S  W  ·  W  S  A  S  W  ·  ·  W
...(rows 9-10 same pattern as row 8)
11 W  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  W
12 W  D  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  B  W
13 W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W  W
```

### Key topology facts:
- **Wall columns** (shelves with items): x = 3, 5, 7, 9, 11, 13, 15, 17
- **Narrow aisles** (1-wide, bottleneck): x = 4, 8, 12, 16
- **Horizontal corridors** (open rows): y = 1, 7, 11, 12
- **Edge corridors**: x = 1 (left), x = 19–20 (right, where bots start)
- **Drop-off**: (1, 12) — far left bottom
- **Bot start**: (20, 12) — far right bottom
- **Shelf rooms**: 6 rooms (3 across × 2 down), separated by wall columns at x = 2, 6, 10, 14, 18
- Items sit ON shelf cells (walls). Bots pick up from adjacent walkable aisle cells.

### Navigation implications:
- Bots must travel y=12 → y=1/7 to enter aisles
- Aisles are 1-cell wide → collision-prone, max 1 bot can pass
- Delivery path: aisle → corridor y=11/12 → left to drop-off (1,12)
- Average BFS distance from right aisles to drop-off: 20–30 steps

---

## 5. Server Protocol & Timing

### WebSocket Flow
```
Server → Client:  {"type": "game_state", "round": N, "bots": [...], ...}
Client → Server:  {"actions": [{"bot": 0, "action": "move_left"}, ...]}
Server → Client:  {"type": "game_state", "round": N+1, ...}
...
Server → Client:  {"type": "game_over", "score": 130, ...}
```

### CRITICAL Timing Constraint
- Server sends state, waits for response, then advances game.
- **If response arrives LATE**, the server applies PREVIOUS round's actions again.
- This causes "desync" — bot moves in wrong direction for 1+ rounds.
- **Solution**: Synchronous `decide()` call (no `asyncio.run_in_executor`), buffer draining.
- Decision compute is only 1–4ms. Total round-trip target: <100ms.

### Collision Model (Server-Side)
1. All bots submit actions simultaneously.
2. Server processes in **sequential bot-ID order** (ascending: bot 0 first, bot 4 last).
3. Lower-ID bot moves first → can vacate cell for higher-ID.
4. If target cell occupied → bot stays in place.
5. **Swap detection**: A→B + B→A → BOTH bots blocked.

---

## 6. Core Architecture

### Active Engine: `OptimizedEngine` (planner.py)

The ONLY engine used for hard difficulty. Entry: `decide(state: GameState) → RoundActions`.

Auto-detects mode:
- 1 bot → easy schedule-driven planner
- 5 bots → multi-bot phase-based planner

### Module Dependencies
```
planner.py ──→ collision.py ──→ models.py
           ──→ pathfinding.py ──→ grid.py ──→ models.py
           ──→ orders.py ──→ models.py
           ──→ max_score.py ──→ models.py
           ──→ grid.py
           ──→ models.py

client.py ──→ planner.py (OptimizedEngine)
          ──→ models.py
          ──→ telemetry.py

runner.py ──→ client.py
          ──→ planner.py
          ──→ telemetry.py
```

### NOT Used (Legacy)
- `decision_engine.py` — older `DecisionEngine` class. Uses `assignment.py`. Not connected.
- `assignment.py` — Bot-item assignment for legacy engine. Ignore for hard.
- `planner_easy_138.py` — Frozen snapshot. Reference only.

---

## 7. Decision Pipeline (Phase-by-Phase)

Every round, `_decide_multi()` executes these phases **in order**. Once a bot is handled in a phase, it skips all later phases.

### Phase 1: DROP_OFF
**Condition**: Bot at drop-off cell AND has inventory matching active order.
**Action**: `DROP_OFF` (stationary).
**Priority**: N/A (stationary, added to `occupied` set).

### Phase 1b: EVICT
**Condition**: Bot at drop-off cell AND has NON-matching inventory (wrong items).
**Action**: Move away from drop-off via `_move_away_from()`.
**Priority**: 3.
**Why**: Bot is blocking delivery for others.

### Phase 2: DELIVER
**Condition**: Bot has items matching active order (anywhere on map).
**Action**: Move toward drop-off via `_move_toward_direct()` (ignores other bots, lets collision resolver handle).
**Priority**: `10 + max(0, 30 - BFS_distance_to_dropoff)` — closer = higher priority.
**Special behaviors**:
- **Opportunistic pickup** — if inv<3 and adjacent to needed active item, picks up instead.
- **Congestion detection** — if a bot at drop-off needs to evict (has non-matching items) AND other bots are already delivering, delivery bots within BFS d≤3 of drop-off defer to prevent swap deadlocks.
- **Proximity defer** (manhattan ≤ 6) — if a nearby unassigned active-needed item has manhattan detour ≤ 6, bot defers delivery to batch multiple items. Capped at 2 deferred bots per round. Disabled during critical endgame (<25 rounds left).
- **Phase 2b** — deferred bots not assigned in Phase 3 proceed to deliver.

### Phase 3: ASSIGN (Greedy Item Assignment)
**Condition**: Available bot with inventory < 3, needed items exist.
**Algorithm**:
1. Pre-compute BFS distance map from each available bot.
2. Pre-compute BFS distance map from drop-off.
3. For each (needed_item, pickup_position, bot) triple, compute:
   ```
   cost = BFS_dist(bot→pickup) + return_dist(pickup→dropoff) × 0.9 + congestion_penalty + synergy
   ```
4. Congestion penalty: `other_bots_in_same_aisle × 3`
5. **Synergy bonus**: For each other active-needed item type within manhattan ≤ 6 of the candidate item, add −3 to cost. Encourages multi-item trips by preferring items near other needed items.
6. Filter: skip if `dist + return_dist + 2 > remaining_rounds`
7. Sort by cost ascending. Greedily assign (each bot/item used once).
**Priority**: 5.

### Phase 3b: PREFETCH (Future Orders)
**Condition**: Active needs were fully assigned in Phase 3 AND leftover bots exist.
**Algorithm**: Build lookahead needs from preview order + dynamically observed future orders (N+2..N+4).
Assign using same greedy cost model.
**Priority**: 2 (lowest — yields to everything).

### Phase 4: PARK (Idle Bots)
**Condition**: Bot not handled by any earlier phase.
**Actions**:
- If at drop-off AND empty inventory → `_move_away_from()` (prevents deadlock).
- Otherwise → find parking spot in rows 1 or 7, right half of map.
**Priority**: 0 (default).

### Collision Resolution (post-planning)
After all phases, moving bots' plans are passed to `resolve_collisions()`.
Blocked bots get `_find_alternative_step()` (accepts moves that increase distance by up to 1).

---

## 8. Collision Resolution

**File**: `collision.py` → `resolve_collisions(plans, occupied, priorities)`

### Algorithm
1. Register stationary bots' positions as claimed.
2. Sort moving bots by **priority DESC**, then **bot_id ASC**.
3. For each bot: if desired cell claimed → stay in place, mark current cell.
4. **Swap detection** (up to 5 iterations): if A→B and B→A, BOTH revert to current.
5. Return resolved positions.

### Alternative Step (`_find_alternative_step` in planner.py)
When a bot is blocked, tries all 4 directions. Accepts any step with
`new_manhattan_distance - current_distance < 2` (closer, lateral, or 1-step away).
Critical for breaking swap deadlocks.

### Priority System
| Phase | Priority Value | Meaning |
|---|---|---|
| Phase 2 (deliver) | 10–40 | Closer to drop-off = higher |
| Phase 3 (assign) | 5 | Standard |
| Phase 1b (evict) | 3 | Low — shouldn't block delivery |
| Phase 3b (prefetch) | 2 | Lowest moving priority |
| Phase 4 (park) | 0 | Yields to everything |

---

## 9. Pathfinding

**File**: `pathfinding.py`

### BFS (primary)
```python
bfs_shortest_path(grid, start, goal, blocked, prefer_left=False) → list[pos] | None
```
- Neighbor order: UP, DOWN, LEFT, RIGHT (or LEFT, UP, DOWN, RIGHT if `prefer_left=True`)
- `blocked` set includes item positions (shelves) and optionally other bot positions
- Returns full path including start and goal

### BFS Distance Map (flood-fill)
```python
bfs_distances_from(grid, start, blocked) → dict[(x,y), int]
```
Used extensively: pre-compute once, look up distances O(1). Every round computes:
- `dropoff_dist_map` — distance from drop-off to every cell
- `bot_dist_maps[bot_id]` — distance from each available bot to every cell

### A* (available but not primary)
```python
astar_path(grid, start, goal, blocked) → list[pos] | None
```
Manhattan heuristic. Same interface as BFS. Not currently used in production.

### Pickup Positions
```python
find_all_pickup_positions(grid, item_pos) → list[(x,y)]
```
Returns walkable cells adjacent to a shelf (item is on wall, must stand next to it).

---

## 10. Key Data Structures

### GameState (from server, models.py)
```python
class GameState(BaseModel):
    round: int              # Current round number (0-indexed)
    max_rounds: int         # 300 for hard
    grid: GridInfo          # {width, height, walls: [[x,y], ...]}
    bots: list[BotInfo]     # [{id, position: [x,y], inventory: ["cheese",...]}]
    items: list[ItemInfo]   # [{id, type, position: [x,y]}]
    orders: list[OrderInfo] # [{id, items_required, items_delivered, complete, status}]
    drop_off: list[int]     # [1, 12]
    score: int
    total_orders: int       # 50
```

### BotAction (enum, models.py)
```python
MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT, PICK_UP, DROP_OFF, WAIT
```

### Pos (lightweight, models.py)
```python
class Pos:  # NOT Pydantic, uses __slots__ for speed
    x: int
    y: int
    def manhattan(self, other) → int
    def as_tuple() → tuple[int, int]
```

### Grid (grid.py)
```python
class Grid:
    def is_walkable(x, y) → bool
    def neighbors(x, y) → list[tuple[int, int]]  # UP, DOWN, LEFT, RIGHT order
    def all_walkable() → list[tuple[int, int]]
    def walkable_neighbors_of(pos) → list[tuple[int, int]]
```

### Internal Planner State (per-round, not persisted)
```python
bot_positions: dict[int, tuple[int, int]]     # bot_id → (x, y)
bots_handled: set[int]                         # bots already assigned this round
bot_priorities: dict[int, int]                 # bot_id → priority for collision
move_plans: list[tuple[int, (x,y), (x,y)]]   # (bot_id, current, desired)
stationary: set[tuple[int, int]]               # cells occupied by non-moving bots
assigned_items: set[str]                        # item IDs already claimed this round
```

### Persistent State (across rounds)
```python
self._observed_orders: dict[str, list[str]]   # order_id → items_required
self._last_active_idx: int                     # index of current active order
self._order_tracker: OrderTracker              # score tracking
# Easy mode only:
self._trip_idx: int                            # schedule position
self._trip_route: list                         # current route waypoints
```

---

## 11. WebSocket Client

**File**: `client.py` → `GameWSClient`

### Key Design Decisions
1. **Synchronous `decide()`**: No `run_in_executor()`. Compute is 1–4ms — async overhead was causing desync.
2. **Buffer drain**: After `ws.recv()`, immediately try `ws.recv(timeout=0.001)` in loop. Always process LATEST state. Prevents stale-state accumulation if previous round was slow.
3. **Desync detection**: Tracks `_last_round`. If `state.round > _last_round + 1`, logs desync.
4. **Error recovery**: If `decide()` throws, sends WAIT for all bots (game continues).

### Usage
```python
engine = OptimizedEngine(debug=True)
logger = RoundLogger(log_dir="logs/bot", difficulty="hard", save_states=True)
client = GameWSClient(url="wss://game.ainm.no/ws?token=...", engine=engine, logger=logger)
result = await client.play()  # Returns GameOver
```

---

## 12. Simulator & Benchmarking

### Offline Simulator (`scripts/_simulator_hard.py`)
- `MultiBotGame` class — replays saved game logs through the planner.
- **Server-accurate collision model**: Sequential bot-ID processing.
- Used by `_bench.py` to test changes without burning live games.

### Benchmark (`scripts/_bench.py`)
- Runs simulator across ALL saved hard game logs (~165 logs).
- Reports per-game score vs baseline, and overall average.
- Current sim avg: **133.7** (up from ~125.5 baseline).
- Baseline array covers first 28 logs; remaining show `?`.

### Live Testing (`scripts/_live_hard.py`)
```powershell
python scripts/_live_hard.py
```
Runs a single live game against the server.

### Typical Workflow
1. Make code change in `planner.py`
2. Run `python scripts/_bench.py` — check sim avg doesn't regress
3. Run `python scripts/_live_hard.py` 2–3 times — verify live score
4. If regression: revert, try different approach

---

## 13. Known Bugs & Pitfalls

### CRITICAL — Do NOT Revert These Fixes
1. **Sync decide in client.py** — removing `run_in_executor()` fixed 60+ point regression from desync.
2. **Buffer drain in client.py** — must always process latest state.
3. **Both-yield swap detection in collision.py** — matches server behavior.
4. **Phase 4 empty-bot drop-off eviction** — prevents permanent deadlock (27-score bug).
5. **`_move_away_from` fallback** — must attempt move even through occupied cells.
6. **Phase 2 congestion detection** — delivery bots within d≤3 of drop-off defer when evicting bot is stuck. Prevents fatal score=9 swap deadlocks.
7. **Proximity defer uses manhattan (NOT BFS)** — BFS distances ≫ manhattan on this grid. Using BFS with budget=6 caused fatal 53-score regression.

### Known Remaining Issues
- **Corridor gridlock**: When 3+ bots converge in same narrow aisle, spiral wait can occur. Causes rare 68–97 score games on specific seeds.
- **No dynamic re-assignment**: Once bot targets an item, it won't switch even if closer bot becomes free.
- **Parking position selection**: Static preference for rows 1/7. Can occasionally block transit paths.
- **Phase 1b priority=3**: Originally tried higher priority (20) but caused cascade swap deadlocks. Must stay low.
- **Seed-dependent variance**: Score varies 97–151 across game seeds due to item layout and order sequences.

### Things That Were Tried and FAILED
| Approach | Why It Failed |
|---|---|
| Staggered delivery (limit 2 bots) | Sim avg −19 — too conservative |
| Pre-claiming in collision resolver | Made resolver too conservative, blocked too many bots |
| LEFT-first BFS (`prefer_left=True`) | No improvement on hard map topology |
| Block memory (remember past blocks) | Added complexity without improvement |
| Sequential resolver (match server exactly) | Too conservative client-side |
| Phase 1b with priority=20 | Caused swap deadlocks with delivery bots |
| BFS-based detour (budget=6) | BFS ≫ manhattan on this grid → 53-score regression |
| Auto-delivery engineering (Phase 2c) | Multiple bots converging on drop-off → fatal score=9 deadlock |
| Sorted delivery (closest first) | Fixed some deadlocks but created 112-score on 24% of seeds |
| Sorted delivery (farthest first) | Catastrophic 64-69 scores — far bots waste rounds detour |
| Inventory-priority sort | Full-inventory bots first → single-item bots all defer → deadlocks |
| Defer bonus -15 (Phase 3 cost) | Cascading assignment distortion → 19-score catastrophic |
| Proximity threshold 4 or 8 | No improvement over 6 (optimal sweet spot) |
| Tapering budget (deferrals×4) | With BFS, too restrictive. With manhattan at ×2, minimal effect |
| Desperate endgame (disable Phase 3b at R<15) | No measurable improvement |
| Synergy weight −4 or −5 | −4: avg 128.1 (−5.6 regression); −5: min dropped to 55 |
| Synergy distance ≤5 or ≤7 | ≤5: avg 133.0 (−0.7); ≤7: avg 132.9 (−0.8) |
| Proximity defer threshold 8 | avg 123.2 (−10.5 regression) |
| Reservation system (−15 lock bonus) | avg 123.8 — distorted Phase 3 assignments |
| Congestion ×6 | avg 93.0 — catastrophic, bots avoid all populated aisles |
| Preview adjacent pickup (Phase 2) | avg 122.8 — delayed active deliveries |
| Order-completion defer 12 | avg 122.4 — over-deferral on most seeds |
| Pair-lock nearby items (dist ≤3–4) | avg 132.3–132.8 — starved other bots |

---

## 14. Performance Baselines

| Metric | Before Optimization | Phase 1 (desync fix) | Phase 2 (current) |
|---|---|---|---|
| Live Score Range | 10–88 | 130–133 | 124–149 (seed-dependent) |
| Sim Avg (all logs) | ~127 | 125.5 (first 28) | **133.7** |
| Desync Rate | 11–18% | 0% | 0% |
| Decision Time | 8–20ms (async) | 1–4ms (sync) | 1–4ms (sync) |
| Round-Trip Time | 120–200ms | ~98ms | ~80ms |

### Reference Scores
- Best sim: **149** (some seeds hit +20 over baseline)
- Live (current server seed): **132** (up from 124 after synergy bonus)
- Sim avg (173 logs): **133.7** (up from ~125.5 baseline)
- Worst sim outlier: **97** (seed-specific corridor gridlock — rare)
- Theoretical max: ~450 (all 50 orders × ~4 items + 50 × 5)
- Practical ceiling: ~160–180 (round-budget limited)

### Key Improvement: Congestion Detection + Proximity Defer + Synergy Bonus
The main gain (+6–30 points on many seeds) comes from the congestion detection
system that prevents delivery bots from creating swap deadlocks at the drop-off.
Bots within BFS d≤3 of the drop-off defer when an evicting bot needs to escape.
The proximity defer (manhattan ≤ 6) enables multi-item trip batching.
The synergy bonus (−3 per nearby active-needed item type within manhattan ≤ 6) added +2.2 sim avg by encouraging bots to pick up items in clusters.

---

## 15. Modification Guidelines

### Before Changing Code
1. Read this document fully.
2. Run `python scripts/_bench.py` to get baseline sim avg.
3. Understand which phase the change affects.

### Making Changes
- **planner.py** is the main file. Most optimization happens here.
- **collision.py** — be VERY careful. Must match server's sequential model.
- **client.py** — do NOT add async overhead. Keep decide() synchronous.
- **pathfinding.py** — BFS neighbor order matters for path tie-breaking.

### Testing Protocol
1. `python scripts/_bench.py` — must not regress by >2 points.
2. `python scripts/_live_hard.py` — run 3+ times, check consistency.
3. If score drops: revert immediately, investigate with debug scripts.

### Key Invariants (DO NOT BREAK)
- `decide()` must complete in <10ms (typical 1–4ms).
- Collision resolution must produce conflict-free positions.
- Active order items have strict priority over preview items.
- Bots at drop-off with matching inventory ALWAYS drop off (Phase 1).
- Empty bots at drop-off ALWAYS move away (Phase 4).

### Debug Utilities
```powershell
# Analyze blocks in a game log
python scripts/_block_analysis.py logs/bot/game_XXXXX_hard.jsonl

# Check for wrong-direction moves (desync indicator)
python scripts/_wrong_dir.py logs/bot/game_XXXXX_hard.jsonl

# Round-by-round trace
python scripts/_trace_hard.py logs/bot/game_XXXXX_hard.jsonl

# Action count summary per bot
python scripts/_game_summary.py logs/bot/game_XXXXX_hard.jsonl

# Grid visualization
python scripts/_grid_vis.py logs/bot/game_XXXXX_hard.jsonl [round]
```

---

## 16. Quick Reference: Key Functions

### planner.py — OptimizedEngine
| Method | Purpose |
|---|---|
| `decide(state)` | Main entry point — returns `RoundActions` |
| `_decide_multi(state)` | Multi-bot planner (5 bots, hard) |
| `_decide_easy(state)` | Schedule-driven planner (1 bot, easy) |
| `_assign_bot_to_item(...)` | Common pickup/move logic |
| `_move_toward_multi(...)` | BFS path avoiding other bots |
| `_move_toward_direct(...)` | BFS path ignoring other bots (delivery) |
| `_find_alternative_step(...)` | Alt direction when blocked (delta≤2) |
| `_move_away_from(...)` | Move away from cell with fallback |
| `_find_parking_far(...)` | Find parking in rows 1/7 right half |
| `_build_route(...)` | Easy mode: optimal TSP pickup route |

### collision.py
| Function | Purpose |
|---|---|
| `resolve_collisions(plans, occupied, priorities)` | Priority-based resolver + swap detection |
| `action_for_move(current, target)` | Convert (x,y) delta to BotAction |

### pathfinding.py
| Function | Purpose |
|---|---|
| `bfs_shortest_path(grid, start, goal, blocked)` | Full BFS path |
| `bfs_distances_from(grid, start, blocked)` | Flood-fill distance map |
| `bfs_distance(grid, start, goal, blocked)` | Single-pair distance |
| `find_all_pickup_positions(grid, item_pos)` | Walkable neighbors of shelf |
| `astar_path(grid, start, goal, blocked)` | A* (not used in production) |

### orders.py
| Function | Purpose |
|---|---|
| `compute_needed_items(state)` | Active order needs minus in-transit |
| `compute_preview_items(state)` | Preview needs minus auto-deliverable |
| `items_matching_active(bot, state)` | Bot inventory matching active order |
| `get_active_order(state)` | Current active OrderInfo |
| `get_preview_order(state)` | Next preview OrderInfo |

### models.py
| Class | Purpose |
|---|---|
| `GameState` | Full server state per round |
| `BotInfo` | Bot id, position, inventory |
| `ItemInfo` | Item id, type, position |
| `OrderInfo` | Order requirements + delivery status |
| `BotAction` | Enum: MOVE_UP/DOWN/LEFT/RIGHT, PICK_UP, DROP_OFF, WAIT |
| `RoundActions` | Collection of bot commands for one round |
| `Pos` | Lightweight (x,y) — NOT Pydantic, uses `__slots__` |

---

## Appendix: Hard Order Sequence (First 25)

```
 #  Items
 0  cheese, milk, flour
 1  flour, oats, butter, cream, cheese
 2  cream, yogurt, pasta
 3  oats, cheese, bread
 4  oats, cheese, cereal
 5  flour, butter, eggs, butter, pasta
 6  rice, rice, rice
 7  cereal, cheese, cheese
 8  oats, cereal, cream, cereal, flour
 9  cheese, pasta, yogurt
10  oats, milk, cereal
11  flour, cream, milk, cream
12  cheese, bread, butter
13  flour, butter, rice, cereal, cream
14  yogurt, rice, cheese, flour
15  pasta, oats, milk, cheese
16  butter, bread, yogurt, cream, cheese
17  cereal, yogurt, butter
18  yogurt, oats, butter, pasta, flour
19  bread, butter, cheese
20  oats, pasta, bread
21  cheese, yogurt, rice, yogurt, oats
22  cheese, milk, pasta, cream
23  cereal, yogurt, flour
24  cream, cereal, cheese, eggs
```

Orders 25–49 are generated runtime via `Random(42)` and tracked dynamically in `_observed_orders`.
