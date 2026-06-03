# Bot Readiness Audit — 2026-02-28

> **Scope:** Evidence-based audit of Seed Server fitness for NMiAI Grocery Bot Challenge  
> **Method:** Source code reads, grep searches, dependency verification, test execution  
> **Test baseline:** 1236 unit passed / 7 skipped; 61 integration passed / 2 skipped / 3 failed  
> **Python:** 3.12.10 · **Framework:** FastAPI · **websockets:** 16.0 (via uvicorn[standard])  
> **Branch:** `feature/phase0-followup`

---

## 1. Executive Summary

Seed Server is an **LLM-orchestration platform**, not a game engine. Its strengths — async infrastructure, multi-provider LLM facade, structured logging, simulation harness — are partially reusable for a competition bot. However, the core agent loop (`AgentSession.process_message()`) is **too heavyweight** for the 2-second per-round deadline, and the platform has **zero** pathfinding, spatial reasoning, or outbound WebSocket client code.

**Verdict:** ~35–40% of Seed infrastructure is directly reusable. The remaining 60% must be built from scratch or is irrelevant. The competition bot should be **primarily algorithmic** with Seed providing async plumbing, LLM facade (for optional strategic advice), Pydantic models, and the simulation/replay pattern.

---

## 2. Reusable Seed Subsystems

### 2.1 Async Infrastructure (Python 3.12 + asyncio)

| What | Evidence | Reuse Level |
|------|----------|-------------|
| `asyncio` event loop, `gather`, `wait_for` | Used throughout: `session.py:L380` (`asyncio.gather`), gateway.py (`asyncio.wait`) | **Direct** — game loop will be pure async |
| Pydantic v2 for data models | `pyproject.toml:L16` (`pydantic==2.6.4`), used in all API types | **Direct** — game state models |
| `websockets` 16.0 library available | Installed via `uvicorn[standard]`; verified: `python -c "import websockets"` → 16.0 | **Direct** — WS client to game server |
| `httpx` async HTTP client | `pyproject.toml:L17` (`httpx[http2]==0.27.0`) | **Available** if HTTP API needed |

### 2.2 UnifiedLLMService — LLM Facade

| What | Evidence | Reuse Level |
|------|----------|-------------|
| `UnifiedLLMService` with pluggable providers | `app/core/llm/unified.py:L157-L293` — `agenerate()`, `agenerate_with_metadata()` | **Reusable** for optional strategic planner |
| `LLMProvider` Protocol (duck-typed) | `app/core/llm/protocol.py:L44-L79` — `generate()`, `agenerate()`, `provider_name`, `is_available` | **Reusable** — clean contract |
| Gemini fast model (`gemini-2.0-flash`) | `app/settings.py:L236` — `SEED_GEMINI_MODEL_FAST` default | **Reusable** — ~400ms typical latency |
| OpenAI fast model (`gpt-4.1-mini`) | `app/settings.py:L232` — `SEED_OPENAI_MODEL_FAST` default | **Reusable** — ~300ms typical latency |
| Stub provider for testing | `app/sim/llm_stub.py:L13-L77` — `DeterministicLLMPipelineStub` | **Reusable** — deterministic test mode |

**Timing concern:** A single `agenerate()` call to `gemini-2.0-flash` takes ~400-800ms. Within a 2000ms round budget, this leaves 1200-1600ms for everything else. Viable for **occasional** strategic LLM calls (every N rounds), not per-round.

### 2.3 Simulation / Replay Harness

| What | Evidence | Reuse Level |
|------|----------|-------------|
| `SimulationReport` dataclass | `app/sim/contracts.py:L41-L54` — `run_id`, `scenarios`, `passed/failed`, `duration_ms` | **Adaptable** — extend for game match reports |
| `ScenarioResult` with assertions | `app/sim/contracts.py:L26-L38` — `assertions`, `artifacts`, `error` | **Adaptable** — per-round assertions |
| `InMemoryAsyncRedis` mock | `app/sim/fake_redis.py:L1-L165` — full Redis mock with pub/sub, pipeline, TTL | **Reusable** for offline replay without Redis |
| `DeterministicLLMPipelineStub` | `app/sim/llm_stub.py:L13-L77` — deterministic responses | **Reusable** for strategy testing without LLM |
| `run_simulation()` harness pattern | `app/sim/harness.py:L1-L919` — scenario-based test execution | **Pattern reusable** — adapt for game replay |

### 2.4 Structured Logging

| What | Evidence | Reuse Level |
|------|----------|-------------|
| JSON logger configured | `pyproject.toml:L22` (`python-json-logger==2.0.7`) | **Direct** |
| PII masking utilities | `app/infrastructure/log_utils.py:L1-L50` — `mask_api_key()`, `mask_email()` | **Low relevance** for game bot |
| Saga audit log pattern | `app/core/realtime/sagas/saga_audit_log.py` — `SagaAuditLogger` | **Pattern reusable** for game telemetry |

### 2.5 Settings / Configuration Pattern

| What | Evidence | Reuse Level |
|------|----------|-------------|
| `Settings` frozen dataclass | `app/settings.py:L7-L109` — env-driven, typed | **Reusable** — add bot-specific settings |
| `_get_int()`, `_get_bool()` helpers | `app/settings.py:L111-L137` — safe env parsing | **Direct** |

### 2.6 Rate Limiter / Timeout Control

| What | Evidence | Reuse Level |
|------|----------|-------------|
| Redis-backed rate limiter | `app/core/rate_limit.py` — atomic INCR+EXPIRE | **Irrelevant** — game server controls rate |
| `SEED_FAST_TIMEOUT_SEC` (default 3s) | `app/settings.py:L214` | **Adaptable** — change to 1.8s for round deadline |
| `RequestPriority` enum | `app/core/realtime/optimized/realtime_handler.py:L35-L39` — `CRITICAL <100ms`, `HIGH <500ms`, `NORMAL <2s` | **Pattern only** — priority concept useful |

---

## 3. Non-Reusable / Overkill Seed Subsystems

### 3.1 AgentSession — Core Orchestrator ❌

| Aspect | Evidence | Why Not Reusable |
|--------|----------|-----------------|
| Full `process_message()` loop | `app/core/agent/session.py:L400-L600` — loads session, resolves history, builds prompt, calls LLM, parses XML tool calls, persists messages, emits events, checks budget | **~1-3 seconds per call**. 300 rounds × 2s deadline = impossible overhead |
| 15 DI parameters in constructor | `session.py:L180-L200` — session_store, tool_registry, action_router, llm_service, artifact_store, persona_loader, auth_context, sandbox_dispatcher, budget_factory, tenant_governance, marketplace_service, event_emitter, sandbox_token_issuer, max_iterations, max_nesting_depth | **Massive wiring** for a self-contained bot |
| History assembly (last 20 messages) | `session.py:L108-L125` — iterates message history per call | **Per-round cost** — game state is full-state, no history needed |
| XML `<tool_call>` parsing | `session.py:L44-L69` — `_TOOL_CALL_RE` regex | **Irrelevant** — bot actions are deterministic, not LLM-parsed |
| Tool manifest inclusion | `session.py:L530` — only on iteration 0 | **Irrelevant** — no tool manifest for game actions |
| `spawn_child_session()` / `delegate_parallel()` | `session.py:L213-L395` — child sessions with persistence | **Overkill** — bot knows all bots directly; no session overhead needed |

### 3.2 AgentBudget — Parent-Child Hierarchy ❌

| Aspect | Evidence | Why Not Reusable |
|--------|----------|-----------------|
| Budget enforcement per LLM call | `budget.py:L30-L32` — `max_total_tokens: 10000`, `max_tool_calls: 20` | **Wrong abstraction** — game has round limits, not token limits |
| Parent-child budget splits | `budget.py:L117-L150` — `create_child()`, `split_budget()` | **No parent-child** in game loop |
| `asyncio.Lock` for parallel consume | `budget.py:L280-L290` | **Not needed** — single-threaded per round |

### 3.3 Session Store / Persistence ❌

| Aspect | Evidence | Why Not Reusable |
|--------|----------|-----------------|
| SQLite session persistence | `app/core/agent/session_store.py:L1-L233` — full CRUD + participants | **Zero value** — game state is ephemeral, received fresh each round |
| Message append + history retrieval | `session_store.py:L130-L170` | **Not needed** — no conversation history |

### 3.4 Sandbox / RPC ❌

| Aspect | Evidence | Why Not Reusable |
|--------|----------|-----------------|
| Redis RPC dispatch to sandbox worker | `app/core/agent/sandbox_dispatcher.py:L60-L100` — RPUSH + BLPOP with 30s timeout | **30s timeout alone disqualifies** |
| JWT sandbox tokens | `app/core/agent/sandbox_jwt.py` | **No sandbox needed** for game bot |
| Sandbox worker container | `app/agent_sandbox_worker.py:L1-L254` | **Irrelevant** |

### 3.5 WebSocket Server Gateway ❌

| Aspect | Evidence | Why Not Reusable |
|--------|----------|-----------------|
| WS **server** endpoint at `/ws` | `app/api/ws/gateway.py:L103-L112` — accepts connections, JWT auth | **Wrong direction** — bot needs WS **client** |
| Redis session store for WS | `app/api/ws/session.py` — `RedisSessionStore` | **Not needed** |
| Agent stream message types | `app/api/ws/agent_types.py:L1-L216` — 8 Pydantic message types | **Wrong protocol** — game uses its own JSON schema |

### 3.6 Tenant Governance / Marketplace / Billing ❌

All tenant/marketplace code is entirely irrelevant for a competition bot.

### 3.7 Saga Orchestrator ⚠️ (Overkill)

| Aspect | Evidence | Why Not Reusable |
|--------|----------|-----------------|
| Full saga engine | `app/core/realtime/sagas/orchestrator.py` — compensation, DLQ, distributed locking | **Way too heavy** for per-round decisions |
| Circuit breaker | `app/infrastructure/realtime/engine/circuit_breaker.py` | **Useful pattern** but bot handles disconnection at protocol level |

---

## 4. Missing Capabilities

### 4.1 Outbound WebSocket Client — **BLOCKER**

**Status:** No outbound WS client code exists in production.  
**Evidence:** `grep -rn "websockets.connect" app/` → 0 matches. The only hit is in `app/core/realtime/optimized/integration_example.py:L493` — a documentation example, not production code.  
**Required:** `async with websockets.connect(url) as ws:` loop that receives `game_state` and sends `{"actions": [...]}` within 2 seconds.  
**Effort:** ~80-120 LoC for robust implementation with timeout guards, reconnection logic, and error handling.

### 4.2 Grid Pathfinding (A*, BFS) — **BLOCKER**

**Status:** Zero pathfinding algorithms in the codebase.  
**Evidence:** `grep -rn "pathfind\|bfs\|dijkstra\|a_star\|astar\|breadth.first\|shortest.path" app/` → 0 matches in application code. BFS exists only in `session_store.get_session_tree()` for session tree traversal (unrelated to spatial grids).  
**Required:**  
- Grid representation with wall cells  
- BFS for shortest path (unweighted grid)  
- A* for optimized pathfinding  
- Dynamic obstacle handling (other bots as temporary walls)  
**Effort:** ~200-300 LoC for BFS + A* with collision avoidance.

### 4.3 Multi-Bot Collision Avoidance — **BLOCKER**

**Status:** No spatial collision logic exists.  
**Evidence:** No concept of grid cells, bot positions, or collision detection anywhere in the codebase.  
**Required:**  
- Cell reservation system (bot claims next cell before moving)  
- Cooperative pathfinding (don't route two bots through same cell)  
- Deadlock detection/resolution  
**Effort:** ~150-250 LoC for reservation-based coordination.

### 4.4 Task Assignment / Order Planning — **BLOCKER**

**Status:** No item-assignment or order-fulfillment logic exists.  
**Evidence:** The closest concept is `ActionRouter` which routes named actions to executors — but this is LLM action routing, not spatial task assignment.  
**Required:**  
- Parse active + preview orders  
- Compute still-needed items  
- Assign items to nearest available bots (greedy or Hungarian assignment)  
- Handle inventory capacity (max 3 items/bot)  
- Dropoff prioritization  
**Effort:** ~200-300 LoC.

### 4.5 Deterministic Game Simulator — **IMPORTANT**

**Status:** The sim harness (`app/sim/harness.py`) runs API-level scenarios, not game simulations.  
**Evidence:** `harness.py:L1-L919` — uses `TestClient` to hit HTTP endpoints. No grid, no tick loop, no game physics.  
**Required:**  
- Local game state simulator (apply actions, check rules, compute score)  
- Replay from recorded game states  
- Deterministic seeding for daily maps  
**Effort:** ~300-400 LoC for faithful game rules simulator.

### 4.6 Per-Round Timeout Guard — **IMPORTANT**

**Status:** `asyncio.wait_for` exists in Python stdlib. Seed's `SEED_FAST_TIMEOUT_SEC` (default 3s in `settings.py:L214`) is a configuration constant, not a per-operation guard.  
**Evidence:** No `asyncio.wait_for` wrapping any round-level decision in current code.  
**Required:** Every round decision must complete within ~1800ms, with a fallback "safe action" policy if the deadline is about to expire.  
**Effort:** ~30-50 LoC for the guard wrapper.

---

## 5. Timing / Latency Risk Assessment

### 5.1 Round Budget Breakdown (2000ms total)

| Phase | Estimated Time | Notes |
|-------|---------------|-------|
| WS recv + JSON parse | ~5-20ms | `websockets` + `json.loads` on ~2KB payload |
| Game state model validation | ~1-5ms | Pydantic v2 validation |
| Pathfinding (A* for 10 bots on 28×18 grid) | ~1-10ms | A* on 504-cell grid is trivial |
| Task assignment (10 bots, 16 items) | ~1-5ms | Greedy or Hungarian on small sets |
| Collision resolution | ~1-5ms | Reservation-based, iterative |
| Action serialization + WS send | ~5-20ms | `json.dumps` + `ws.send` |
| **Total algorithmic path** | **~15-65ms** | **Well within budget** |
| **Total with 1 LLM call** | **~400-900ms** | Viable but risky for every round |
| **Total with full AgentSession** | **~1500-3000ms** | **EXCEEDS DEADLINE** |

### 5.2 Timing Verdict

- **Pure algorithmic:** ~15-65ms per round → **97% headroom**. Safe.
- **Algorithmic + LLM every 10-20 rounds:** ~15ms typical + ~600ms every 10th → **Safe** with fallback.
- **LLM every round:** ~400-900ms → **Risky.** Network variance could push past 2s.
- **Full AgentSession loop:** ~1500-3000ms → **WILL FAIL.** Not viable.

### 5.3 Critical Path Analysis

```
Round starts (t=0)
├── recv game_state         (~10ms, t=10)
├── parse + validate        (~5ms, t=15)
├── compute needed items    (~1ms, t=16)
├── assign items to bots    (~3ms, t=19)
├── pathfind per bot (10×)  (~5ms, t=24)
├── collision resolution    (~3ms, t=27)
├── serialize actions       (~3ms, t=30)
└── send response           (~10ms, t=40)
                            Total: ~40ms
                            Deadline: 2000ms
                            Margin: 1960ms
```

---

## 6. Architecture Recommendation

### Primary: **Option A — Fully Algorithmic Bot**

**Justification:**
1. **Timing:** 40ms per round vs. 2000ms deadline → 50× safety margin.
2. **Determinism:** Same input → same output. Reproducible for debugging and replay.
3. **Reliability:** No network dependency on LLM API. No latency spikes from provider.
4. **Scoring:** Grocery Bot rewards efficient item delivery, not creative reasoning. BFS + greedy assignment is optimal for known grid.
5. **Complexity:** Challenge is coordination, not reasoning. Multi-bot pathfinding with collision avoidance is an algorithms problem, not an LLM problem.

**Fallback:** Option B (hybrid) if algorithmic scoring plateaus and strategic pre-computation proves beneficial.

### Why NOT Option B (Hybrid Algorithmic + LLM)

LLM could theoretically help with:
- Choosing which preview order to pre-pick for
- Long-horizon planning (which items to pick in what order across 300 rounds)

But:
- Preview order is only 1 lookahead, and greedy "pick nearest needed item" is near-optimal for this
- 300 rounds with full visibility → optimal planning is computable algorithmically
- LLM adds latency, cost, and non-determinism for marginal gain

### Why NOT Option C (Full AgentSession Loop)

- **1500-3000ms per round** exceeds 2000ms deadline
- Session persistence, history assembly, tool manifest injection, XML parsing — all wasted overhead
- The game protocol is not an LLM conversation; it's a state→actions function

---

## 7. Difficulty-by-Difficulty Strategy

### Easy (12×10, 1 bot, 2 aisles, 4 item types, orders 3-4)

**Strategy:** Single-bot greedy pathfinder.
- Pick closest needed item (BFS shortest path)
- When inventory full or all needed items carried, go to drop-off
- No collision avoidance needed (1 bot)
- **Expected score:** Near-optimal. Bottleneck is path length, not strategy.

### Medium (16×12, 3 bots, 3 aisles, 8 item types, orders 3-5)

**Strategy:** Simple task assignment + BFS.
- Assign each needed item to nearest available bot
- Avoid duplicate assignments (shared assignment set)
- Basic collision: if next cell occupied, wait 1 round
- Preview order: if a bot is idle, start picking preview items
- **Expected score:** Good. Collision avoidance matters but is simple with 3 bots.

### Hard (22×14, 5 bots, 4 aisles, 12 item types, orders 3-5)

**Strategy:** Hungarian-style assignment + A* + reservation.
- Use cost matrix (bot→item distance) for optimal assignment
- A* pathfinding with dynamic obstacles (other bots)
- Cell reservation: bot claims its next N cells; others route around
- Dedicated "delivery bot" role: 1-2 bots focus on delivering full inventories
- Preview order pre-picking by idle bots
- **Expected score:** Competitive. Coordination quality becomes the differentiator.

### Expert (28×18, 10 bots, 5 aisles, 16 item types, orders 4-6)

**Strategy:** Full swarm coordination.
- Zone-based assignment: divide store into sectors, assign bots to zones
- Cooperative A* or windowed HCA* for deadlock-free routing
- Pipeline pattern: some bots pick, some deliver, rotating roles based on inventory
- Aggressive preview order picking
- Anti-congestion: spread bots across aisles to reduce blocking
- **Expected score:** Highly dependent on coordination quality. This is where the competition is won or lost.

---

## 8. Final Verdict

### Reusable As-Is

| Component | File | What For |
|-----------|------|----------|
| `asyncio` event loop + `gather` | stdlib | Game loop, parallel I/O |
| `websockets` 16.0 library | (installed) | WS client to game server |
| `Pydantic v2` | `pyproject.toml` | Game state models, validation |
| `Settings` dataclass pattern | `app/settings.py` | Bot configuration (token, difficulty, etc.) |
| `_get_int()`, `_get_bool()` env helpers | `app/settings.py:L111-L137` | Config parsing |
| `python-json-logger` | `pyproject.toml:L22` | JSON-structured game telemetry |
| `UnifiedLLMService.agenerate()` | `app/core/llm/unified.py:L233-L248` | Optional strategic planner (if hybrid) |
| `LLMProvider` Protocol | `app/core/llm/protocol.py:L44-L79` | Provider abstraction |
| `DeterministicLLMPipelineStub` | `app/sim/llm_stub.py:L13-L77` | Offline testing without LLM |

### Must Be Adapted

| Component | Source | Adaptation Needed |
|-----------|--------|-------------------|
| `SimulationReport` / `ScenarioResult` | `app/sim/contracts.py` | Extend for game match reporting: per-round scores, total items, orders completed |
| `InMemoryAsyncRedis` | `app/sim/fake_redis.py` | Only if bot needs Redis for any reason (unlikely) |
| `sim/harness.py` pattern | `app/sim/harness.py` | Rewrite run loop for game replay instead of HTTP scenarios |
| `RequestPriority` concept | `app/core/realtime/optimized/realtime_handler.py:L35-L39` | Triage pattern for deadline management |

### Must Be Built Fresh

| Component | Estimated LoC | Priority |
|-----------|---------------|----------|
| Game WS client (connect, recv, send loop) | ~100-150 | **P0 — Blocker** |
| Game state Pydantic models | ~80-120 | **P0 — Blocker** |
| Grid representation + BFS pathfinding | ~100-150 | **P0 — Blocker** |
| A* pathfinding with dynamic obstacles | ~80-120 | **P0 — Blocker** |
| Multi-bot collision avoidance (reservation) | ~150-250 | **P1 — Required for Medium+** |
| Task assignment engine (greedy + Hungarian) | ~150-200 | **P1 — Required for scoring** |
| Order logic (active/preview, needed items) | ~60-80 | **P0 — Blocker** |
| Inventory + dropoff logic | ~40-60 | **P0 — Blocker** |
| Per-round timeout guard with safe fallback | ~30-50 | **P0 — Safety** |
| Local game simulator for replay/testing | ~300-400 | **P1 — Debug/iterate** |
| Benchmark harness (timing per phase) | ~50-80 | **P1 — Verification** |
| Difficulty-specific tuning (zones, roles) | ~100-200 | **P2 — Competition edge** |
| **Total new code** | **~1240-1860** | |

---

## Appendix A: Verification Commands Used

```bash
# Test baseline
python -m pytest tests/unit -q --tb=no --timeout=120
# Result: 1236 passed, 7 skipped in 25.55s

python -m pytest tests/integration -q --tb=line --timeout=30
# Result: 3 failed, 61 passed, 2 skipped in 14.11s

# websockets library check
python -c "import websockets; print(websockets.__version__)"
# Result: 16.0

# Pathfinding search (negative evidence)
grep -rn "pathfind\|bfs\|dijkstra\|a_star\|astar" app/
# Result: 0 matches in application code

# WS client search (negative evidence)
grep -rn "websockets.connect\|aiohttp.ClientSession" app/
# Result: 1 match in integration_example.py (docs only, not production)
```
