# Agent Platform Audit — 2026-02-28

> **Scope:** Evidence-based audit of the agent platform as implemented in code (P0-01 through P0-43).
> **Method:** Source code reads, grep searches, test execution, architecture map cross-reference.
> **Test baseline:** 1236 unit passed / 7 skipped; 61 integration passed / 2 skipped / 3 failed; 559 agent-specific unit passed.
> **Branch:** `feature/phase0-followup`

---

## 1. Executive Summary

The agent platform is structurally complete. All 43 Phase 0 tasks are marked DONE and 559 agent-specific unit tests pass. The architecture follows the design intent: `AgentSession` orchestrates an LLM→tool loop backed by `ActionRouter`, `ToolRegistry` is catalog-only (not execution), budgets are enforced server-side with parent-child hierarchy, and sandbox isolation is implemented via Redis RPC.

**However**, the audit surfaces **8 concrete issues** ranging from broken test fixtures (P1) to deprecated API usage and hardcoded secrets. None are showstoppers for development, but 3 are blockers for any demo or production use.

---

## 2. Subsystem-by-Subsystem Audit

### 2.1 AgentSession — Core Orchestrator
**File:** `app/core/agent/session.py` (1144 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| `asyncio.get_event_loop()` used at lines 936 and 980 | Medium | Deprecated since Python 3.10. Should use `asyncio.get_running_loop()`. In executor calls for sync `ActionRouter.execute_action()` and `SandboxDispatcher.dispatch()`. |
| `_is_pre_confirmed()` always returns `False` (line 854-866) | Medium | The confirmation gate correctly pauses on `requires_confirmation` tools, but the "already confirmed" check is a stub. Users must cancel and re-trigger rather than having pending confirmations matched to incoming confirm messages. The *outer* confirmation resolution at the top of `process_message()` handles explicit confirm/cancel, so this is not a security hole — but it means the LLM loop always re-emits a confirmation request even if the user already confirmed in the same turn. |
| `parse_tool_calls()` uses `<tool_call>` XML regex (line 44-69) | Low | Not native OpenAI/Anthropic function-calling format. Works with StubProvider. Will need adapter when switching to real LLM providers that return `tool_calls` in the API response object rather than XML-tagged text. |
| Tool manifest sent only on iteration 0 (line ~530) | Low | If a multi-turn loop runs >1 iteration, subsequent LLM calls don't include tool manifests. The LLM may "forget" tools. Acceptable for short loops but breaks for complex multi-step tasks. |
| `AgentEventEmitter` base class is a no-op (lines 140-170) | Info | By design — `RedisAgentEventEmitter` in `agent_handler.py` provides the real implementation. Non-WS sessions get silent no-op. Correct pattern. |
| 15 dependency injection parameters in `__init__` | Info | `session_store`, `tool_registry`, `action_router`, `llm_service`, `artifact_store`, `persona_loader`, `auth_context`, `sandbox_dispatcher`, `budget_factory`, `tenant_governance`, `marketplace_service`, `event_emitter`, `sandbox_token_issuer`, `max_iterations`, `max_nesting_depth`. Heavy but functional. |

### 2.2 AgentBudget — Parent-Child Hierarchy
**File:** `app/core/agent/budget.py` (314 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| `asyncio.Lock` for concurrent consume | Good | Lines 280-290: `async_consume_llm()` and `async_consume_tool_call()` acquire lock. Prevents overspend in parallel sub-agent scenarios. |
| Parent cascade is synchronous (line 241-252) | Info | `consume_llm()` and `consume_tool_call()` directly increment parent counters. Safe in single-event-loop context. The async wrappers provide the lock. |
| `split_budget(n)` creates n children, each with `remaining/n` share | Good | Lines 152-185. Each child capped at parent remaining. |
| `per_user_consumption` tracking present | Good | Lines 260-275. Tracks per-user tokens, cost, tool calls. |
| No budget persistence/reload across restarts | Low | Budgets are in-memory. If the process restarts mid-session, budget state is lost. The `to_config()` / `from_config()` methods exist but there's no evidence of periodic checkpoint writes to the session store. |

### 2.3 AgentSessionStore — Persistence Layer
**File:** `app/core/agent/session_store.py` (233 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| Full CRUD + child session queries | Good | `create_session`, `get_session`, `update_session`, `list_child_sessions`, `get_session_tree` (BFS), `cancel_session_tree`. |
| Participant CRUD complete | Good | `add_participant`, `remove_participant`, `get_participant`, `list_participants` — lines 173-233. |
| `get_session_tree` uses BFS (queue-based) | Good | Prevents stack overflow for deep trees. |
| `cancel_session_tree` marks all descendants as cancelled | Good | Recursive via BFS. Returns list of cancelled IDs. |
| Message limit default 200 | Info | `get_messages(limit=200)`. Configurable per call. |

### 2.4 Models
**File:** `app/core/agent/models.py` (421 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| `AgentSessionData.to_row()` returns 13-element tuple | Good | Covers session_id through project_id including parent_session_id, tenant_id, project_id. |
| `from_row()` supports both `sqlite3.Row` and tuple | Good | Backward compatibility with raw tuples and row objects. |
| `PersonaOverrides` dataclass present | Good | `display_name`, `voice_id`, `system_prompt_append`. |
| `SessionParticipant` with composite PK (session_id, user_id) | Good | Role enum: OWNER/EDITOR/VIEWER. |
| `sender_user_id` in `AgentSessionMessage` | Good | Multi-user attribution present. |

### 2.5 ToolRegistry — Catalog Layer
**File:** `app/core/agent/tool_registry.py` (263 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| `is_tool_allowed()` checks session scopes + per-tool scope from YAML | Good | Default-deny: tool must be in session's allowlist AND meet its scope requirement. |
| `list_tools_for_llm()` returns OpenAI function-calling manifests | Good | Only allowlisted tools visible to LLM. |
| `build_action()` creates `Action` objects for `ActionRouter` | Good | Correct bridge between catalog and execution. |
| Only 5 tools configured in `tool_permissions.yaml` | Info | `inventory_sync`, `recipe_generator`, `menu_lookup`, `admin_reset`, `github_fetch`. Production will need more. |

### 2.6 Sandbox Dispatcher + JWT
**Files:** `app/core/agent/sandbox_dispatcher.py` (132 lines), `app/core/agent/sandbox_jwt.py` (133 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| Redis RPC with BLPOP on result key + timeout | Good | `dispatch()` at lines 60-100. rpush to `agent_sandbox_rpc`, BLPOP on `agent_sandbox_rpc_result:{rpc_id}` with configurable timeout. |
| Sandbox JWT with `aud: "seed:sandbox"`, `iss: "seed:api"`, 60s TTL | Good | `issue_sandbox_token()` at sandbox_jwt.py lines 30-60. |
| **Hardcoded dev secret `_DEV_SECRET`** | **High** | `sandbox_jwt.py` line ~20: `_DEV_SECRET = "seed-sandbox-dev-secret-DO-NOT-USE-IN-PRODUCTION"`. Falls back to this when `SEED_SANDBOX_JWT_SECRET` env var is not set. Means sandbox tokens are signed with a known key in default config. |
| No sandbox worker health check / heartbeat | Medium | `agent_sandbox_worker.py` main loop only polls Redis. No liveness probe, no heartbeat publication. If the worker crashes silently, API-side dispatches will just timeout. |

### 2.7 Sandbox Worker
**File:** `app/agent_sandbox_worker.py` (254 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| Secret isolation check on startup | Good | Lines 200-205: Checks for `SEED_OPENAI_API_KEY`, `DATABASE_URL`, `SEED_DB_PATH` in env and aborts if found. |
| Replay protection via in-memory set | Good | `_track_rpc_id()` prevents replayed RPC IDs. |
| Allowlist check before execution | Good | Tool must be in `allowed_in_sandbox` set from tool_permissions.yaml. |
| `BlockRegistry()` instantiated per job | Medium | Line 168: `block_registry = BlockRegistry()` created fresh for each RPC job. Could be cached. Performance concern for high-throughput scenarios. |
| No graceful timeout per job | Low | Worker relies on BLPOP timeout but individual job execution has no watchdog. A hanging block could block the worker indefinitely. |

### 2.8 WebSocket Agent Streaming
**Files:** `app/api/ws/agent_handler.py` (266 lines), `app/api/ws/agent_types.py` (216 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| `RedisAgentEventEmitter` publishes to `agent_session:{id}:events` | Good | Clean pub/sub pattern. |
| `AgentStreamBinding` tracks WS↔agent bindings | Good | Session binding with auth check. |
| 8 message types defined with Pydantic models | Good | `AgentStreamStart`, `AgentPartial`, `AgentToolCallStart`, `AgentToolCallResult`, `AgentConfirmationRequest`, `AgentBudgetUpdate`, `AgentFinal`, `AgentError`. |
| `FileReference` model for IDE navigation | Good | `path`, `start_line`, `end_line`, `description`. |
| `correlation_id` and `request_id` in all messages | Good | IDE protocol compliance. |

### 2.9 Agent Routes — HTTP API
**File:** `app/api/agent_routes.py` (612 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| 12 endpoints via `build_agent_router()` factory | Good | Sessions CRUD, messages, persona, context, repo-context, tree, participants, tools. |
| Auth enforcement on every endpoint | Good | `_require_auth(request, scope)` with per-endpoint scope strings. |
| Session ownership + participant checks | Good | `_ensure_owner()` and `_ensure_participant()` with role-based access. |
| Participant role validation prevents adding second OWNER | Good | Line 475: `if role == ParticipantRole.OWNER: raise HTTPException(400)`. |

### 2.10 Router Registration
**File:** `app/infrastructure/router_registration.py` (212 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| **Agent routes catch `(ImportError, Exception)`** | **High** | Line 207: `except (ImportError, Exception) as e:`. This catches ALL exceptions during agent router setup, not just missing imports. A config error, DB connection failure, or attribute error would be silently logged as a warning and the entire agent API would be missing at runtime. Every other router block in the same file catches only `ImportError`. |

### 2.11 Repo Context + UI Context
**Files:** `app/core/agent/repo_context.py` (206 lines), `app/core/agent/ui_context.py` (150 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| `RepoContextPack`: 200KB limit, 50 files max, 50KB tree max | Good | Size guards prevent memory abuse. |
| `UIContextPack`: 100KB total, 200 components max | Good | Pydantic validators enforce limits. |
| `RepoFileCache` session-level caching | Good | Prevents re-fetching within same session. |

### 2.12 SagaLLMPipelineAdapter
**File:** `app/core/realtime/sagas/llm_adapter.py` (152 lines)

| Finding | Severity | Evidence |
|---------|----------|----------|
| Uses `execute_action()` from `app.core.llm.router` | Info | Bypasses `UnifiedLLMService` and calls the lower-level LLM router directly. This is the saga pathway, not the agent pathway. Agent sessions use `UnifiedLLMService` correctly. |
| Provider chain fallback: `["auto", "openai", "gemini", "stub"]` | Good | Line ~80. Robust fallback. |

### 2.13 console_runtime.py coupling
**File:** `app/api/console_runtime.py`

| Finding | Severity | Evidence |
|---------|----------|----------|
| 20 references to `request.app.state` | Low | Heavy coupling to global app state for db, stores, orchestrator, provider profiles, budget ledger. Not related to agent platform directly but indicates broader state management debt. |

---

## 3. Test Fixture Gap — Root Cause of 3 Integration Failures

**Problem:** 3 tests in `tests/integration/test_agent_demo_scenario.py` fail because `InMemoryStore` (test fixture) does not implement `cancel_session_tree` or `list_child_sessions`.

**Root cause:** The `InMemoryStore` class was written for P0-17 (Phase 0.6 demo test) when the store interface had only basic CRUD. Phase 0.7 (P0-20, P0-22) added `list_child_sessions`, `cancel_session_tree`, `get_session_tree`, and participant methods to the production `AgentSessionStore` — but the integration test fixture was never updated.

**Scope:** 7 separate `InMemoryStore` implementations exist across the test suite:

| File | Has `cancel_session_tree`? | Has `list_child_sessions`? | Has participant methods? |
|------|---------------------------|---------------------------|------------------------|
| `tests/integration/test_agent_demo_scenario.py` | ❌ | ❌ | ❌ |
| `tests/integration/test_agent_github_fetch_demo.py` | ? | ? | ? |
| `tests/integration/test_agent_tenant_demo.py` | ? | ? | ? |
| `tests/integration/test_agent_ws_demo.py` | ? | ? | ? |
| `tests/integration/test_agent_multi_agent_demo.py` | ? | ? | ? |
| `tests/unit/test_sandbox_routing.py` | ? | ? | ? |
| `tests/unit/test_agent_budget_enforcement.py` | ? | ? | ? |

**Recommendation:** Extract a shared `InMemoryAgentSessionStore` to `tests/support/` that mirrors the full production interface. All 7 test files should import from it.

---

## 4. Risk Register

| # | Risk | Severity | Impact | Evidence | Mitigation |
|---|------|----------|--------|----------|------------|
| R-1 | Router registration silently swallows agent startup errors | **High** | Agent API missing at runtime without any error signal | `router_registration.py:207` catches `(ImportError, Exception)` | Narrow to `ImportError` only, matching all other router blocks in the same file |
| R-2 | Hardcoded sandbox JWT dev secret | **High** | Sandbox tokens signed with known key in default config; anyone can forge sandbox RPC requests | `sandbox_jwt.py` `_DEV_SECRET` fallback | Require `SEED_SANDBOX_JWT_SECRET` env var; fail startup if missing when sandbox is enabled |
| R-3 | InMemoryStore fixture out of sync (3 test failures) | **P1** | Integration tests fail; CI red on agent demo path | `test_agent_demo_scenario.py:65-93` missing 5+ methods | Extract shared fixture mirroring production interface |
| R-4 | `asyncio.get_event_loop()` deprecated usage | Medium | `DeprecationWarning` in Python 3.10+; will error in future Python versions | `session.py:936,980` | Replace with `asyncio.get_running_loop()` |
| R-5 | No sandbox worker health check | Medium | Silent worker crash → all sandbox dispatches timeout (30s default) | `agent_sandbox_worker.py` — no heartbeat, no liveness probe | Add Redis heartbeat key (`agent_sandbox:heartbeat`) with TTL; API checks before dispatch |
| R-6 | `_is_pre_confirmed()` always returns False | Medium | LLM loop re-emits confirmation even if user already confirmed in same turn | `session.py:854-866` | Implement actual check against resolved pending list |
| R-7 | `parse_tool_calls` uses XML regex, not native function calling | Low | Works with StubProvider but incompatible with real OpenAI/Anthropic function-calling responses | `session.py:44-69` | Add provider-specific tool call parser; keep XML as fallback |
| R-8 | Budget not checkpointed to session store | Low | Process restart loses in-flight budget state | `budget.py` — `to_config()` exists but no periodic writes | Add budget checkpoint in `update_session()` after each tool call |

---

## 5. Demo Readiness Assessment

### Stable Demo (StubProvider, no Docker)

| Gate | Status | Notes |
|------|--------|-------|
| Session CRUD | ✅ Pass | 12 endpoints registered and tested |
| Tool execution loop | ✅ Pass | 559 agent unit tests green |
| Budget enforcement | ✅ Pass | Tests verify all budget paths |
| Confirmation gate | ✅ Pass | Tool-level and session-level gates work |
| Sub-agent spawning | ✅ Pass | Parent-child hierarchy, scope subset enforcement |
| Parallel sub-agents | ✅ Pass | asyncio.gather with budget lock |
| Multi-user sessions | ✅ Pass | Participant model, role-based access |
| WS streaming types | ✅ Pass | 8 message types with Pydantic models |
| Tenant billing | ✅ Pass | Usage recording, quota gate |
| **Integration demo test** | **❌ Fail** | 3 failures due to InMemoryStore gap (R-3) |

### Wow Demo (Docker + Sandbox)

| Gate | Status | Notes |
|------|--------|-------|
| Sandbox worker container | ✅ Defined | docker-compose.yml has `agent_sandbox` service |
| Redis RPC | ✅ Pass | Dispatch + result round-trip tested |
| Egress proxy | ✅ Defined | `scripts/sandbox_egress_proxy.py` exists |
| **JWT secret management** | **⚠️ Risk** | Hardcoded dev secret (R-2) |
| **Worker health monitoring** | **⚠️ Risk** | No heartbeat (R-5) |

### Blocking Issues for Demo

1. **R-3 (InMemoryStore):** Fix the test fixture — extract shared implementation. This unblocks CI.
2. **R-1 (Router registration):** Narrow the exception catch to `ImportError`. This prevents silent agent API disappearance.
3. **R-2 (JWT secret):** Add startup guard when `SEED_SANDBOX_ENABLED=true`.

---

## 6. Invariant Compliance Check

| Invariant | Status | Notes |
|-----------|--------|-------|
| I-1: No direct core access | ✅ Compliant | Agent uses ToolRegistry → ActionRouter only |
| I-2: Tools are the only surface | ✅ Compliant | ToolRegistry catalog + ActionRouter execution |
| I-3: Hard budgets server-side | ✅ Compliant | AgentBudget with pre_check + consume, asyncio.Lock for parallel |
| I-4: Confirmation gates | ⚠️ Partial | Gate works but `_is_pre_confirmed()` is stub (R-6) |
| I-5: Session isolation | ✅ Compliant | Per-session state, scoped access |
| I-6: Every step traced | ✅ Compliant | Trace appended per tool call + LLM call |
| I-7: Repo ops in sandbox only | ✅ Compliant | `github_fetch` marked `sandbox_required: true` |
| I-8: Sandbox locked down | ⚠️ Partial | Locked down but dev JWT secret fallback (R-2), no health check (R-5) |
| I-9: Persona split | ✅ Compliant | Global prompts immutable, session overrides per-session only |
| I-10: Demo as acceptance test | ⚠️ Partial | 3 integration test failures (R-3) |
| I-11: Sub-agents are policy wrappers | ✅ Compliant | Same ToolRegistry, ActionRouter, budget enforcement path |
| I-12: GitHub fetch sandbox-only | ✅ Compliant | `sandbox_required: true, allowed_in_sandbox: true` |
| I-13: Per-participant scopes | ✅ Compliant | Participant model with role-based tool scopes |
| I-14: WS uses existing gateway | ✅ Compliant | Redis pub/sub channel pattern reused |
| I-15: Tenant billing single layer | ✅ Compliant | `record_usage()` in tenant_governance is sole path |

---

## 7. Files Audited

| File | Lines | Status |
|------|-------|--------|
| `app/core/agent/session.py` | 1144 | Fully read |
| `app/core/agent/budget.py` | 314 | Fully read |
| `app/core/agent/models.py` | 421 | Fully read |
| `app/core/agent/session_store.py` | 233 | Fully read |
| `app/core/agent/tool_registry.py` | 263 | Fully read |
| `app/core/agent/tool_permissions.yaml` | 56 | Fully read |
| `app/core/agent/sandbox_dispatcher.py` | 132 | Fully read |
| `app/core/agent/sandbox_jwt.py` | 133 | Fully read |
| `app/core/agent/repo_context.py` | 206 | Fully read |
| `app/core/agent/ui_context.py` | 150 | Fully read |
| `app/api/agent_routes.py` | 612 | Fully read |
| `app/api/ws/agent_handler.py` | 266 | Fully read |
| `app/api/ws/agent_types.py` | 216 | Fully read |
| `app/agent_sandbox_worker.py` | 254 | Fully read |
| `app/infrastructure/router_registration.py` | 212 | Fully read |
| `app/infrastructure/app_wiring.py` | 251 | First 100 lines |
| `app/core/realtime/sagas/llm_adapter.py` | 152 | Fully read |
| `app/main.py` | — | Grep for provider registration |
| `app/api/console_runtime.py` | — | Grep for app.state coupling |
