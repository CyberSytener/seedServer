# NMiAI Grocery Bot — Max Score Push

## Objective

Maximise the bot's score on **Easy** difficulty by replacing the greedy
baseline with an optimised planner that exploits the protocol's scoring
rules.

## Scoring Formula (from protocol)

```
score = items_delivered × 1  +  orders_completed × 5
```

- **Easy** — 1 bot, 12×10 grid, 50 orders, 3–4 items/order, 300 rounds,
  inventory cap 3, drop-off at (1,8).
- **Auto-delivery** — when an active order completes, any inventory items
  matching the *new* active order are automatically delivered for free.
- Items respawn; the game is deterministic per day.

## Theoretical Max Score

| Metric | Value |
|--------|-------|
| Upper bound (all 50 orders, 4 items each) | **450** |
| Round-budget estimate (15 rounds/cycle) | **~160** |
| Realistic target with optimised play | **130–150** |

The round budget is the binding constraint — there are not enough rounds
to complete all 50 orders.

## New Modules

### `modules/bot/max_score.py`

- `score_upper_bound(total_orders, max_items_per_order)` — naïve ceiling.
- `estimate_max_score(state)` — round-budget-aware estimate from round-0 state.
- `OrderTracker` — accumulates observed orders during gameplay and projects
  the exact max as more orders become visible.

### `modules/bot/planner.py`

Drop-in replacement for `DecisionEngine` — same `decide(state) → RoundActions`
interface.

**`PlannerConfig`** dataclass with tunable knobs:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lookahead_orders` | 2 | Future orders to scan when scoring items |
| `active_weight` | 10.0 | Utility weight for active-order items |
| `preview_weight` | 3.0 | Utility weight for preview-order items |
| `auto_delivery_bonus` | 5.0 | Extra weight when item enables auto-delivery |
| `prefetch` | True | Pick preview items when no active items remain |
| `deliver_on_full` | True | Deliver when inventory cap reached |
| `deliver_to_complete` | True | Deliver when delivery completes active order |
| `tiebreak_seed` | 0 | Seed for controlled tie-breaking (0 = deterministic) |

**`OptimizedEngine`** key improvements over baseline:

1. **Smarter delivery timing** — delivers only when it completes the order or
   inventory is full. Avoids wasted partial trips.
2. **Utility-based item scoring** — `utility / travel_cost` with deterministic
   tie-breaking by item type and position.
3. **Auto-delivery awareness** — when the current delivery completes an order,
   remaining slots are filled with preview items that auto-deliver on transition.
4. **Prefetch** — picks preview-order items when nothing for the active order
   remains.

### `modules/bot/autotune.py`

Parameter-search harness:

- `generate_config_grid()` — builds a grid of `PlannerConfig` combinations.
- `autotune(difficulty, max_runs, target_score)` — runs games, saves results
  to `.seed_artifacts/nmiai_grocery_bot/autotune/`, persists the best config to
  `app/integrations/nmiai_grocery_bot/best_configs/<difficulty>.json`.
- Early-stops when `target_score` is reached.
- 10-second cooldown between games (server requirement).

## CLI Usage

```bash
# Default: Easy with OptimizedEngine
python scripts/run_nmiai_grocery_bot.py

# Show max-score estimate and exit
python scripts/run_nmiai_grocery_bot.py --show-max

# Use baseline engine for comparison
python scripts/run_nmiai_grocery_bot.py --legacy

# Load best config found by autotune
python scripts/run_nmiai_grocery_bot.py --use-best

# Run autotune (30 runs, stop at score 145)
python scripts/run_nmiai_grocery_bot.py --autotune-easy --max-runs 30 --target-score 145
```

## Test Coverage

| Test file | Tests | Description |
|-----------|-------|-------------|
| `tests/bot/test_max_score.py` | 19 | Upper bound, estimate, OrderTracker |
| `tests/bot/test_planner.py` | 20 | PlannerConfig, OptimizedEngine decisions |
| `tests/bot/test_autotune.py` | 8 | Config grid, save/load persistence |
| **Total new** | **47** | |

Full suite: **101 tests passing** (47 new + 54 existing).

## Files Changed

| File | Change |
|------|--------|
| `modules/bot/models.py` | Added `active_order_index`, `total_orders` to `GameState` |
| `modules/bot/max_score.py` | **New** — scoring estimates |
| `modules/bot/planner.py` | **New** — `PlannerConfig` + `OptimizedEngine` |
| `modules/bot/autotune.py` | **New** — parameter search harness |
| `app/integrations/nmiai_grocery_bot/ws_client.py` | Engine-agnostic `_play()` |
| `scripts/run_nmiai_grocery_bot.py` | Added `--show-max`, `--legacy`, `--use-best`, `--autotune-easy` flags |

## Baseline vs Optimised

| Engine | Score | Notes |
|--------|-------|-------|
| DecisionEngine (baseline) | 114 | Greedy nearest-item |
| OptimizedEngine (default config) | TBD | Utility-based + auto-delivery |
| OptimizedEngine (autotuned) | TBD | Best config from parameter search |

Run a live game to fill in the TBD values:

```bash
python scripts/run_nmiai_grocery_bot.py --difficulty easy
```
