# BOT_TASKS.md — Optimization Roadmap & Testing Strategy

> Target: Push live score from **130–133** toward **145–160** (practical ceiling).
> Last updated: 2026-03-03

---

## Table of Contents

1. [Current State Summary](#current-state-summary)
2. [Score Decomposition & Ceiling Analysis](#score-decomposition--ceiling-analysis)
3. [Priority Tiers](#priority-tiers)
4. [Tier 1 — High Impact (Expected +5–15 points)](#tier-1--high-impact)
5. [Tier 2 — Medium Impact (Expected +2–8 points)](#tier-2--medium-impact)
6. [Tier 3 — Low Impact / Speculative (+1–5 points)](#tier-3--low-impact--speculative)
7. [Tier 4 — Infrastructure & Tooling](#tier-4--infrastructure--tooling)
8. [Testing Strategy](#testing-strategy)
9. [Experiment Log Template](#experiment-log-template)
10. [Risk Register](#risk-register)

---

## Current State Summary

| Metric | Value |
|---|---|
| Stable live score | 130–133 |
| Best live | 133 |
| Worst live (post-fixes) | 71 (rare corridor gridlock) |
| Sim avg (28 games) | ~99.5 |
| Decision time | 1–4 ms |
| Orders completed per game | ~18–20 (of 50) |
| Items delivered per game | ~60–70 |
| Rounds wasted (WAITs + blocks) | ~40–60 per game |
| Active phase (collecting) | ~200 rounds |
| Delivery phase (transit) | ~100 rounds |

**Bottom line**: We complete ~18–20 of 50 orders in 300 rounds. Each order takes ~15 rounds avg. The main levers are: (a) reduce wasted rounds, (b) reduce trip distance, (c) increase bot utilization, (d) reduce corridor collisions.

---

## Score Decomposition & Ceiling Analysis

### Current score breakdown (typical 131 game)
```
Orders completed:  ~19 × 5 = 95 points (order bonus)
Items delivered:   ~36     = 36 points (item bonus)
                            ─────────
Total:                      ~131
```

### Theoretical improvement paths
```
              Current    Target     Delta   How
Orders:       19         24         +5      Faster cycles → more orders
Items/order:  ~1.9 avg   ~3.0 avg   +22    Fill inventory → deliver more items
Wasted rounds:  ~50       ~25       -25     Fewer WAITs/blocks → more actions
Trip distance:  ~15 avg   ~12 avg    -3/trip  Better item selection → shorter trips

Potential target: 24×5 + 72 = 192 (aggressive)
Realistic target: 22×5 + 55 = 165 (achievable)
```

---

## Priority Tiers

| Tier | Tasks | Expected Impact | Risk |
|---|---|---|---|
| **Tier 1** | 6 tasks | +5–15 points total | Medium |
| **Tier 2** | 6 tasks | +2–8 points total | Low–Medium |
| **Tier 3** | 5 tasks | +1–5 points total | High (speculative) |
| **Tier 4** | 5 tasks | Infrastructure (enables other tiers) | Low |

---

## Tier 1 — High Impact

### T1.1 — Drop-Off Queuing & Pipelining
**Problem**: Multiple bots arrive at drop-off simultaneously, but only 1 can drop at a time. Others WAIT 1–3 rounds, blocking the corridor.

**Current behavior**: Phase 2 sends ALL matching bots toward drop-off. They arrive together, collide near (1,12), and queue inefficiently.

**Proposed solution**:
1. Track how many bots are within 3 steps of drop-off.
2. If ≥2 bots converging, delay lower-priority bots (WAIT or grab nearby preview items).
3. Ensure only 1 bot is "en route to drop-off" at a time over the final 3 cells.
4. Second bot can start approaching when first is within 1 step of drop-off.

**Key metric**: Reduce "WAIT at/near drop-off" rounds from ~15–20/game to <5.

**Files to modify**: `planner.py` (Phase 2 delivery logic)

**Sim-testable**: YES — track WAIT count near drop-off in bench.

---

### T1.2 — Multi-Item Pickup Trips (Fill Inventory to 3)
**Problem**: Bots often deliver with only 1–2 items in inventory. 3-item trips are 50% more efficient per round spent.

**Current behavior**: Phase 3 assigns one item per bot. Bot picks up, has inventory=1, and if it matches active order, Phase 2 sends it to delivery immediately — even though there are more needed items nearby.

**Proposed solution**:
1. When bot picks up item #1 and active order still needs more items, check: is another needed item within ~5 BFS steps? If yes, go pick that up first (don't deliver yet).
2. Phase 2 delivery trigger: only deliver when (a) inventory full (=3), OR (b) this bot carries ALL remaining needs for the active order, OR (c) no more needed items are reachable quickly (within detour_threshold rounds).
3. Add `deliver_threshold` parameter: max extra rounds allowed for detour pickup before delivering.

**Key metric**: Average items per delivery trip (target: 2.5+ from current ~1.9).

**Files to modify**: `planner.py` (Phase 2 trigger logic, Phase 3 multi-item planning)

**Sim-testable**: YES — track items-per-drop-off in bench.

---

### T1.3 — Corridor Traffic Flow (One-Way Lanes)
**Problem**: Narrow aisles (x=4,8,12,16) are 1-cell wide. Two bots entering from opposite ends deadlock, wasting 2–6 rounds each. This causes the ~71-score outlier games.

**Current behavior**: Aisle congestion penalty (×3) discourages crowding but doesn't prevent it. No directional awareness.

**Proposed solution**:
Option A — **Soft lane preference**:
1. Bots entering aisle from top (y=1→y=7) prefer moving DOWN. Bots entering from bottom (y=11→y=7) prefer moving UP.
2. If aisle already has a bot moving in opposite direction, penalize that aisle by +10 in assignment cost.
3. Track per-round aisle "direction" reservation: `aisle_dir[x] = "down" | "up" | None`.

Option B — **Time-sliced aisle access**:
1. Even rounds: bots with lower ID have aisle priority.
2. Odd rounds: bots with higher ID have aisle priority.
3. Non-priority bot WAITs at aisle entrance until slot opens.

**Recommended**: Start with Option A (simpler, less disruptive).

**Key metric**: Blocks/collisions in aisles per game (target: <10 from current ~20–30).

**Files to modify**: `planner.py` (Phase 3 assignment + `_move_toward_multi`)

**Sim-testable**: YES — track collision count per aisle in bench.

---

### T1.4 — Dynamic Re-Assignment Between Rounds
**Problem**: Once a bot targets an item in Phase 3, it pursues that item until pickup — even if next round a closer bot becomes free and could grab it faster.

**Current behavior**: `_decide_multi()` is stateless PER ROUND — no memory of previous assignments. BUT: the "state" is baked into bot positions (bot is already moving toward target). The greedy assignment re-runs each round based on current positions, which is somewhat dynamic. However, bots already carrying non-matching items (going to deliver) block available bots from being reassigned.

**Proposed solution**:
1. Track actual bot→item assignment across rounds: `_persistent_assignments: dict[int, str]`.
2. Each round, re-evaluate: if another bot is now closer to the target item AND the assigned bot has >5 BFS remaining, SWAP assignments.
3. Cap reassignment frequency to prevent oscillation (max 1 reassignment per bot per 5 rounds).

**Key metric**: Average pickup distance (target: –2 BFS steps from current).

**Files to modify**: `planner.py` (Phase 3, add persistent tracking)

**Sim-testable**: YES — track average BFS(bot→item) at assignment time.

---

### T1.5 — Smart Prefetch: Order Pipeline
**Problem**: When active order is about to complete (1 item remaining), all other bots are idle or parking. They should already be picking up items for the NEXT order.

**Current behavior**: Phase 3b prefetches preview items only when active needs are fully assigned. But "fully assigned" means all items have been assigned to bots — not necessarily picked up. The transition between orders creates a 5–10 round gap where bots are underutilized.

**Proposed solution**:
1. **Predict order completion**: When active order has ≤2 items still needing delivery (bot carrying them, within 5 rounds of drop-off), treat the preview order as "nearly active".
2. **Elevate preview priority**: Promote remaining bots from Phase 3b (priority 2) to Phase 3 (priority 5) for preview items in this "transition window".
3. **Pre-position near drop-off**: Bots with preview items should start moving toward drop-off area (not parking) so they're ready when order flips.

**Key metric**: Rounds between order completion and first item delivered for next order (target: <3 from current ~8).

**Files to modify**: `planner.py` (Phase 3/3b boundary logic)

**Sim-testable**: YES — track inter-order gap rounds.

---

### T1.6 — Delivery Corridor Reservation (y=12 Lane)
**Problem**: Row y=12 is the main east→west delivery corridor (drop-off at x=1). Parked or idle bots on y=12 block delivery bots, causing delays.

**Current behavior**: Phase 4 parks bots in rows 1/7 right half — good. But during transitions, bots may sit on y=11/12 while deciding, blocking delivery traffic.

**Proposed solution**:
1. Mark cells on y=12.x<10 as "delivery lane" — no parking allowed.
2. Any idle bot on y=12 with x<15 gets immediate priority to move north (y=11→y=7).
3. Delivering bots on y=12 get priority boost (+5) over all non-delivery bots on y=12.
4. Add "corridor clear" bonus to parking evaluation: never park on y=11/12.

**Key metric**: Delivery bot blocks on y=12.

**Files to modify**: `planner.py` (Phase 4 parking, collision priority)

**Sim-testable**: YES.

---

## Tier 2 — Medium Impact

### T2.1 — Bot-ID-Aware Planning (Exploit Server Sequential Processing)
**Problem**: Server processes moves in bot_id order (0→4). Bot 0 moves first and can vacate its cell for Bot 1. Our planner doesn't exploit this.

**Current behavior**: Collision resolver treats all bots symmetrically (sorted by priority, then bot_id). Doesn't model that Bot 0 physically moves before Bot 1 on the server.

**Proposed solution**:
1. When two bots need to swap/cross paths, prefer the plan where lower-ID bot moves first (vacates cell).
2. In assignments: if two bots are equally good for an item, prefer the one whose bot_id makes the movement collision-free under sequential processing.
3. In collision resolver: simulate sequential processing order instead of simultaneous claim model.

**Risk**: Previous attempt at "sequential resolver" was too conservative. The key is to use sequential knowledge for PLANNING (choosing plans), not for RESOLUTION (blocking moves).

**Sim-testable**: Requires simulator update to also model this correctly (already done).

---

### T2.2 — Endgame Time Pressure Mode
**Problem**: In the last 30–50 rounds, the bot still plans normally. It should switch to "time pressure" mode — only pick items that can definitely be delivered before round 300.

**Current behavior**: Phase 3 has `dist + return_dist + 2 > remaining_rounds` filter, but it's only a hard cutoff. No soft time-pressure adjustments.

**Proposed solution**:
1. When `remaining_rounds < 60`: increase delivery priority — bots with ANY matching items should deliver immediately (don't wait to fill inventory).
2. When `remaining_rounds < 40`: stop prefetching preview items entirely. Focus only on active order.
3. When `remaining_rounds < 20`: all bots with inventory → force delivery regardless of which order they match.
4. Add score-per-round target tracking: if falling behind, become more aggressive.

**Key metric**: Items delivered in final 50 rounds (target: +5 from current).

**Sim-testable**: YES — very measurable.

---

### T2.3 — Aisle Pre-Positioning
**Problem**: Bots travel from parking (rows 1/7 right half) to the correct aisle, then enter and pick up. This transit wastes 5–10 rounds per trip.

**Current behavior**: Idle bots park far from items. When assigned, they must traverse the full distance.

**Proposed solution**:
1. Instead of generic parking, park bots NEAR the aisles containing the most likely needed items (based on upcoming orders from `HARD_ORDERS`/`_observed_orders`).
2. Compute "item density" per aisle: which aisles have the most items matching orders N+1..N+3.
3. Park idle bots at the entrance (y=1 or y=7) of the highest-value aisle.

**Key metric**: Average first-step distance to assigned item.

**Sim-testable**: YES.

---

### T2.4 — Opportunistic Pickup Expansion
**Problem**: Currently only Phase 2 has opportunistic pickup (delivering bot, inv=2, adjacent needed active item). This should be broader.

**Current behavior**: Narrow condition: delivering bot, inventory exactly 2, adjacent item type in remaining_active.

**Proposed solution**:
1. **Any bot moving through aisle**: If bot passes adjacent to a needed item and has inventory space → pick it up regardless of phase.
2. **Preview item opportunistic pickup**: Even if item is for preview order, picking it up "for free" (0 detour rounds) is always worth it.
3. **Full-inventory delivering bot**: If inv=3 and adjacent to a needed item, still can't pick up. But bot with inv=1 or inv=2 delivering should consider detours of ≤2 steps to grab needed items.

**Key metric**: "Free" pickups per game (target: 3–5 from current ~1).

**Files to modify**: `planner.py` (Phase 2, Phase 3, add adjacency check everywhere)

**Sim-testable**: YES.

---

### T2.5 — Smarter Collision Alternative Steps
**Problem**: `_find_alternative_step()` tries all 4 directions when blocked but doesn't know WHY the bot was blocked. It may step sideways into a worse position.

**Current behavior**: Accepts any step with manhattan_delta < 2 (closer, lateral, or 1-step-away). No consideration of where other bots are heading next round.

**Proposed solution**:
1. Pass the full `move_plans` to alternative step finder.
2. Prefer steps that don't conflict with other bots' next-step positions.
3. When in an aisle, prefer stepping in the same direction as the current aisle traffic.
4. Add 1-round lookahead: if stepping sideways this round enables the ideal move next round, prefer it.

**Key metric**: Rounds spent in WAIT after collision (target: –5/game).

**Sim-testable**: YES — track WAIT-after-block events.

---

### T2.6 — Drop-Off Auto-Delivery Chains
**Problem**: When an order completes, the server auto-delivers matching items from ALL bots at drop-off for the NEXT order. Our planner doesn't exploit this.

**Current behavior**: Simulator implements `_auto_deliver_all_bots()` but the planner doesn't plan for it. If Bot A delivers the last item of Order N, and Bot B is at drop-off with Order N+1 items, those items auto-deliver — but this is accidental, not planned.

**Proposed solution**:
1. When active order is near completion (1 item left), check which bots have inventory matching the PREVIEW order.
2. Actively send those bots to drop-off simultaneously — so when Order N completes, Order N+1 items auto-deliver.
3. This can save 10+ rounds by eliminating the "wait for order flip → deliver" gap.

**Key metric**: Auto-delivered items per game (target: 5+ from current ~0–2).

**Sim-testable**: YES — track auto-delivery events in simulator.

---

## Tier 3 — Low Impact / Speculative

### T3.1 — Zone-Based Bot Specialization
Assign bots to geographic zones (left/center/right) to reduce transit overlap. Bot 0–1 handle left aisles, Bot 2–3 center, Bot 4 right + delivery. Risk: rigid zoning may underperform greedy when order items are clustered.

### T3.2 — Path Diversity (Avoid Single-Path Convergence)
When 2+ bots have the same BFS path (e.g., both go along y=12), shift one bot to an alternate equal-length path (e.g., y=11). Reduces same-cell collision. Tried previously with limited effect — worth revisiting with better heuristics.

### T3.3 — Item Type Position Cache
Build a static map of where each item type lives (per shelf). Use this to instantly compute optimal item for each order without scanning all items every round. Minor optimization — reduces constant factor, not algorithmic improvement.

### T3.4 — Predictive Collision Avoidance (2-Round Lookahead)
Simulate move plans 2 rounds ahead. If a collision is predicted for round N+1, adjusted moves in round N to prevent it. High complexity, potentially high payoff for congested scenarios. Risk: compute time may exceed 4ms budget.

### T3.5 — Adaptive Priority Weights
Instead of fixed priority values (Phase 2: 10+, Phase 3: 5, etc.), adjust dynamically based on game state:
- Early game: higher pickup priority (accumulate items fast)
- Mid game: balanced
- Late game: higher delivery priority (clear inventory)
Track score velocity and adjust.

---

## Tier 4 — Infrastructure & Tooling

### T4.1 — Enhanced Simulator Accuracy
**Problem**: Sim avg is 99.5 vs live 130+. The gap makes sim less useful for tuning.

**Root causes**:
1. Sim doesn't model item respawn/removal accurately.
2. Sim collision model is correct but items may differ across games.
3. Live games have non-deterministic element from network timing.

**Actions**:
1. Validate sim item positions match actual server state round-by-round using saved logs.
2. Add "replay mode" — feed exact server states to planner, compare actions.
3. Compute correlation coefficient between sim Δ and live Δ for each change.

---

### T4.2 — Statistical Live Testing Framework
**Problem**: Running 2–3 live games per change isn't statistically significant. Need N≥10 for reasonable confidence.

**Actions**:
1. Create `scripts/_batch_live.py` — runs N games sequentially, reports mean/median/stddev.
2. Target: 10 games per test. Confidence interval: score ± 2σ/√n.
3. Add Welch's t-test: is new score significantly different from baseline (p<0.05)?
4. Store results in `logs/bot/experiments/` with experiment name and parameters.

---

### T4.3 — Per-Round Analytics Dashboard
**Problem**: Hard to identify WHERE in the game rounds are wasted.

**Actions**:
1. Create `scripts/_round_analytics.py` — reads game log, computes:
   - Rounds per order completion
   - WAIT count per bot per phase
   - Collision count per location
   - Score velocity (points/round) over time
   - Idle bot count per round
2. Output: per-game CSV + summary chart.
3. Goal: identify which rounds/phases waste the most time.

---

### T4.4 — A/B Configuration Testing
**Problem**: Tuning `PlannerConfig` parameters manually is slow.

**Actions**:
1. Create `scripts/_ab_test.py` — runs sim with Config A and Config B across all logs.
2. Reports per-game comparison, avg difference, and paired t-test.
3. Extend `autotune.py` — grid search over key parameters:
   - `return_cost_factor` (currently 0.9)
   - aisle congestion multiplier (currently 3)
   - delivery detour threshold (new)
   - endgame time-pressure thresholds (new)

---

### T4.5 — Regression Test Suite
**Problem**: No automated regression detection. Manual bench comparison is error-prone.

**Actions**:
1. Store baseline sim scores in `logs/bot/baseline_scores.json`.
2. `scripts/_bench.py` auto-compares against baseline, flags regressions >2 points.
3. Add `scripts/_regression_check.py` — pass/fail based on avg delta.
4. Integrate into pre-commit hook or CI.

---

## Testing Strategy

### Pyramid of Confidence

```
                    ┌─────────┐
                    │  LIVE   │   N≥10 games
                    │ (final) │   mean ± 95% CI
                    ├─────────┤
                    │  SIM    │   28+ game logs
                    │ (bench) │   Δ avg from baseline
                ┌───┤─────────├───┐
                │   │ UNIT    │   │
                │   │ (logic) │   │   Module-level checks
                └───┴─────────┴───┘
```

### Step-by-Step Test Protocol

#### 1. Pre-Change Baseline
```powershell
# Record baseline sim score
python scripts/_bench.py > logs/bot/baseline_YYYYMMDD.txt
```
Note the avg score. This is your control.

#### 2. Make Change (ONE change at a time)
- Edit `planner.py` (or relevant file).
- Ensure `decide()` still runs <10ms.
- Visually review change for correctness.

#### 3. Quick Sim Sanity Check
```powershell
# Single game sim — verify no crash
python scripts/_simulator_hard.py
```
Expected: completes without error, score in ballpark.

#### 4. Full Sim Bench
```powershell
python scripts/_bench.py
```
**Pass criteria**:
- Avg score ≥ baseline − 1.0 (no regression)
- No individual game drops >10 points from baseline
- Overall Δ is positive

#### 5. Short Live Test (3 games)
```powershell
python scripts/_live_hard.py  # Run 3 times
```
**Pass criteria**:
- All 3 games ≥ 125
- No game < 100 (indicates regression)
- Mean ≥ 128

#### 6. Full Live Test (10 games)
Only if Step 5 passes:
```powershell
# Use batch live script (T4.2)
python scripts/_batch_live.py --count 10
```
**Pass criteria**:
- Mean ≥ 130
- Std dev < 15
- Min game ≥ 110
- Statistical test vs baseline: p < 0.10 or non-inferior

#### 7. Ship or Revert
- If passes: update baseline, commit, document in experiment log.
- If fails: revert, analyze why, document in experiment log.

### Sim vs Live Correlation Guide

| Sim change | Expected live change | Notes |
|---|---|---|
| Avg +3 | ~+2 to +5 live | Good correlation for structural changes |
| Avg +1 | May not be visible live | Within noise — need 10+ games |
| Avg −2 | Likely −5 to −10 live | Sim underestimates regressions |
| Avg 0, but max game +10 | Possible +2 live | Sim misses some live dynamics |

### Key Instruments for Diagnosis

| Script | When to use |
|---|---|
| `_bench.py` | Every change — primary regression detector |
| `_live_hard.py` | After sim passes — live validation |
| `_block_analysis.py <log>` | When live score drops — find collision hotspots |
| `_game_summary.py <log>` | After any game — WAIT/action distribution |
| `_wrong_dir.py <log>` | If score suddenly drops 50+ — check for desync return |
| `_trace_hard.py <log>` | Deep debugging — round-by-round bot decisions |
| `_grid_vis.py <log> [round]` | Visualize what happened at specific round |
| `_delay_theory.py <log>` | If desync suspected — verify timing |

---

## Experiment Log Template

Copy and fill for each experiment:

```markdown
## Experiment: [NAME]
**Date**: YYYY-MM-DD
**Branch/Commit**: [hash]
**Task**: T[X.Y]
**Hypothesis**: [what you expect to improve and why]

### Change Summary
- File(s) modified: [list]
- Description: [1–3 sentences]

### Sim Results
- Baseline avg: [X.X]
- New avg: [X.X] (Δ [+/-X.X])
- Worst regression: [game] −[X] points
- Best improvement: [game] +[X] points

### Live Results
- Games played: [N]
- Scores: [list]
- Mean: [X.X] (baseline: [X.X])
- Min/Max: [X]/[X]

### Decision
- [ ] KEEP — improves score significantly
- [ ] KEEP — neutral but cleaner code
- [ ] REVERT — regression detected
- [ ] NEEDS MORE DATA — inconclusive

### Notes
[observations, follow-up ideas]
```

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Change regresses live but not sim | Medium | High | Always run 10+ live games before ship |
| Multi-change interaction breaks | Medium | High | Never combine 2+ untested changes |
| Compute time exceeds 10ms | Low | Critical | Profile `decide()` after each change |
| Corridor fix causes different deadlock | Medium | Medium | Visualize with `_grid_vis.py` |
| Over-fitting to sim collision model | Medium | Medium | Sim is less accurate than live — always live-validate |
| Desync returns (client.py regression) | Low | Critical | Never modify client.py without checking `_wrong_dir.py` |
| Server-side change (map/rules) | Low | High | Compare first-round game state vs known map |

---

## Recommended Execution Order

```
Week 1:  T4.1 (sim accuracy) → T4.2 (batch live) → T4.5 (regression suite)
         ↳ Foundation: better testing before making changes

Week 2:  T1.2 (multi-item trips) → T2.2 (endgame mode)
         ↳ Biggest ROI: fill inventory, optimize late game

Week 3:  T1.5 (order pipeline) → T2.6 (auto-delivery chains)
         ↳ Reduce inter-order gaps

Week 4:  T1.1 (drop-off queuing) → T1.6 (corridor reservation)
         ↳ Reduce wasted rounds near drop-off

Week 5:  T1.3 (traffic flow) → T2.5 (smarter alt steps)
         ↳ Tackle corridor gridlock (the 71-score games)

Week 6:  T1.4 (dynamic re-assign) → T2.4 (opportunistic pickup)
         ↳ Fine-tuning: extract remaining efficiency

Ongoing: T4.3 (analytics), T4.4 (A/B testing), T3.* (speculative)
```

---

## Quick Command Reference

```powershell
# Sim baseline
python scripts/_bench.py

# Single live game
python scripts/_live_hard.py

# Debug specific game
python scripts/_game_summary.py logs/bot/game_XXXXX_hard.jsonl
python scripts/_block_analysis.py logs/bot/game_XXXXX_hard.jsonl
python scripts/_trace_hard.py logs/bot/game_XXXXX_hard.jsonl

# Grid visualization at round N
python scripts/_grid_vis.py logs/bot/game_XXXXX_hard.jsonl 50

# Check for desync
python scripts/_wrong_dir.py logs/bot/game_XXXXX_hard.jsonl
```
