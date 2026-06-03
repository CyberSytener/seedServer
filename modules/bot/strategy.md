# Grocery Bot Strategy Research Plan

> Generated: 2026-03-04
> Baseline: ~140 (0-desync live), ~134.6 (10-log sim avg)
> Target: 180+

---

## 1. Executive Summary

### Current State

The bot runs a **sequential phase pipeline** (Phase 1 → 1b → 2 → 3 → 2b → 3b → 4 → collision resolution) that assigns one task per bot per round in a greedy, myopic fashion. It is implemented in [`planner.py`](planner.py) as the `OptimizedEngine._decide_multi()` method (~400 lines of the ~980 total).

**What is already strong:**
- WebSocket layer is latency-optimized (sync decide, buffer drain, 1–4ms compute, ~100ms round-trip). No desyncs on clean networks. Evidence: [`client.py`](client.py) L46–68 drain loop; `decide()` call is synchronous, no executor overhead.
- Collision resolution is server-accurate (sequential bot-ID ascending, both-yield swap detection). Evidence: [`collision.py`](collision.py) `resolve_collisions()` matches protocol spec §8.
- Phase pipeline is clean and debuggable. All experimental code has been reverted.
- Greedy assignment + proximity defer + congestion penalty is locally optimal for single-step decisions.
- Extensive tooling exists: offline simulator ([`scripts/_simulator_hard.py`](../../scripts/_simulator_hard.py)), batch benchmarking ([`scripts/_bench.py`](../../scripts/_bench.py)), per-round analytics, block analysis, phase tracing, grid visualization.

**What is likely causing the plateau:**
1. **Single-item delivery trips.** Bots pick up 1 item, return to drop-off, repeat. With 5 bots and 3–5 item orders, this means 1–2 bots are always idle or parking. Evidence: BOT_TASKS.md §T1.2 estimates ~1.9 items/trip average; filling to 2.5+ would save ~22 points.
2. **No multi-step lookahead.** Each round's decision is greedy — it minimizes immediate cost without considering future consequences (e.g., "this pickup position blocks an aisle needed in 3 rounds"). Evidence: `_decide_multi()` in [`planner.py`](planner.py) L194–540 — zero lookahead, pure greedy cost function.
3. **No cooperative pathfinding.** Bots plan paths independently. Collisions are resolved post-hoc by the resolver, which can only stall or laterally displace bots — it cannot route them cooperatively. Evidence: `_move_toward_multi()` at L565–592 blocks on other bots' current positions, not on planned future positions.
4. **Order transition gaps.** When an active order completes, bots with preview items are not pre-positioned at drop-off to exploit auto-delivery. Evidence: Phase 3b at L440–485 assigns preview items with priority 2 (lowest) and sends bots toward items, not toward drop-off.
5. **No exploitation of auto-delivery mechanic.** Protocol §7.3 & §11.3 confirm: when order N completes, ALL bots at drop-off auto-deliver matching items for order N+1. The planner treats this as accidental, not engineered. Evidence: simulator `_auto_deliver_all_bots()` at [`scripts/_simulator_hard.py`](../../scripts/_simulator_hard.py) L296–320 implements it, but planner has no corresponding planning logic.

### Research Goal

Identify 3–5 strategy families that are **fundamentally different** from the already-tested greedy variants, evaluate their potential to break the 140 ceiling, and design bounded experiments to test them without falling into infinite tuning loops.

---

## 2. Verified Baseline

### Current Architecture

```
                    ┌─────────────────────────────────┐
                    │   OptimizedEngine.decide(state)  │
                    │   planner.py L152–192            │
                    └───────────────┬─────────────────┘
                                    │
              ┌─────────────────────▼─────────────────────┐
              │         _decide_multi(state)               │
              │         planner.py L194–540                 │
              │                                            │
              │  1. Parse state, build indices              │
              │  2. Phase 1:  DROP_OFF (matching items)    │
              │  3. Phase 1b: EVICT (non-matching at D/O)  │
              │  4. Phase 2:  DELIVER (move to drop-off)   │
              │     - Opportunistic PICK_UP if adjacent     │
              │     - Proximity defer (manhattan ≤ 6)       │
              │  5. Phase 3:  ASSIGN (greedy cheapest)     │
              │     - BFS dist + return×0.9 + congestion×3 │
              │     - Defer bonus: -5 for deferred bots    │
              │  6. Phase 2b: DELIVER deferred bots        │
              │  7. Phase 3b: PREFETCH preview/future      │
              │  8. Phase 4:  PARK idle bots               │
              │  9. Collision resolution + alt steps        │
              └────────────────────────────────────────────┘
```

### Per-Round Computation Budget

| Operation | Cost | Evidence |
|---|---|---|
| Parse state (`GameState.model_validate`) | ~0.5ms | client.py L91 |
| Build Grid, item_blocked, items_by_type | ~0.1ms | planner.py L197–211 |
| BFS distance maps (drop-off + each bot) | ~0.5–2ms | planner.py L260, L340–343 |
| Greedy assignment sort | <0.1ms | planner.py L393 |
| Collision resolution | <0.1ms | collision.py L42–68 |
| **Total decide()** | **1–4ms** | Ample headroom under 2s timeout |

### Map Structure (Hard: 22×14)

- **64 items** across 12 types, placed on 8 shelf columns (x=3,5,7,9,11,13,15,17)
- **4 narrow aisles** (x=4,8,12,16): 1-cell wide, vertical, collision-prone
- **3 horizontal corridors** (y=1, y=7, y=11) + delivery row (y=12)
- **Drop-off** at (1,12) — far left. **Bot start** at (20,12) — far right.
- Average BFS distance from rightmost aisle to drop-off: ~25–30 steps
- Average BFS distance from leftmost aisle to drop-off: ~8–12 steps
- Each aisle has ~ALL 12 item types (verified: conversation summary notes 16 items per aisle, ~12 types each)

### Score Formula & Throughput Analysis

Score = items_delivered × 1 + orders_completed × 5.

Current typical game (sim avg 134.6):
- ~60 items delivered, ~16 orders completed → 60 + 80 = 140 (0-desync)
- Orders average ~3.7 items required (Hard orders: mix of 3, 4, and 5)
- Typical: ~16 orders × 3.7 items = ~59 items, each delivered individually

For 180: need ~80 items + ~20 orders (80 + 100 = 180), OR ~70 items + ~22 orders (70 + 110 = 180).
This means either: (a) deliver 20 more items + 4 more orders, or (b) complete orders faster with multi-item trips.

### Strengths

1. **Zero-desync potential**: When network is clean, consistently hits 139–140.
2. **Reliable delivery**: Phase 1/2 never fails to initiate drop-off when correct.
3. **Congestion awareness**: Aisle congestion penalty reduces but doesn't eliminate aisle gridlock.
4. **Preview prefetching**: Phase 3b intelligently pre-fetches items for future orders.
5. **Good parking**: Bots park out of the delivery corridor (rows 1/7, right half).

### Limitations

1. **Greedy myopia**: No consideration of how current actions affect future rounds.
2. **Single-item trips**: No mechanism to batch multiple items before delivering.
3. **Independent pathing**: Bots plan paths in isolation, resolve collisions reactively.
4. **No auto-delivery exploitation**: Doesn't engineer simultaneous drop-offs for order transitions.
5. **Static priorities**: Fixed priority values regardless of game phase or score velocity.
6. **No corridor reservation**: Delivery row y=12 can be blocked by parking/transitioning bots.
7. **No drop-off queuing**: Multiple bots converge on (1,12) simultaneously, wasting ~3 rounds per collision.

---

## 3. Already Tested Approaches

### Verified Table (from conversation history + code review)

| # | Name | What Actually Changed | Sim Result | Live Result | Failure Mode | Verdict | Deep Enough? |
|---|---|---|---|---|---|---|---|
| 1 | **Defer bonus -15** | `defer_bonus` from -5 to -15 in Phase 3 cost function (planner.py L380) | 140 (5/5 games) | **19** — catastrophic | Cascading assignment distortion → oscillating deadlock, score stuck R32–R299 | KILLED | Yes — live failure is definitive. The mechanism is understood: too-strong bonus makes deferred bots always win assignments, starving other bots and creating circular dependencies. |
| 2 | **Proximity threshold 4** | Phase 2 defer threshold from `best_extra <= 6` to `<= 4` (planner.py L316) | 134 | Not tested | Fewer deferrals → more single-item trips | KILLED | Shallow — only one sim run. BUT: the mechanism is obvious (fewer deferrals = less batching), so not worth deep exploration. |
| 3 | **Proximity threshold 8** | Same line, from 6 to 8 | 134 | Not tested | Same as baseline — diminishing returns on wider threshold | KILLED | Shallow — same reasoning. 6 is already wide enough to capture nearby items. |
| 4 | **Aisle concentration (-6)** | Added `aisle_bonus = -6` to Phase 3 cost for items in "best aisle" (most coverage + closest to drop-off) | 125 | Not tested | Forced bots to travel far for aisle-matching items, ignoring closer items in other aisles | KILLED | Yes — the concept is sound but the implementation penalized distance too much. Could be revisited with milder bonus AND only when bot is already in/near the target aisle. |
| 5 | **Item reservation (chain)** | Persistent `_chain_reserved` dict: after Phase 3 assigns a bot, reserve same-aisle items (y-dist ≤ 6) for that bot | 125 | Not tested | Reserving items delays other bots from picking them up → throughput reduction | KILLED | Moderate — one variant tested. The core problem is reservation duration: reserving "forever" is too aggressive. A bounded 2–3 round reservation might work differently but was not tried. |
| 6 | **En-route opportunistic pickup** | Phase 3 bot heading to assigned item, if adjacent to DIFFERENT needed active item, grab it | 134 (no change) | Not tested | Phase 3 already assigns closest items, so adjacency events are rare | NEUTRAL | Yes — the rare activation is inherent to the greedy assignment model. Not worth more effort. |
| 7 | **Return cost factor sweep** | `return_cost_factor` tested at 0.5, 0.7, 0.8, 0.85, 0.9, 1.0 across 5 logs | 0.8→134, 0.9→134, others worse | Not tested | 0.5 too aggressive (ignores return distance), 1.0 too conservative (over-penalizes far items) | 0.9 KEPT (was already baseline) | Yes — thorough sweep. |
| 8 | **Preview opportunistic pickup (unrestricted)** | Delivering bot picks up adjacent preview items en-route to drop-off | 126.5 avg (10-log, range 90–149) | 132.4 | Eviction waste: delivering bot grabs preview item → delays active delivery → cascading order delays | KILLED | Moderate — multiple variants tested (see below), but the core issue (delayed active delivery) wasn't addressed by gating. |
| 9 | **Preview pickup (active-matching only)** | Only pick up preview items that match active order too | 140 single-log | Inconsistent | Narrow activation window, inconsistent across logs | KILLED | Shallow — only one sim log. |
| 10 | **Preview pickup (distance-gated >5)** | Only pick up preview items when >5 BFS from drop-off | 123 | Not tested | Still delays delivery on most logs | KILLED | Shallow — one variant of many possible gates. |
| 11 | **Preview pickup (order-complete only)** | Only grab preview when remaining_active is empty | 104.7 avg (10-log, min=38) | Not tested | Catastrophic on some order sequences | KILLED | Yes — the 38-score floor proves this is fundamentally flawed. |
| 12 | **Phase 3b return distance** | Added `return_dist * 0.5` to Phase 3b preview assignment cost | 134.5 | Not tested | Negligible effect — Phase 3b is low priority and rarely bottleneck | NEUTRAL | Shallow — one coefficient tried. Not worth more. |
| 13 | **Multi-route delivery** | Changed Phase 2 delivery from `_move_toward_direct` to `_move_toward_multi` | 48.5 avg (10-log, min=19, max=99) | Not tested | `_move_toward_multi` blocks on other bots → delivery corridor deadlocks | KILLED | Yes — definitive failure. Delivery MUST ignore other bots and rely on collision resolver. |
| 14 | **Min-max Phase 3 assignment** | Replace greedy cheapest-first with minimize-bottleneck (longest trip) using permutations | 124.6 avg (10-log, range 43–151) | Not tested | High variance; didn't handle duplicate need types; optimizer chose worse average paths to reduce worst-case | KILLED | Moderate — had a bug (duplicate types). The concept of bottleneck-minimizing assignment deserves a clean reimplementation, but brute-force permutations are too expensive for >5 needs. |
| 15 | **Cluster bonus (-2 per co-type)** | Reward items in aisles with more needed types | 125 | Not tested | Same problem as aisle concentration — forces bots to travel far | KILLED | Shallow — one coefficient. Same structural issue as #4. |
| 16 | **Caching (Grid, dist maps, items)** | Cached Grid, drop_off, item_blocked, dropoff_dist_map, items_by_type across rounds | 140 (sim correct) | 130, 130, 69, 124 — regression | Stale state: likely ItemInfo references or item_blocked set becoming stale between rounds | KILLED | Moderate — one implementation. Caching is implementable correctly but requires careful invalidation. Not retried. |
| 17 | **Drain timeout 0.2ms** | client.py drain timeout from 1ms to 0.2ms | N/A | Part of caching test (regressed) | Tested jointly with caching, confounded | INCONCLUSIVE | Not isolated — must be retested independently. |

### Critical Pattern from Tested Approaches

**Every approach that modified the assignment cost function by more than ±5 caused regressions.** The greedy cost function (`BFS_dist + return_dist × 0.9 + congestion × 3 + defer_bonus`) is locally stable — small perturbations don't improve it, and large perturbations destabilize it. This strongly suggests the plateau is architectural, not parametric.

**Every approach that delayed active delivery (preview pickup, reservation, batching) regressed.** This is the key tension: multi-item trips would improve throughput, but the current pipeline has no safe mechanism to delay delivery without cascading order completion delays.

---

## 4. Strategic Hypotheses Worth Testing

### Hypothesis A: Deliberate Multi-Item Trip Planning

**Core Idea:** Instead of the current flow (pick 1 item → deliver → repeat), explicitly plan 2–3 item pickup routes before delivering. This is the single highest-leverage change because it directly addresses the throughput ceiling.

**Why Fundamentally Different from Tested Variants:**
Previously tested approaches (item reservation, en-route pickup, preview pickup) all tried to bolt multi-item behavior *onto* the existing single-item delivery pipeline. They failed because the pipeline's Phase 2 trigger (`bot has matching items → deliver immediately`) fights against batching. The correct approach requires **restructuring the delivery trigger** itself:

- A bot should NOT deliver just because it has 1 matching item.
- A bot should deliver when: (a) inventory full (3 items), OR (b) carrying all remaining needs for the active order, OR (c) no more needed items are reachable within a detour budget, OR (d) endgame time pressure.

This was proposed in BOT_TASKS.md §T1.2 but never properly implemented. The prior "item reservation" attempt (#5 above) added reservation on top of the existing Phase 2 trigger without changing it. The prior "preview pickup" attempts (#8–11) tried to add items during delivery without suppressing the delivery trigger.

**Why It Could Beat the Plateau:**
- Current: ~60 items in ~16 orders. If items/trip goes from ~1.9 to ~2.5, the same 300 rounds could yield ~80 items in ~20 orders → score ~180.
- The math: 5 bots × 300 rounds / (avg_trip_length_in_rounds) × items_per_trip. Currently avg_trip ~18 rounds, 1.9 items/trip. At 2.5 items/trip and same trip length: 5×300/18×2.5 = 208 items — but orders gate delivery, so the real gain is ~20 more items + ~4 more orders = +40 points.

**Risks:**
- Batching delays delivery of the first item → order completion is pushed later → fewer orders total
- Need careful "detour budget" tuning: too generous = bot wanders forever; too tight = collapses to current behavior
- Requires modifying Phase 2 trigger logic, which is the most tested/stable part of the planner

**Implementation Complexity:** Medium. Modifying Phase 2 delivery trigger + adding a "go pick up a second item" sub-phase between Phase 2 and Phase 3. ~50–100 lines of new logic.

**Runtime Cost:** Negligible — same BFS computations, just different decision logic.

**Suitable for:** Hard, Expert (any multi-bot difficulty where throughput matters).

---

### Hypothesis B: Cooperative Time-Space Pathfinding (Reservation Table)

**Core Idea:** Replace independent per-bot pathfinding with a reservation table that tracks (cell, time) pairs. Bots reserve their planned paths for the next K rounds, and subsequent bots route around existing reservations. This eliminates corridor deadlocks at the source rather than resolving them post-hoc.

**Why Fundamentally Different from Tested Variants:**
The current system plans paths for each bot independently (BFS ignoring or blocking on other bots' current positions) and then resolves collisions reactively:
- [`_move_toward_multi()`](planner.py#L565): Blocks on other bots' **current** positions.
- [`resolve_collisions()`](collision.py#L9): Handles conflicts for **this round only**.
- [`_find_alternative_step()`](planner.py#L649): Brute-force alt direction when blocked.

None of these consider where bots will be in future rounds. A reservation table (also called Cooperative A* or WHCA*) would:
1. Plan bot paths in priority order.
2. Each bot's path is committed for K rounds into a time-space reservation table.
3. Later bots route around all reservations.
4. Result: zero collisions within the planning horizon.

No tested variant attempted time-space coordination. The "multi-route delivery" test (#13) used the existing `_move_toward_multi()` (bot-aware BFS) for delivery instead of `_move_toward_direct` — a fundamentally different change that simply blocked on current positions. Reservation tables are categorically different.

**Why It Could Beat the Plateau:**
- BOT_TASKS.md estimates ~20–30 aisle collisions per game, each wasting 2–6 rounds per bot pair. That's 40–180 bot-rounds wasted, or 8–36 effective rounds lost. Eliminating even half could yield +5–15 score.
- More importantly: cooperative paths enable bots to "weave" through narrow aisles in coordinated sequences, which is currently impossible because independent planning + reactive resolution causes both bots to wait.

**Risks:**
- Computational cost: WHCA* with K=5 horizon, 5 bots, on a 200-cell grid may exceed the 4ms budget. Must benchmark.
- Re-planning every round may waste the reservation table (plans change as items are picked up). Could use a 2–3 round horizon instead of full path reservation.
- Server collision model is sequential by bot-ID, not simultaneous. Cooperative paths must model this correctly to avoid planning invalid paths.

**Implementation Complexity:** High. Requires new data structure (time-space reservation table), modified pathfinding, and integration into the phase pipeline. ~150–250 lines.

**Runtime Cost:** Potentially 2–10ms per round depending on horizon and grid size. Must profile.

**Suitable for:** Hard, Expert (most benefit on maps with narrow corridors and many bots).

---

### Hypothesis C: Order-Transition Auto-Delivery Engineering

**Core Idea:** Deliberately synchronize bot arrivals at drop-off so that when order N completes, bots carrying order N+1 items are already at drop-off and auto-deliver instantly.

**Why Fundamentally Different from Tested Variants:**
No tested variant targeted auto-delivery. The simulator implements it ([`_simulator_hard.py`](../../scripts/_simulator_hard.py) L296–320 `_auto_deliver_all_bots()`), and the protocol spec confirms it (§7.3, §11.3), but the planner completely ignores this mechanic.

Currently:
- Bot A delivers last item of order N → order N completes → order N+1 activates
- Bot B, carrying an N+1 item and at drop-off, gets auto-delivery (free +1 point, possibly free order completion)
- But this is accidental. The planner never thinks about it.

The strategy is:
1. When active order has ≤2 items remaining and a bot is within 3 rounds of delivering the last one:
   - Identify bots carrying items matching the preview order.
   - Route those bots to drop-off in parallel, timed to arrive when/just after the last active item is delivered.
2. This converts "accidental" auto-deliveries into "engineered" ones.
3. In the best case, an entire 3-item order can auto-complete in 0 extra rounds.

**Why It Could Beat the Plateau:**
- Each auto-delivered order saves ~15 rounds (full trip for that order).
- If we engineer 3–4 auto-deliveries per game: +3–4 extra orders × 5 points + ~12 extra items = +27–32 points.
- Even engineering 1–2 auto-deliveries per game: +10–15 points.

**Risks:**
- Timing is critical. If the preview bot arrives 1 round too late, it misses auto-delivery.
- If the preview bot arrives but the active order doesn't complete (e.g., another bot's delivery is blocked), the preview bot wastes rounds at drop-off holding non-active items.
- Requires accurate prediction of "when will the active order complete?" which depends on delivery bot's path + collision outcomes.

**Implementation Complexity:** Medium. Add an "order transition detector" that identifies when the active order is about to complete, and a "parallel delivery router" that redirects preview-item-carrying bots to drop-off. ~80–120 lines.

**Runtime Cost:** Negligible — just additional conditional logic on existing data structures.

**Suitable for:** All difficulties (any difficulty where orders are sequential).

---

### Hypothesis D: Drop-Off Queuing & Pipelining

**Core Idea:** Instead of sending all delivery bots to drop-off simultaneously (causing them to queue and collide near (1,12)), stagger arrivals so exactly one bot delivers per round, creating a smooth pipeline.

**Why Fundamentally Different from Tested Variants:**
- "Staggered delivery (limit 2 bots)" was tried in the prior session and regressed by -19 in sim. BUT: that test limited total delivery bots to 2, which is too conservative — it prevented 3rd/4th/5th bots from delivering at all.
- The correct approach is not to limit how many bots can deliver, but to **sequence their arrival**. Bot closest to drop-off delivers first; bots 2nd/3rd in queue slow down or divert until the first bot clears.

Implementation:
1. Classify delivery-phase bots by distance to drop-off.
2. Only the closest bot gets `_move_toward_direct` to drop-off.
3. 2nd closest gets `_move_toward_direct` but caps approach at distance 3 from drop-off (wait or divert if closer).
4. 3rd+ bots continue picking up items if possible, or slow-approach.

**Why It Could Beat the Plateau:**
- BOT_TASKS.md §T1.1 estimates 15–20 WAIT rounds at/near drop-off per game. Pipelining could reduce to <5, recovering 10–15 rounds → +3–5 score.
- Smaller impact than multi-item trips or auto-delivery, but low risk and composable with other improvements.

**Risks:**
- Over-constraining delivery can delay order completion if the queuing logic is too conservative.
- The drop-off cell (1,12) has limited adjacent cells for staging, making physical pipelining tricky.

**Implementation Complexity:** Low-Medium. Add distance-based gating to Phase 2. ~30–60 lines.

**Runtime Cost:** Negligible.

**Suitable for:** Hard, Expert (minimal benefit on Easy/Medium with fewer bots).

---

### Hypothesis E: Rolling-Horizon Multi-Step Lookahead

**Core Idea:** Instead of greedy single-step decisions, simulate 3–5 possible future assignments and pick the one with the best projected score at the end of the horizon. Not full MCTS — a bounded, deterministic lookahead.

**Why Fundamentally Different from Tested Variants:**
The "min-max Phase 3 assignment" test (#14) used `itertools.permutations` to minimize the longest trip, but: (a) only looked at immediate assignment cost, not projected future rounds, (b) had a bug with duplicate need types, (c) used brute-force on all permutations. A rolling-horizon planner is different because it:
1. Simulates actual game mechanics (movement, pickup, delivery) for K rounds.
2. Evaluates based on projected score at round N+K, not just assignment cost.
3. Can evaluate order transitions, auto-delivery, and multi-item trips in composition.

Implementation: use the existing `MultiBotGame` simulator (with simplified collision) as a forward model. At each round, generate 3–5 candidate assignment strategies, simulate each for K=5–10 rounds, and pick the best.

**Why It Could Beat the Plateau:**
- The greedy planner makes locally optimal decisions that are globally suboptimal. Even 5-round lookahead can prevent: (a) assigning a bot to a far item when it would be better to wait 2 rounds for a closer bot, (b) delivering immediately when batching 1 more item would save 10 rounds overall.
- If lookahead captures 3–5 opportunities per game that the greedy misses: +10–20 score.

**Risks:**
- Computational cost: simulating 5 candidate strategies × 10 rounds × 5 bots = significant. Must stay under ~10ms.
- Branching factor is enormous if enumerating all possible assignments. Must limit to 3–5 heuristically-chosen candidate strategies (e.g., "current greedy", "batch one more item", "deliver immediately", "redirect to closer item").
- Forward model accuracy: sim collision model may diverge from server behavior, causing lookahead to pick plans that fail live.

**Implementation Complexity:** High. Requires lightweight sim integration into decide(), candidate strategy generation, and evaluation function. ~200–300 lines.

**Runtime Cost:** 5–15ms per round (depends on horizon and branching factor). May need to reduce to critical rounds only (e.g., only when a decision point is detected).

**Suitable for:** Hard, Expert. Overkill for Easy/Medium.

---

### Evaluated but NOT Recommended

The following strategy families were requested for evaluation but are judged to be **not worth pursuing** at this time:

| Strategy | Verdict | Reasoning |
|---|---|---|
| **Monte Carlo Tree Search** | Not recommended | MCTS requires thousands of random rollouts per decision. With 5 bots × 7 actions each, the branching factor per round is 7^5 = 16,807. Even 100 rollouts at 10-round depth = 100 × 10 × simstep = ~1000 simulation steps per round. This is likely 20–100ms, exceeding the compute budget. MCTS excels in games with compact state spaces and moderate branching; this game has neither. A bounded lookahead (Hypothesis E) captures most of the benefit at 1/10th the cost. |
| **Reinforcement Learning** | Not recommended now | RL requires: (1) a training loop with thousands of episodes, (2) a reward signal that distinguishes 140 from 145, (3) a policy network that runs in <4ms. Training infrastructure doesn't exist. The action space (7^5 per round) is too large for tabular RL, and neural RL introduces latency and debugging opacity. RL is a last resort after all planning-based approaches are exhausted. |
| **Learned Heuristics** | Not recommended now | Requires training data (thousands of games with ground-truth optimal decisions). No such dataset exists. Could be valuable later if the lookahead planner generates labeled data. |
| **Offline Policy Search** | Partially covered | Hypothesis E (rolling-horizon) subsumes this. A separate "offline policy optimizer" that tunes parameters against sim logs is essentially the `autotune.py` tooling that already exists. |
| **Meta-Controller (strategy switching)** | Premature | Switching between strategies requires having multiple good strategies. Currently we have 1 strategy. Build 2–3 first, then evaluate switching. |
| **Zone-Based Coordination** | High risk, low reward | Each aisle has ~ALL 12 item types. Zone assignment would restrict bots to subsets of identical item pools. The benefit of zone separation (less congestion) is already largely achieved by the congestion penalty. Hard-assignment zones are rigid and cannot adapt to random order sequences. Evidence: bot_context.md §4 map analysis shows uniform item distribution across aisles. |
| **Beam Search** | Already exists, single-bot only | [`scripts/_beam_search.py`](../../scripts/_beam_search.py) implements beam search for 1-bot games. Extending to 5 bots is impractical due to the joint action space (16,807 per round). Not recommended for multi-bot. |
| **Traffic-Aware Congestion Pricing** | Already tested (subset) | Congestion penalty `others × 3` is already in Phase 3 (planner.py L385–390). The tested "aisle concentration" and "cluster bonus" are variations. More sophisticated pricing (per-round dynamic, directional) could be explored as part of cooperative pathfinding (Hypothesis B), not independently. |
| **Dynamic Role Assignment** | Subset of Multi-Item Trips | "Dedicated delivery bots" vs "dedicated pickup bots" is a special case of trip planning. Not worth separating. |
| **Intent Locking / Commitment Windows** | Subset of Reservation Table | Reserving bot intentions for N rounds is exactly what the reservation table (Hypothesis B) does. |

---

## 5. Prioritized Experiment Roadmap

### Priority 1: Hypothesis A — Multi-Item Trip Planning

**Why now:** Highest theoretical payoff (+20–40 points). Addresses the #1 bottleneck (single-item trips). Does not require complex infrastructure.

**Success metric:** 10-log sim avg ≥ 142 (8+ point improvement would be meaningful, but even 145 is not guaranteed on first variant).

**Failure metric:** 10-log sim avg < 130 after 3 variants. OR: simulated items-per-trip does not increase above 2.0.

**Required telemetry:**
- Items per delivery trip (items dropped off per DROP_OFF action per bot)
- Order completion latency (rounds between order activation and completion)
- Bot idle time (rounds spent in Phase 4 PARK)
- Delivery delay: rounds between "bot has matching items" and "bot drops off"

**Replay scenarios:** Use the 10-log benchmark suite established in prior session (evenly sampled from 114 log files). Also use the single log that produced the worst score (123) as a stress test.

**Iteration budget:** 4 variants before kill decision.
- Variant A1: Simple hold — don't deliver if inv=1 and a needed item is ≤ 8 BFS away. Timer: if held for >10 rounds, force deliver.
- Variant A2: Budget-gated — compute "detour cost" (extra rounds to pick up 2nd item vs deliver now). If cost < 6, detour.
- Variant A3: Order-completion-aware — only hold if completing the order requires ≥2 more items after this bot's. If this bot carries the last item, deliver immediately.
- Variant A4: Combined best elements of A1–A3.

---

### Priority 2: Hypothesis C — Auto-Delivery Engineering

**Why now:** Completely untapped mechanic. Low implementation risk. Composable with all other changes.

**Success metric:** 10-log sim avg ≥ 137 (even +3 points is significant given low risk). Track: number of auto-delivered items per game (target: 3+).

**Failure metric:** 10-log sim avg < 133 (regression). OR: auto-delivery events < 1 per game average.

**Required telemetry:**
- Auto-delivery event count per game (add logging to simulator's `_auto_deliver_all_bots()`)
- "Near-miss" events: bot arrived at drop-off 1–2 rounds after order completion (missed auto-delivery)
- Order transition timing: round of order N completion vs round of first order N+1 delivery

**Replay scenarios:** Same 10-log suite. Also specifically replay logs where orders with overlapping item types are sequential (highest auto-delivery potential).

**Iteration budget:** 3 variants before kill decision.
- Variant C1: When active order has ≤1 remaining item and a bot within ≤5 BFS of delivery: redirect any bot carrying preview-matching items to drop-off (if distance ≤ 10).
- Variant C2: More aggressive — redirect when ≤2 remaining items.
- Variant C3: Time-phased — only redirect in early/mid game (R < 200), pure greedy in endgame.

---

### Priority 3: Hypothesis D — Drop-Off Pipelining

**Why now:** Low complexity, low risk. Can be implemented in ~1 hour. Even small gains compound with other improvements.

**Success metric:** 10-log sim avg ≥ 136 AND reduction in WAIT count near drop-off by ≥30%.

**Failure metric:** 10-log sim avg < 133. OR: order completion latency increases (pipelining delays delivery too much).

**Required telemetry:**
- Per-bot WAIT count within manhattan distance ≤ 3 of drop-off
- Drop-off cell utilization: fraction of rounds where at least one bot is at (1,12) dropping off
- Drop-off queue length: number of bots with matching items within 5 BFS of drop-off per round

**Replay scenarios:** 10-log suite. Focus on logs with high bot convergence near drop-off.

**Iteration budget:** 2 variants before kill decision.
- Variant D1: Only closest delivery bot proceeds; 2nd+ bots divert to pick up another item if available, else slow-approach.
- Variant D2: First bot proceeds at full speed; second bot proceeds but caps approach at dist=2; third+ bots divert.

---

### Priority 4: Hypothesis B — Reservation Table (Cooperative Pathfinding)

**Why now:** Addresses a real problem (corridor deadlocks) but high implementation cost. Attempt after A, C, D are resolved.

**Success metric:** 10-log sim avg ≥ 140 AND collision count per game reduced by ≥50%.

**Failure metric:** Compute time per round > 10ms. OR: 10-log sim avg < 130.

**Required telemetry:**
- Collision count per round (bot wanted to move but was blocked)
- Corridor stall count: consecutive rounds where a bot WAITs due to aisle blocked
- Path stretch ratio: actual path length / BFS shortest path length

**Replay scenarios:** Focus on logs that produced lowest scores (123–125) in the 10-log suite — these likely have the most congestion.

**Iteration budget:** 3 variants before kill decision.
- Variant B1: WHCA* with K=3 horizon, bot priority = phase priority.
- Variant B2: Simpler — "one-at-a-time" aisle access. Track aisle occupancy, defer entry if another bot is in the same aisle column.
- Variant B3: Direction-based — assign aisle directions (e.g., aisle x=4 always traversed top→bottom, x=8 always bottom→top). Bots wait at the entry end.

---

### Priority 5: Hypothesis E — Rolling-Horizon Lookahead

**Why now:** Highest complexity, attempt last. Captures emergent multi-agent coordination that rule-based approaches miss.

**Success metric:** 10-log sim avg ≥ 145.

**Failure metric:** Compute time > 15ms (unacceptable) or no improvement over best of A+C+D.

**Required telemetry:**
- "Decision quality" metric: percentage of rounds where lookahead chose a different action than greedy, and that choice led to better score within K rounds.
- Compute time per round (must track p50, p99).

**Replay scenarios:** 10-log suite with per-round decision comparison against greedy.

**Iteration budget:** 2 variants before kill decision (high cost per variant).
- Variant E1: 3 candidate strategies (greedy, batch-one-more, immediate-deliver), 5-round horizon.
- Variant E2: Add "redirect to closer item" and "auto-delivery engineered" as candidate strategies, 8-round horizon.

---

## 6. Iteration Policy

### General Rules

1. **Every strategy change must be tested against the full 10-log benchmark suite** before any live testing. A single-log test is worthless for evaluation (variance is 123–149).

2. **Never combine two untested changes.** Each variant must be isolated and benchmarked independently.

3. **Sim-to-live promotion threshold:** Only promote to live testing if 10-log sim avg ≥ baseline (134.6) AND no individual log drops below 115 (indicating a catastrophic edge case).

4. **Live sample size:** Minimum 5 games for initial assessment. 10 games for promotion decision. Use the existing 5-game benchmark loop command.

5. **Regression vs noise:** A 10-log sim change of ±2 points is within noise. Only changes of ±3 or more across 10 logs are meaningful. For live testing, a 5-game change of ±5 is within noise.

### Per-Strategy Policies

#### Hypothesis A (Multi-Item Trips)

| Rule | Value |
|---|---|
| Minimum variants before kill | 4 |
| Minimum sim runs per variant | 10 logs |
| Minimum live runs per variant (if promoted) | 5 games |
| Promotion to live criteria | 10-log avg ≥ 137 AND items-per-trip ≥ 2.2 |
| Kill criteria | After 4 variants, best 10-log avg < 136 |
| Escalation criteria | If 1 variant hits ≥ 140 but another hits < 125, investigate the divergent log files before killing |
| Stop-loss (overall time) | 8 hours of engineering effort |

#### Hypothesis C (Auto-Delivery Engineering)

| Rule | Value |
|---|---|
| Minimum variants before kill | 3 |
| Minimum sim runs per variant | 10 logs |
| Promotion to live criteria | 10-log avg ≥ 135 AND auto-delivery count ≥ 2/game |
| Kill criteria | After 3 variants, auto-delivery count < 1/game on average |
| Stop-loss | 4 hours |

#### Hypothesis D (Drop-Off Pipelining)

| Rule | Value |
|---|---|
| Minimum variants before kill | 2 |
| Minimum sim runs per variant | 10 logs |
| Promotion to live criteria | 10-log avg ≥ 135 AND WAIT-near-dropoff reduced ≥ 30% |
| Kill criteria | Any variant regresses avg below 132 |
| Stop-loss | 3 hours |

#### Hypothesis B (Reservation Table)

| Rule | Value |
|---|---|
| Minimum variants before kill | 3 (but start with B2 — simplest) |
| Minimum sim runs per variant | 10 logs |
| Promotion to live criteria | 10-log avg ≥ 138 AND round-trip compute < 8ms |
| Kill criteria | Compute > 10ms p99 even with K=3 horizon. OR avg < 130. |
| Stop-loss | 10 hours (complex implementation) |

#### Hypothesis E (Rolling-Horizon Lookahead)

| Rule | Value |
|---|---|
| Minimum variants before kill | 2 |
| Minimum sim runs per variant | 10 logs |
| Promotion to live criteria | 10-log avg ≥ 142 AND compute < 12ms p99 |
| Kill criteria | Compute > 15ms. OR no improvement over best of A+C+D. |
| Stop-loss | 12 hours |

### Refinement Loop Template

For each strategy family:

```
1. Implement Variant X1 (simplest version)
2. Run 10-log sim benchmark
3. If avg < baseline - 3:
     Diagnose: which logs regressed? Why?
     If root cause is fixable → fix → re-benchmark (counts as X2)
     If root cause is fundamental → skip to X(next)
4. If avg ≥ baseline:
     Run 5-game live test
     If live avg ≥ baseline live (134):
         Document as "candidate"
     If live avg < 130:
         Investigate sim-live divergence
5. After all variants exhausted:
     If best variant avg ≥ promotion threshold: PROMOTE (keep in codebase)
     If best variant avg < kill threshold: KILL (revert, document findings)
     If inconclusive: extend by 1 more variant (max 1 extension)
```

---

## 7. Telemetry / Evaluation Gaps

The following metrics are **not currently tracked** but are needed to properly evaluate the proposed strategies. They should be added to the simulator and/or the live telemetry before beginning experiments.

### Critical Missing Metrics

| Metric | Needed For | How to Add |
|---|---|---|
| **Items per delivery trip** | Hypothesis A | In simulator `_try_dropoff()`: count items consumed per DROP_OFF call. Accumulate and report at game end. |
| **Auto-delivery count** | Hypothesis C | In simulator `_auto_deliver_all_bots()`: increment counter when items are auto-delivered. |
| **Bot idle rounds** | All hypotheses | Count rounds where bot action is WAIT or PARK (Phase 4). Already partially tracked by `_analyze_game.py` but not aggregated into bench output. |
| **Drop-off queue length** | Hypothesis D | Each round: count bots with matching items within BFS ≤ 5 of drop-off. Report avg and max per game. |
| **Collision/block count** | Hypothesis B | Each round: count bots whose `resolve_collisions()` output differs from their desired position. Already computable from existing data but not tracked. |
| **Order completion latency** | Hypotheses A, C | Track round of order activation → round of order completion. Report avg and max latency per game. |
| **Path stretch ratio** | Hypothesis B | For each bot move: track BFS shortest distance to goal vs actual steps taken. Report avg stretch ratio per game. |

### Nice-to-Have Metrics

| Metric | Purpose |
|---|---|
| **Congestion heatmap** | Identify which cells are most frequently contested |
| **Delivery latency per item** | Round when bot picks up item → round when bot drops it off |
| **Effective throughput by phase** | What fraction of score comes from Phase 2 vs 2b vs auto-delivery? |
| **Score velocity curve** | Points per 10 rounds over the game — identifies "dead zones" |
| **Preview hit rate** | What fraction of Phase 3b prefetched items are actually useful when their order activates? |

### Instrumentation Plan

Phase 1 (before starting experiments):
1. Add per-game summary stats to `simulate_multi()` in [`scripts/_simulator_hard.py`](../../scripts/_simulator_hard.py): items_per_trip, auto_delivery_count, total_waits, order_latencies.
2. Add these to `_bench.py` output as extra columns.
3. Create `scripts/_telemetry_bench.py` that runs the 10-log suite and outputs a CSV with all metrics.

Phase 2 (add during experiments as needed):
1. Add collision/block counter to the simulator.
2. Add path stretch tracking to `_decide_multi()`.

---

## 8. Final Recommendation

### Top 3 Strategy Directions

#### 1. Multi-Item Trip Planning (Hypothesis A) — START HERE

**Why pursue:** Single highest theoretical payoff. Addresses the fundamental throughput limit. The math is compelling: going from 1.9 to 2.5 items/trip changes the game from ~140 to ~170–180. Every other optimization is additive to this one.

**Why it has a real chance:** The previous failed attempts (item reservation, preview pickup) attacked the symptom (want more items per trip) without changing the root cause (Phase 2 delivers immediately upon having 1 matching item). Changing the delivery trigger is a qualitatively different approach that has never been tried.

**Effort budget:** 8 hours / 4 variants. Kill if no variant achieves items-per-trip ≥ 2.2 in sim.

#### 2. Auto-Delivery Engineering (Hypothesis C) — SECOND PRIORITY

**Why pursue:** Completely exploits a game mechanic that is currently ignored. Low implementation risk, composable with everything else. Even modest success (+3–5 points from 2–3 auto-deliveries per game) is worth the effort.

**Why it has a real chance:** The mechanic is confirmed in both the protocol spec and the simulator code. It's not speculative — it's a documented game rule that we're simply not using. The question is whether we can reliably time bot arrivals, not whether the mechanic works.

**Effort budget:** 4 hours / 3 variants. Kill if auto-delivery events < 1/game after 3 variants.

#### 3. Drop-Off Pipelining (Hypothesis D) — THIRD PRIORITY

**Why pursue:** Low effort, low risk, addresses a known waste (15–20 WAIT rounds near drop-off). Won't break anything even if it doesn't help. Composable with A and C.

**Why it has a real chance:** The problem (multiple bots arriving at drop-off simultaneously) is observable in game logs. The solution (stagger arrivals) is straightforward. The main question is magnitude of impact.

**Effort budget:** 3 hours / 2 variants. Kill if no WAIT reduction or sim regression.

### Composition Strategy

The recommended execution order allows **stacking**:
1. Implement and test A (multi-item trips) first.
2. If A succeeds or is neutral, layer C (auto-delivery) on top of A.
3. If A+C succeed, layer D (drop-off pipelining) on top.
4. After A+C+D, evaluate total improvement. If still below 170, then invest in B (reservation table).
5. Only pursue E (rolling-horizon) if A–D combined don't break 160.

Each layer is independent enough to be implemented, tested, and kept/reverted without affecting the others.

### Honest Assessment of Risk

| Strategy | Chance of +5 points | Chance of +15 points | Chance of regression |
|---|---|---|---|
| A (Multi-Item Trips) | 60% | 30% | 25% (delivery delay risk) |
| C (Auto-Delivery) | 50% | 15% | 10% (low risk) |
| D (Drop-Off Pipeline) | 40% | 5% | 10% (low risk) |
| B (Reservation Table) | 30% | 20% | 30% (high complexity risk) |
| E (Rolling-Horizon) | 25% | 25% | 40% (compute + complexity risk) |

**Combined path A+C+D:** ~70% chance of reaching 150+, ~30% chance of reaching 170+.

**Combined path A+C+D+B:** ~50% chance of reaching 170+, ~20% chance of reaching 180+.

Reaching 180+ is ambitious but not impossible. The key insight from this analysis is that the **plateau is not at the ceiling of what the game allows** — it's at the ceiling of what **single-item greedy delivery** can achieve. Multi-item trips alone could theoretically push to 170–180. The other strategies are hedges and composable boosters.

---

## Appendix: UNKNOWN Items Requiring Discovery

These items need investigation before or during implementation:

1. **UNKNOWN: Does the server enforce `total_orders` strictly?** The `GameState` has `total_orders: int` but it's not used by the planner. If the game ends before all orders are exhausted (likely — 300 rounds for 50 orders is very tight), then optimizing late orders is wasteful. **Discovery:** Check saved game logs — how many orders are typically completed? (Estimated: 16–17 from current performance.)

2. **UNKNOWN: Does `drop_off` auto-deliver from ALL bots or only the bot that triggered the order completion?** Protocol §7.3 says "remaining bot inventory matching the NEW active order is automatically delivered" but doesn't specify whether this applies to all bots at drop-off or just the triggering bot. The simulator implements all-bot auto-delivery (`_auto_deliver_all_bots()` at [`scripts/_simulator_hard.py`](../../scripts/_simulator_hard.py) L296–320). **Discovery:** Test live with 2 bots at drop-off during order transition.

3. **UNKNOWN: Is the order sequence truly deterministic within a day?** The protocol says "Deterministic within a day" (§11.2). But the conversation summary notes "Orders randomized each game" and "HARD_ORDERS list in code is STALE." **Discovery:** Run 3 consecutive live games and compare first 5 order sequences. If identical → deterministic and cacheable. If different → randomized per game (current assumption).

4. **UNKNOWN: Does the server auto-deliver on the same round as the completing DROP_OFF, or on the next round?** If same round: bot A drops last item, bots B/C at drop-off auto-deliver immediately. If next round: there's a 1-round lag. **Discovery:** Inspect saved game log round-by-round around order transitions.

5. **UNKNOWN: Exact aisle collision frequency.** We estimate 20–30 per game (BOT_TASKS.md §T1.3) but haven't measured. **Discovery:** Add collision counter to simulator and run 10-log bench.
