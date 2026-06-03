# Seed Server — Task Tracker (Roadmap Execution)

> Current note, 2026-05-06: this file is retained as phase/task history. For the live backlog use `PROBLEMS_AND_TASKS.md`; for the latest project analysis use `docs/CURRENT_PROJECT_ANALYSIS_2026-05-06.md`.

**Roadmap source:** `roadmap.md` | **Audit source:** `docs/AGENT_PLATFORM_AUDIT_2026-02-28.md`
**Archive:** Phase 0 Agent Platform Expansion (P0-01 → P0-43) archived to `docs/TASKS_ARCHIVE_2026-02-28.md`; Phases 0–6 + legacy archived to `docs/TASKS_ARCHIVE_2026-03-05.md`
**Last updated:** 2026-02-28
**Branch:** `feature/phase0-followup`
**Test baseline:** 1236 unit passed, 7 skipped; 61 integration passed, 2 skipped, 3 failed (InMemoryStore fixture gap — see audit R-3)

---

## Standing Invariants

All invariants from Phase 0 (I-1 through I-15) remain in force. See `docs/TASKS_ARCHIVE_2026-02-28.md` for the full invariant table.

**Key invariants for new work:**
- I-1: Agent never gets direct core access. All actions through Tools.
- I-3: Hard budgets enforced server-side by `AgentBudget`. Model cannot bypass.
- I-4: Human confirmation gates for dangerous operations. Default read-only.
- I-8: Sandbox: tmpfs, no secrets, narrow Redis RPC. No "open shell."
- I-12: GitHub fetch runs ONLY in sandbox.
- I-15: Tenant billing is the single cost accounting layer.

---

# Roadmap — Post Phase 0 Agent Platform

> **Source:** `docs/AGENT_PLATFORM_AUDIT_2026-02-28.md`
> **Methodology:** Every task below cites a concrete file:line or test output as evidence. No speculative tasks.
> **Rules:** (1) No runtime code changes unless the task explicitly specifies them. (2) Each task has a DoD and verification command. (3) Tasks are ordered by dependency, not priority alone.

---

## Phase A — Stabilization (fix what's broken)

> **Goal:** Green CI. Fix the 3 integration failures, eliminate the two high-severity risks, and clean up deprecated API usage. Zero new features.

### A-1: Extract shared InMemoryAgentSessionStore test fixture

- **Priority:** P0
- **Why:** 3 integration tests fail because 7 separate `InMemoryStore` classes in test files are out of sync with the production `AgentSessionStore` interface.
- **Evidence:**
  - `tests/integration/test_agent_demo_scenario.py:65-93` — `InMemoryStore` missing `list_child_sessions`, `cancel_session_tree`, `get_session_tree`, and all participant methods.
  - Production store at `app/core/agent/session_store.py` has 15 methods; test fixture has 6.
  - Audit risk R-3.
- **Implementation:**
  - Create `tests/support/in_memory_agent_store.py` with `InMemoryAgentSessionStore` implementing the full interface: `create_session`, `get_session`, `update_session`, `delete_session`, `append_message`, `get_messages`, `list_child_sessions`, `get_session_tree`, `cancel_session_tree`, `add_participant`, `remove_participant`, `get_participant`, `list_participants`.
  - Update all 7 test files to import from the shared fixture.
  - Run `python -m pytest tests/integration/test_agent_demo_scenario.py -v` — must pass.
- **DoD:** All 3 integration failures resolved. `python -m pytest tests/integration -q` → 0 failures.
- **Verification:** `python -m pytest tests/integration -q --tb=line --timeout=30`
- **Affected Files:**
  - `tests/support/in_memory_agent_store.py` (new)
  - `tests/integration/test_agent_demo_scenario.py` (modify — replace InMemoryStore import)
  - `tests/integration/test_agent_github_fetch_demo.py` (modify)
  - `tests/integration/test_agent_tenant_demo.py` (modify)
  - `tests/integration/test_agent_ws_demo.py` (modify)
  - `tests/integration/test_agent_multi_agent_demo.py` (modify)
  - `tests/unit/test_sandbox_routing.py` (modify)
  - `tests/unit/test_agent_budget_enforcement.py` (modify)

### A-2: Narrow router_registration agent exception catch

- **Priority:** P0
- **Why:** `router_registration.py:207` catches `(ImportError, Exception)`, silently swallowing all startup errors for the agent API. A config error, DB failure, or attribute error would make the entire agent API disappear at runtime with only a warning log.
- **Evidence:**
  - `app/infrastructure/router_registration.py:207` — `except (ImportError, Exception) as e:`.
  - Every other router block in the same file (15+ blocks) catches only `ImportError`.
  - Audit risk R-1.
- **Implementation:**
  - Change `except (ImportError, Exception) as e:` to `except ImportError as e:` at line 207.
  - This matches the pattern used by all other router blocks in the same file.
- **DoD:** Agent startup errors propagate to caller. Only `ImportError` is suppressed.
- **Verification:** `python -m pytest tests/unit -q --tb=no --timeout=60` (no regressions)
- **Affected Files:**
  - `app/infrastructure/router_registration.py` (modify — 1 line)

### A-3: Guard sandbox JWT secret when sandbox is enabled

- **Priority:** P0
- **Why:** `sandbox_jwt.py` falls back to a hardcoded `_DEV_SECRET` when `SEED_SANDBOX_JWT_SECRET` is not set. Anyone can forge sandbox RPC requests with the known key.
- **Evidence:**
  - `app/core/agent/sandbox_jwt.py` line ~20: `_DEV_SECRET = "seed-sandbox-dev-secret-DO-NOT-USE-IN-PRODUCTION"`.
  - Used as fallback in `issue_sandbox_token()` and `validate_sandbox_token()`.
  - Audit risk R-2.
- **Implementation:**
  - In `issue_sandbox_token()` and `validate_sandbox_token()`: if `SEED_SANDBOX_JWT_SECRET` is not set AND `SEED_SANDBOX_ENABLED=true`, raise `RuntimeError("SEED_SANDBOX_JWT_SECRET required when sandbox is enabled")`.
  - Keep `_DEV_SECRET` fallback ONLY when `SEED_SANDBOX_ENABLED` is false/unset (local dev).
  - Add unit test verifying the guard.
- **DoD:** Sandbox-enabled startup without secret → startup error. Local dev (sandbox disabled) → still works with dev secret.
- **Verification:** `python -m pytest tests/unit/test_sandbox_jwt_validation.py -v`
- **Affected Files:**
  - `app/core/agent/sandbox_jwt.py` (modify)
  - `tests/unit/test_sandbox_jwt_validation.py` (modify — add guard test)

### A-4: Replace deprecated `asyncio.get_event_loop()` calls

- **Priority:** P1
- **Why:** `session.py` uses `asyncio.get_event_loop()` at lines 936 and 980 to run sync `ActionRouter.execute_action()` and `SandboxDispatcher.dispatch()` in an executor. Deprecated since Python 3.10; will error in future versions.
- **Evidence:**
  - `app/core/agent/session.py:936` — `loop = asyncio.get_event_loop()`
  - `app/core/agent/session.py:980` — `loop = asyncio.get_event_loop()`
  - Both used for `loop.run_in_executor(None, lambda: ...)`.
- **Implementation:**
  - Replace both with `loop = asyncio.get_running_loop()`.
  - Verify no other `get_event_loop()` calls exist in agent code.
- **DoD:** `grep -rn "get_event_loop" app/core/agent/` → 0 matches. All agent tests pass.
- **Verification:** `python -m pytest tests/unit -k "agent" -q --tb=no --timeout=60`
- **Affected Files:**
  - `app/core/agent/session.py` (modify — 2 lines)

---

## Phase B — Sandbox & Fetch Hardening

> **Goal:** Make the sandbox worker production-ready. Add health monitoring, per-job timeouts, and fix the BlockRegistry-per-job overhead.

### B-1: Sandbox worker health check / heartbeat

- **Priority:** P1
- **Why:** If the sandbox worker crashes silently, all API-side dispatches will timeout (30s default) with no early warning system.
- **Evidence:**
  - `app/agent_sandbox_worker.py` — main loop only BLPOP polls Redis. No liveness probe, no heartbeat.
  - `app/core/agent/sandbox_dispatcher.py` — `dispatch()` does BLPOP with timeout but no pre-check for worker liveness.
  - Audit risk R-5.
- **Implementation:**
  - Sandbox worker: set a Redis key `agent_sandbox:heartbeat` with value `{timestamp, rpc_count}` every 10 seconds (or on each successful BLPOP). TTL: 30 seconds.
  - API-side `SandboxDispatcher.dispatch()`: before sending RPC, check if `agent_sandbox:heartbeat` exists and is < 30s old. If stale, return early error instead of waiting for 30s timeout.
  - Add docker healthcheck: `CMD python -c "import redis; r=redis.from_url(...); assert r.exists('agent_sandbox:heartbeat')"`.
- **DoD:** Worker publishes heartbeat. Dispatcher checks heartbeat before dispatch. Stale heartbeat → early error. Docker healthcheck defined.
- **Verification:** `python -m pytest tests/unit/test_sandbox_health.py -v` (new test)
- **Affected Files:**
  - `app/agent_sandbox_worker.py` (modify — heartbeat emission)
  - `app/core/agent/sandbox_dispatcher.py` (modify — heartbeat check)
  - `docker-compose.yml` (modify — healthcheck)
  - `tests/unit/test_sandbox_health.py` (new)

### B-2: Per-job execution timeout in sandbox worker

- **Priority:** P1
- **Why:** A hanging block (e.g., infinite loop in a tool) blocks the worker indefinitely. No per-job watchdog exists.
- **Evidence:**
  - `app/agent_sandbox_worker.py:160-180` — `_process_job()` has a try/except for execution but no timeout.
  - `job.get("timeout_seconds", 30)` is extracted from the RPC payload but never enforced.
- **Implementation:**
  - Wrap `block.execute(tool_input)` in `signal.alarm()` (Unix) or `threading.Timer` (cross-platform) with timeout from `job["timeout_seconds"]` (default 30s).
  - On timeout: return `{"status": "error", "error": "Tool execution timeout"}`.
- **DoD:** Hanging block → timeout error returned within configured seconds. Worker continues processing next job.
- **Verification:** `python -m pytest tests/unit/test_sandbox_timeout.py -v` (new test)
- **Affected Files:**
  - `app/agent_sandbox_worker.py` (modify)
  - `tests/unit/test_sandbox_timeout.py` (new)

### B-3: Cache BlockRegistry in sandbox worker

- **Priority:** P2
- **Why:** `agent_sandbox_worker.py:168` creates `BlockRegistry()` for every RPC job. Registry construction scans for blocks and is needlessly repeated.
- **Evidence:**
  - `app/agent_sandbox_worker.py:168` — `block_registry = BlockRegistry()` inside `_process_job()`.
  - `app/core/blocks.py:76` — `build_default_registry()` registers ~30 blocks + dynamic scan.
- **Implementation:**
  - Move `BlockRegistry` construction to module-level or worker startup (before main loop). Pass to `_process_job()` as parameter.
- **DoD:** `BlockRegistry()` constructed once per worker lifetime. Jobs use cached instance.
- **Verification:** `python -m pytest tests/unit -k "sandbox" -q --tb=no`
- **Affected Files:**
  - `app/agent_sandbox_worker.py` (modify)

---

## Phase C — Agent Loop Quality

> **Goal:** Fix the confirmation stub, make tool-call parsing provider-agnostic, and ensure tool manifests persist across loop iterations.

### C-1: Implement `_is_pre_confirmed()` properly

- **Priority:** P1
- **Why:** Currently always returns `False` (line 854-866). The outer confirmation resolution at the top of `process_message()` handles explicit confirm/cancel correctly, but the inner loop re-emits confirmation requests even when the user has already confirmed in the same turn.
- **Evidence:**
  - `app/core/agent/session.py:854-866` — `_is_pre_confirmed()` returns `False` unconditionally.
  - Comments in the method say "In this implementation, if a confirmation is still in pending, it has NOT been confirmed yet."
  - Audit risk R-6.
- **Implementation:**
  - Track resolved confirmation IDs within the current `process_message()` call scope.
  - `_is_pre_confirmed()` should check if the tool call matches a just-resolved confirmation (same tool name + matching input hash).
  - This prevents the LLM from being asked to re-confirm a tool that was already confirmed.
- **DoD:** Tool confirmed → re-emitted confirmation request suppressed. Test: confirm tool → same tool call in next iteration → executes without re-asking.
- **Verification:** `python -m pytest tests/unit/test_agent_confirmation_gate.py -v`
- **Affected Files:**
  - `app/core/agent/session.py` (modify)
  - `tests/unit/test_agent_confirmation_gate.py` (modify — add re-confirmation test)

### C-2: Provider-agnostic tool call parser

- **Priority:** P1
- **Why:** `parse_tool_calls()` uses `<tool_call>` XML regex. Works with StubProvider but incompatible with real OpenAI/Anthropic function-calling responses where tool calls are in the API response object, not XML-tagged text.
- **Evidence:**
  - `app/core/agent/session.py:44-69` — `_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>")`.
  - `app/core/agent/session.py:595` — `tool_calls = parse_tool_calls(gen_result.text)`.
  - `app/core/llm/protocol.py` — `GenerationResult` has `text` field but may gain `tool_calls` field for native function calling.
  - Audit risk R-7.
- **Implementation:**
  - Extend `GenerationResult` (or create an adapter) to carry structured `tool_calls: List[ToolCall]` alongside `text`.
  - In `process_message()`, prefer `gen_result.tool_calls` if present; fall back to XML regex parsing.
  - Keep XML parsing as a fallback for providers that return only text.
  - This enables a smooth migration path: current StubProvider keeps working, new OpenAI/Anthropic providers return native tool calls.
- **DoD:** Agent loop accepts tool calls from both native format and XML fallback. Tests cover both paths.
- **Verification:** `python -m pytest tests/unit/test_agent_session_loop.py tests/unit/test_agent_tool_call_parser.py -v`
- **Affected Files:**
  - `app/core/agent/session.py` (modify — dual parser)
  - `app/core/llm/protocol.py` (modify — add `tool_calls` field to `GenerationResult`)
  - `tests/unit/test_agent_tool_call_parser.py` (new)

### C-3: Persist tool manifests across loop iterations

- **Priority:** P2
- **Why:** Tool manifests are sent to the LLM only on iteration 0 of the loop. Subsequent iterations (after tool results) don't include manifests, so the LLM may "forget" available tools.
- **Evidence:**
  - `app/core/agent/session.py` line ~530 — manifest inclusion conditional on iteration index.
- **Implementation:**
  - Include tool manifests in every LLM call within a `process_message()` invocation, not just the first one.
  - Cost impact: minimal — manifests are cached per session and add ~1-2KB per call.
- **DoD:** LLM receives tool manifests on all iterations. Multi-step tool chains work reliably.
- **Verification:** `python -m pytest tests/unit/test_agent_session_loop.py -v`
- **Affected Files:**
  - `app/core/agent/session.py` (modify — remove iteration-0 guard)

### C-4: Budget checkpoint to session store

- **Priority:** P2
- **Why:** Budget is in-memory only. If the process restarts mid-session, budget state is lost and a resumed session could overspend.
- **Evidence:**
  - `app/core/agent/budget.py` — `to_config()` exists but no evidence of periodic writes.
  - `app/core/agent/session_store.py` — `update_session()` persists session state but budget snapshot is only written at session end or on explicit update.
- **Implementation:**
  - After each tool call in `process_message()`, write `budget.to_config()` to `session.budget_config` and call `session_store.update_session(session)`.
  - On session load, reconstruct `AgentBudget` from `budget_config` via `from_config()`.
- **DoD:** Budget survives process restart. Test: consume 50% → checkpoint → reconstruct → remaining = 50%.
- **Verification:** `python -m pytest tests/unit/test_agent_budget.py -v`
- **Affected Files:**
  - `app/core/agent/session.py` (modify — add checkpoint call)
  - `tests/unit/test_agent_budget.py` (modify — add checkpoint round-trip test)

---

## Phase D — Demo Readiness

> **Goal:** After Phases A-C are complete, verify the full demo scenario end-to-end with zero failures.

### D-1: Run full stable demo scenario

- **Priority:** P0
- **Why:** The stable demo (StubProvider, no Docker) is the CI gate. Must pass after Phases A-C.
- **Evidence:**
  - `tests/integration/test_agent_demo_scenario.py` — currently 3 failures (blocked on A-1).
  - Expansion acceptance rubric requires 10-step stable demo.
- **Implementation:**
  - No code changes. Run the demo suite after A-1 through C-4 are complete.
  - If any assertion fails, trace back to the root cause and file follow-up tasks.
- **DoD:** `python -m pytest tests/integration -q --timeout=30` → 0 failures.
- **Verification:** `python -m pytest tests/integration -q --timeout=30`
- **Affected Files:** None (validation only)

### D-2: Run full unit test regression suite

- **Priority:** P0
- **Why:** Validate that Phases A-C introduced no regressions.
- **Implementation:** No code changes. Run `python -m pytest tests/unit -q --tb=no --timeout=60`.
- **DoD:** All unit tests pass. Count >= 1236.
- **Verification:** `python -m pytest tests/unit -q --tb=no --timeout=60`
- **Affected Files:** None (validation only)

### D-3: Update test baseline in TASKS.md header

- **Priority:** P1
- **Why:** The test baseline header must reflect the actual post-fix state.
- **Implementation:** After D-1 and D-2, update the header line to reflect the new pass/fail counts.
- **DoD:** Header test baseline matches actual `pytest -q` output.
- **Affected Files:** `TASKS.md` (modify — 1 line)

---

## Phase E — Discovery & Future Planning

> **Goal:** Research-only tasks that feed the next roadmap. No code changes.

### E-1: Evaluate native function-calling integration for target LLM providers

- **Priority:** P2
- **Why:** C-2 adds a dual parser. This discovery determines which providers should get native function-calling support and what `GenerationResult` changes are needed.
- **Evidence:**
  - `app/core/llm/unified.py` — `UnifiedLLMService` supports Gemini, OpenAI, Stub providers.
  - `app/main.py:226-240` — 3 providers registered: Gemini, OpenAI, Stub.
- **Output:** `docs/LLM_FUNCTION_CALLING_DISCOVERY.md` with provider-by-provider function calling support matrix.
- **DoD:** Discovery report with concrete API contracts for each provider.
- **Affected Files:** `docs/LLM_FUNCTION_CALLING_DISCOVERY.md` (new)

### E-2: Evaluate persistent sandbox state for multi-step tool chains

- **Priority:** P2
- **Why:** Current sandbox is stateless (tmpfs wiped per invocation). Multi-step tool chains that need intermediate state (e.g., clone repo → analyze → generate) require a persistence strategy.
- **Evidence:**
  - `docker-compose.yml` — sandbox has `tmpfs /work:100M,noexec`.
  - Each sandbox invocation starts fresh.
- **Output:** `docs/SANDBOX_PERSISTENCE_DISCOVERY.md` with options analysis (tmpfs carryover, Redis-backed cache, volume mounts).
- **DoD:** Discovery report with recommended approach and security implications.
- **Affected Files:** `docs/SANDBOX_PERSISTENCE_DISCOVERY.md` (new)

### E-3: Audit console_runtime.py app.state coupling for DI migration

- **Priority:** P2
- **Why:** `app/api/console_runtime.py` has 20 references to `request.app.state`. This is not agent-specific but contributes to overall state management debt that will affect agent-console integration.
- **Evidence:**
  - `app/api/console_runtime.py` — 20 `request.app.state` references for db, stores, orchestrator, provider profiles, budget ledger.
- **Output:** `docs/CONSOLE_RUNTIME_DI_DISCOVERY.md` listing every `app.state` reference, its purpose, and DI migration path.
- **DoD:** Discovery report with dependency catalog and migration effort estimate.
- **Affected Files:** `docs/CONSOLE_RUNTIME_DI_DISCOVERY.md` (new)

---

## Task Summary Matrix

| ID | Title | Phase | Priority | Type | Deps |
|----|-------|-------|----------|------|------|
| A-1 | Extract shared InMemoryAgentSessionStore | A | P0 | Fix | — |
| A-2 | Narrow router_registration exception catch | A | P0 | Fix | — |
| A-3 | Guard sandbox JWT secret | A | P0 | Fix | — |
| A-4 | Replace deprecated asyncio.get_event_loop() | A | P1 | Fix | — |
| B-1 | Sandbox worker health check | B | P1 | Hardening | A-2 |
| B-2 | Per-job execution timeout | B | P1 | Hardening | — |
| B-3 | Cache BlockRegistry in worker | B | P2 | Optimization | — |
| C-1 | Implement _is_pre_confirmed() | C | P1 | Fix | — |
| C-2 | Provider-agnostic tool call parser | C | P1 | Enhancement | — |
| C-3 | Persist tool manifests across iterations | C | P2 | Fix | — |
| C-4 | Budget checkpoint to session store | C | P2 | Hardening | — |
| D-1 | Run full stable demo scenario | D | P0 | Validation | A-1 through C-4 |
| D-2 | Run full unit test regression suite | D | P0 | Validation | A-1 through C-4 |
| D-3 | Update test baseline header | D | P1 | Bookkeeping | D-1, D-2 |
| E-1 | LLM function-calling discovery | E | P2 | Discovery | — |
| E-2 | Persistent sandbox state discovery | E | P2 | Discovery | — |
| E-3 | console_runtime DI audit | E | P2 | Discovery | — |

## Execution Order

1. **Slice 1 (Phase A — parallel):** A-1 + A-2 + A-3 + A-4 (all independent, can be done in parallel)
2. **Slice 2 (Phase B):** B-1 → B-2 → B-3 (sequential within sandbox)
3. **Slice 3 (Phase C):** C-1, C-2 (independent); then C-3, C-4 (independent)
4. **Slice 4 (Phase D):** D-1 → D-2 → D-3 (sequential validation)
5. **Slice 5 (Phase E — parallel):** E-1 + E-2 + E-3 (all independent discoveries)

## Quality Gates

1. After each slice: `python -m pytest tests/unit -q --tb=no --timeout=60` → all pass.
2. After Slice 1: `python -m pytest tests/integration -q --timeout=30` → 0 failures.
3. After Slice 4: full baseline updated in header.
4. No new `except Exception: pass` without logging.
5. Discovery reports (Phase E) must cite file:line evidence.
