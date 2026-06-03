# NMiAI Grocery Bot — Dashboard

> Last updated: 2026-03-05 (Phase 3 synergy optimization session)

---

## Performance Summary

| Metric | Value |
|---|---|
| **Difficulty** | Hard |
| **Best Sim Score** | **149** |
| **Sim Avg (173 logs)** | **133.7** |
| **Stable Live Range** | 132 (current seed) |
| **Sim Avg Baseline** | 125.5 (first 28 logs) |
| **Improvement** | +8.2 avg (+24 peak) |
| **Theoretical Max** | ~450 (50 orders × 4 items + 50 × 5) |
| **Practical Ceiling** | ~160 (round budget limited) |
| **Avg Decision Time** | 1–4 ms |
| **Avg WebSocket RT** | ~98 ms |
| **Desync Rate (after fix)** | 0% |
| **Skip Rate** | 0% |

---

## Live Score History (Sessions)

```
Run  Score  Notes
───  ─────  ───────────────────────────────
 1    46    Pre-client fix, distance priority
 2    62    Pre-client fix
 3   133    ★ Client rewrite (sync decide + buffer drain)
 4    27    Outlier — drop-off deadlock (B4 empty WAIT forever)
 5   133    Stable
 6   131    Stable
 7   130    Stable
 8    71    Outlier (planner edge case)
 9   130    After drop-off deadlock fix
10   130    Stable
11   130    Stable
12   133    Stable
13   131    Stable
--- Phase 2 optimization session (03-04) ---
14   124    Congestion detection + proximity defer (new server seed)
15   124    ↑ Consistent on this seed
16   124    ↑
17   124    ↑
18    53    BFS detour budget=6 regression (fixed → manhattan)
19     9    Phase 2c auto-delivery deadlock (disabled)
20   126    Manhattan detour restored
21   124    Final config: tight congestion + manhattan defer ≤6
--- Phase 3 synergy optimization session (03-05) ---
22   132    Phase 3 synergy bonus (−3, dist≤6). Sim avg 133.7
```

**Baseline before session:** 10–88 (extreme variance, desync-driven)

---

## Key Optimizations Applied

| # | Optimization | Impact | Status |
|---|---|---|---|
| 1 | **WebSocket sync decide** | +60–70 live score | ✅ KEPT |
| 2 | **Buffer drain (latest state)** | Eliminates stale-state processing | ✅ KEPT |
| 3 | **Distance-based delivery priority** | +5 sim avg | ✅ KEPT |
| 4 | **Both-yield swap detection** | Matches server collision model | ✅ KEPT |
| 5 | **Drop-off deadlock prevention** | Fixes 27-score outlier | ✅ KEPT |
| 6 | **`_move_away_from` fallback** | Prevents permanent blocking | ✅ KEPT |
| 7 | **`_find_alternative_step` delta=2** | Breaks more deadlocks | ✅ KEPT |
| 8 | **Aisle congestion penalty** | Reduces corridor gridlock | ✅ KEPT |
| 9 | **Congestion detection (Phase 2)** | Fixes score=9 deadlocks, +6–30 sim | ✅ KEPT |
| 10 | **Proximity defer manhattan ≤6** | Multi-item batching, +7 avg | ✅ KEPT |
| 11b | **Phase 3 synergy bonus (−3, dist≤6)** | +2.2 sim avg, cluster preference | ✅ KEPT |
| 11 | **Endgame thresholds** | Disable defer R<25, desperate R<15 | ✅ KEPT |
| 12 | Staggered delivery (limit 2) | −19 sim avg regression | ❌ REVERTED |
| 13 | Pre-claiming collision | Too conservative | ❌ REVERTED |
| 14 | LEFT-first BFS | No improvement on hard | ❌ REVERTED |
| 15 | BFS-based detour (budget=6) | BFS≫manhat → 53-score regression | ❌ REVERTED |
| 16 | Auto-delivery Phase 2c | Fatal 9-score deadlock | ❌ DISABLED |
| 17 | Sorted delivery (closest first) | 112-score on 24% of seeds | ❌ REVERTED |
| 18 | Tapering budget (×4/deferral) | Too restrictive with BFS | ❌ REVERTED |

---

## Architecture at a Glance

```
                    ┌──────────────┐
 NMiAI Server ◄────┤  client.py   ├───► WebSocket (wss://game.ainm.no)
 (game_state)       │  sync decide │
                    │  buffer drain│
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  planner.py  │  OptimizedEngine.decide()
                    │ (~1000 lines)│
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Phase 1–2    Phase 3–3b   Phase 4
         drop-off     greedy       park idle
         & deliver    assignment   bots
              │            │            │
              └────────────┼────────────┘
                           ▼
                    ┌──────────────┐
                    │ collision.py │  resolve_collisions()
                    │ priority +   │  swap detection
                    │ both-yield   │
                    └──────────────┘
```

---

## Bot Module File Sizes

| File | Lines | Role |
|---|---|---|
| planner.py | ~1000 | **MAIN** multi-bot + easy planner |
| decision_engine.py | 358 | Legacy single-bot orchestrator (unused) |
| client.py | 163 | WebSocket client (optimized) |
| pathfinding.py | 170 | BFS, A*, distance maps |
| models.py | 137 | Pydantic models + Pos helper |
| max_score.py | 150 | Score estimation + order tracking |
| telemetry.py | 113 | JSONL round logger |
| orders.py | 103 | Order needs computation |
| collision.py | 92 | Collision resolver |
| runner.py | 88 | CLI entry point |
| grid.py | 56 | Grid walkability + neighbors |
| assignment.py | ~120 | Bot-item assignment (legacy) |
| autotune.py | ~80 | Parameter search utilities |
| **Total** | **~2,559** | |

---

## Map Topology (Hard)

```
Grid: 22 × 14   Walls: 108   Walkable cells: ~200
Bots: 5          Start: (20,12)   Drop-off: (1,12)
Items: 64        Types: 12 (cheese, milk, flour, oats, butter,
                              cream, yogurt, pasta, rice, cereal,
                              bread, eggs)
Rounds: 300      Orders: 50   Inv cap: 3 items/bot

Wall columns (shelves): x = 3, 5, 7, 9, 11, 13, 15, 17
Narrow aisles:          x = 4, 8, 12, 16
Horizontal corridors:   y = 1, 7, 11, 12
Edge corridors:         x = 1, x = 19–20
```

---

## Server Behavior (Confirmed)

- **Collision model**: Sequential bot-ID ascending. Lower-ID processes first → can vacate cell for higher-ID.
- **Swap detection**: Mutual A→B / B→A blocks BOTH bots.
- **Order sequence**: Deterministic. First 25 known, rest generated via `Random(42)`.
- **Round timing**: Server sends `game_state`, expects `actions` response. Late response → previous actions replayed.
- **Score formula**: $\text{score} = \text{items\_delivered} \times 1 + \text{orders\_completed} \times 5$

---

## Known Remaining Risks

1. **Seed-dependent variance** — score ranges 68–151 across sim seeds; some seeds have corridor gridlock patterns
2. **No dynamic re-assignment** — once a bot targets an item, it doesn't re-evaluate if a closer bot becomes free
3. **Parking can occupy useful paths** — idle bots in rows 1/7 may occasionally slow transit
4. **Expert difficulty untested** — only easy and hard modes validated
5. **Congestion detection scope** — only detects eviction-type stuck bots at drop-off; empty bots at drop-off don't trigger (by design, to avoid false positives)
