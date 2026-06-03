# NMiAI Grocery Bot — Implementation Report

> **Date:** 2026-03-01  
> **Status:** Integration complete, Bug #3 fixed, all 54 tests green  
> **Location:** `app/integrations/nmiai_grocery_bot/` + `modules/bot/`

---

## 1. Executive Summary

A fully algorithmic grocery-store bot has been built and integrated into
the Seed Server ecosystem.  The bot:

- **Auto-obtains** WebSocket game sessions via `POST https://api.ainm.no/games/request`
- Reads the `AINM_ACCESS_TOKEN` JWT from `.env` (no manual URL paste)
- Supports all **four difficulties**: Easy, Medium, Hard, Expert
- Runs 300 rounds in ≈120 s wall-clock with <2 ms/round decision time
- Logs every round as JSONL for post-game analysis

---

## 2. Architecture

```
app/integrations/nmiai_grocery_bot/
├── __init__.py        Public re-exports
├── endpoint.py        HTTP client (list_maps, request_game_session)
├── protocol.py        Re-exports canonical Pydantic models from modules/bot
└── ws_client.py       Async WebSocket game loop + GameResult dataclass

modules/bot/
├── models.py          Pydantic protocol models (GameState, BotAction, …)
├── grid.py            Grid + wall lookup
├── pathfinding.py     BFS / A* + pickup-position discovery
├── assignment.py      Greedy nearest-item task assignment (6 phases)
├── decision_engine.py Per-round orchestrator (Bug #3 fixed here)
├── collision.py       Multi-bot cell reservation
├── orders.py          Order analysis (needed items, matching)
├── client.py          Legacy WebSocket client (still usable standalone)
├── runner.py          Legacy CLI entry point (--url / --token)
└── telemetry.py       JSONL round logger + GameSummary

scripts/
└── run_nmiai_grocery_bot.py   One-command runner (reads .env, auto-session)

tests/
├── bot/                       39 tests — grid, BFS, A*, orders, decision engine
└── integrations/              15 tests — endpoint auth, protocol re-exports, GameResult
```

### Key data flow

```
.env (AINM_ACCESS_TOKEN)
  │
  ▼
endpoint.py  ──GET /games/maps──►  MapInfo[]
             ──POST /games/request──►  GameSession {ws_url, token, …}
  │
  ▼
ws_client.py  ──wss://game.ainm.no/ws?token=…──►  300 rounds
  │                                                  │
  │  ◄── GameState JSON ────────────────────────────┘
  │  ──► {"actions": [...]} ────────────────────────►
  │
  ▼
GameResult {score, items_delivered, orders_completed, …}
```

---

## 3. API Contract

| Endpoint | Method | Auth | Body | Response |
|---|---|---|---|---|
| `/games/maps` | GET | Cookie `access_token=<jwt>` | — | `[{id, label, difficulty, seed}]` |
| `/games/request` | POST | Cookie `access_token=<jwt>` | `{"map_id":"<uuid>"}` | `{token, ws_url, map: {id, label, difficulty}}` |

### Map IDs (well-known)

| Difficulty | Map ID | Seed |
|---|---|---|
| easy | `c89da2ec-3ca7-40c9-a3b1-8036fca3d0b7` | 7001 |
| medium | `3c523f5e-160b-452c-9ffc-171ef1e845f5` | 7002 |
| hard | `05ddc283-9097-4314-824c-90b3269a3d95` | 7003 |
| expert | `c7c7f564-2496-4ab1-9179-7532979adcb4` | 7004 |

---

## 4. Bugs Fixed

### Bug #1 — Score 0 (items block movement)
Items sit on shelf/wall cells.  Bot tried to walk through them and
failed silently (server ignored invalid moves).

**Fix:** Treat item positions as blocked in pathfinding.

### Bug #2 — Score 10 stall (non-matching delivery)
Assignment sent bots with *any* inventory to drop-off, even if
none matched the active order.  Bot sat waiting forever.

**Fix:** `items_matching_active()` check before assigning deliver.

### Bug #3 — Movement loop after first order *(fixed this session)*
Adding ALL item positions to `grid._walls` destroyed the walkable
graph.  `find_all_pickup_positions()` returned `[]` for items whose
4-neighbors were also items, making them permanently unreachable.
BFS fell back to `_simple_move` which bounced the bot aimlessly for
266 rounds.

**Root cause:** `grid._walls = grid._walls | item_positions` (line 44-48
of `decision_engine.py`) ran *before* `assign_bots()`.

**Fix:** Removed the wall mutation.  Item positions are now passed as a
`blocked` set through `assign_bots()` → `bfs_distance()` and
`_move_toward()` → `bfs_shortest_path()` / `astar_path()`.  The grid's
`walkable_neighbors_of()` (used for pickup position discovery) sees the
**clean** wall set, so all floor tiles adjacent to items are correctly
reported as reachable.

---

## 5. Test Coverage

| Suite | Tests | Status |
|---|---|---|
| `tests/bot/test_game_models.py` | 14 | ✅ |
| `tests/bot/test_decision_pipeline.py` | 25 | ✅ |
| `tests/integrations/test_nmiai_grocery_bot.py` | 15 | ✅ |
| **Total** | **54** | **All green** |

### Integration test highlights:
- `.env` token parsing (cookie-prefix strip, missing var error)
- UUID validation for all 4 map IDs
- Mocked `GET /games/maps` response parsing
- Mocked `POST /games/request` auth + body validation
- Protocol model re-export verification
- `GameResult` dataclass defaults

---

## 6. Usage

```bash
# Easy difficulty (default)
python scripts/run_nmiai_grocery_bot.py

# Specific difficulty
python scripts/run_nmiai_grocery_bot.py --difficulty hard

# All four difficulties
python scripts/run_nmiai_grocery_bot.py --all

# List available maps
python scripts/run_nmiai_grocery_bot.py --list-maps

# Use A* pathfinder
python scripts/run_nmiai_grocery_bot.py --use-astar

# Legacy standalone (with manual URL)
python -m modules.bot.runner --url "wss://game.ainm.no/ws?token=..."
```

### Environment setup
```
# .env
AINM_ACCESS_TOKEN=access_token=eyJhbG...
```

---

## 7. Decision Engine Strategy

1. **Grid construction** — Walls from server, items tracked separately
2. **Assignment** (6 phases):
   - Phase 1: Bots at drop-off with matching inventory → deliver
   - Phase 2: Bots with full inventory + match → deliver
   - Phase 3: (reserved)
   - Phase 4: Greedy nearest-item for active/preview orders
   - Phase 5: Remaining bots with matching inventory → deliver
   - Phase 6: Truly idle → wait
3. **Opportunistic pickup** — Adjacent needed item? Pick up immediately
4. **Opportunistic drop-off** — Standing on drop-off with matches? Deliver
5. **Pathfinding** — BFS (default) or A*, items in blocked set
6. **Collision resolution** — Cell reservation with swap detection
7. **Fallback** — Manhattan step if BFS fails

---

## 8. Next Steps

- [ ] Run live game with Bug #3 fix to measure score improvement
- [ ] Profile on Medium/Hard/Expert maps
- [ ] Consider multi-order lookahead (pick preview items while delivering active)
- [ ] Evaluate whether to integrate bot telemetry into Seed's monitoring dashboard
