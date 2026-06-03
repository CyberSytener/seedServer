# Phase 7 — Autonomous Agent Sessions — Work Log

**Branch:** `feature/phase7-agent-sessions`
**Started:** 2026-02-27

---

## Baseline

- **Branch created:** `feature/phase7-agent-sessions`
- **Baseline test run:** `python -m pytest tests/unit -q` → **610 passed, 7 skipped** (20.83s)
- **Starting from:** Phase 6 complete

---

## P7-01: Agent scope family in authz ✅

**Status:** DONE

- Modified `app/core/authz.py` — added agent scopes to `ROLE_SCOPES` (user/developer/operator/admin)
- Created `tests/unit/test_authz_agent_scopes.py` — **11 tests passed**

---

## P7-02: AgentSession data model + persistence ✅

**Status:** DONE

- Modified `app/infrastructure/db/sqlite.py` — added `agent_sessions` + `agent_session_messages` tables
- Modified `app/settings.py` — added `agent_session_ttl_seconds` field
- Created `app/core/agent/__init__.py`, `models.py`, `session_store.py`
- Created `tests/unit/test_agent_session_store.py` — **9 tests passed**

---

## P7-03: AgentBudget ✅

**Status:** DONE

- Created `app/core/agent/budget.py` — `AgentBudget` with token, cost, time, tool call limits
- Created `tests/unit/test_agent_budget.py` — **19 tests passed**

---

## P7-04: ToolRegistry ✅

**Status:** DONE

- Created `app/core/agent/tool_registry.py` — `ToolRegistry` + `ToolPermissionConfig` (default-deny, OpenAI manifests, ActionRouter integration)
- Created `tests/unit/test_agent_tool_registry.py` — **20 tests passed**

---

## P7-04a: Confirmation gate ✅

**Status:** DONE

- Added `PendingConfirmation` dataclass to `app/core/agent/models.py`
- Created `tests/unit/test_agent_confirmation_gate.py` — **10 tests passed**
- Fixed `tests/unit/test_pepper_warning.py` (missing `agent_session_ttl_seconds` field)

### Phase 7.0 Verification
`python -m pytest tests/unit -q` → **679 passed, 7 skipped** (20.38s) — zero regressions

---

## P7-05: AgentSession runtime loop ✅

**Status:** DONE

- Added `AgentResponse` dataclass to `app/core/agent/models.py`
- Created `app/core/agent/session.py` — `AgentSession.process_message()` with iterative LLM↔tool loop, budget enforcement, confirmation gate, ActionRouter execution, artifact storage
- Created `tests/unit/test_agent_session_loop.py` — **24 tests passed**

---

## P7-06: Agent HTTP API endpoints ✅

**Status:** DONE

- Created `app/api/agent_routes.py` — `build_agent_router()` factory with 6 endpoints (create, message, get, persona, delete, tools)
- Modified `app/infrastructure/router_registration.py` — registered agent router as optional
- Created `tests/unit/test_agent_routes.py` — **16 tests passed**

---

## P7-07: Agent telemetry + audit trail ✅

**Status:** DONE

- Added `AgentTrace`, `AgentTraceStep` dataclasses to `app/core/agent/models.py`
- Modified `app/core/agent/session.py` — added `audit_emitter` callback, structured trace, tool duration tracking
- Created `tests/unit/test_agent_telemetry.py` — **14 tests passed**

### Final Verification
`python -m pytest tests/unit -q` → **733 passed, 7 skipped** (24.98s) — zero regressions

### New Tests Summary
| Task   | File                                  | Tests |
|--------|---------------------------------------|-------|
| P7-01  | test_authz_agent_scopes.py            | 11    |
| P7-02  | test_agent_session_store.py           | 9     |
| P7-03  | test_agent_budget.py                  | 19    |
| P7-04  | test_agent_tool_registry.py           | 20    |
| P7-04a | test_agent_confirmation_gate.py       | 10    |
| P7-05  | test_agent_session_loop.py            | 24    |
| P7-06  | test_agent_routes.py                  | 16    |
| P7-07  | test_agent_telemetry.py               | 14    |
| **Total** |                                    | **123** |

---

## P7-08: UI context pack ingest endpoint ✅

**Status:** DONE

- Created `app/core/agent/ui_context.py` — `UIContextPack` Pydantic model with `UIComponent`, `UIRoute`, `UIContract` sub-models; validators for framework, max components (200), max payload (100KB); `to_prompt_section()` for LLM
- Modified `app/api/agent_routes.py` — added `POST /v1/agent/sessions/{id}/context` endpoint (scope: `agent:context:read`)
- Modified `app/core/agent/session.py` — `build_prompt()` accepts `ui_context`; `process_message()` extracts latest context message
- Created `tests/unit/test_agent_ui_context.py` — **26 tests passed**

---

## P7-09: CLI context pack generator ✅

**Status:** DONE

- Created `scripts/generate_ui_context_pack.py` — walks directory, extracts components from .tsx/.jsx/.vue/.svelte via regex, outputs UIContextPack JSON
- Tested against `saga-console/src`: 14 components found

---

## P7-10: Per-session persona overrides ✅

**Status:** DONE

- Added `PersonaOverrides` dataclass to `app/core/agent/models.py` (display_name, voice_id, system_prompt_append with 2000 char limit)
- Modified `app/core/agent/session.py` — `_resolve_persona()` applies overlay; `process_message()` populates `persona_meta`
- Modified `app/api/agent_routes.py` — update_persona maps name→display_name, voice→voice_id; SendMessageResponse includes persona_meta
- Created `tests/unit/test_agent_persona.py` — **17 tests passed**

---

## P7-11: Verify/create seed.md persona ✅

**Status:** DONE

- Created `prompts/personas/seed.md` — frontmatter (name: Seed, tags: [agent, autonomous, tool-capable, seed]) + system prompt (capabilities, communication style, constraints)
- Verified: `init_persona_loader('prompts/personas'); get_persona_prompt('seed')` → length 1073

---

## P7-12: Per-tool permission matrix ✅

**Status:** DONE

- Created `app/core/agent/tool_permissions.yaml` — defaults + per-tool configs (inventory_sync: sandbox+confirmation, recipe_generator: read-only, admin_reset: elevated scope)
- Modified `app/core/agent/tool_registry.py` — `ToolPermissionConfig.from_yaml()`, `is_tool_allowed()` checks per-tool elevated scopes via `_scope_matches()` (default scope implicitly granted by tool name presence)
- Created `tests/unit/test_agent_tool_permissions.py` — **18 tests passed**

---

## P7-13: Budget enforcement integration tests ✅

**Status:** DONE

- Created `tests/unit/test_agent_budget_enforcement.py` — **8 tests** covering 3-tool budget scenario, token/cost exhaustion, zero budget, per-tool limits, budget snapshot in trace

---

## P7-14: Sandbox worker container definition ✅

**Status:** DONE

- Modified `docker-compose.yml` — added `agent_sandbox` service (read_only, tmpfs /work:100M, cap_drop ALL, no-new-privileges, separate Redis DB /2) + `agent_sandbox_net` internal network
- Created `app/agent_sandbox_worker.py` — main loop polling Redis, replay protection, sandbox allowlist, token validation, security verification

---

## P7-15: Sandbox RPC protocol via Redis ✅

**Status:** DONE

- Created `app/core/agent/sandbox_dispatcher.py` — `SandboxDispatcher` with `dispatch()` method (rpush→blpop, token issuance, timeout handling)
- Created `tests/unit/test_sandbox_rpc.py` — **10 tests passed**

---

## P7-15a: Scoped JWT for sandbox RPC ✅

**Status:** DONE

- Created `app/core/agent/sandbox_jwt.py` — `issue_sandbox_token()`, `validate_sandbox_token()`, `SandboxTokenError`, separate signing secret
- Created `tests/unit/test_sandbox_jwt_validation.py` — **9 tests** covering round-trip, expired, wrong audience, wrong issuer, rpc_id mismatch, tool_name mismatch, wrong scope, wrong secret

---

## P7-16: Sandbox routing in AgentSession ✅

**Status:** DONE

- Modified `app/core/agent/session.py` — `_execute_tool()` checks `sandbox_required` flag; routes to `SandboxDispatcher.dispatch()` when enabled; rejects with clear error when disabled; handles config contradictions
- Modified `app/settings.py` — added `sandbox_enabled` field (default: False, env: `SEED_SANDBOX_ENABLED`)
- Created `tests/unit/test_sandbox_routing.py` — **11 tests passed**

---

## P7-17: Demo scenario integration test ✅

**Status:** DONE

- Created `tests/integration/test_agent_demo_scenario.py` — **7 tests** covering full demo flow (create→context→message→persona→verify→get session→delete), budget verification, session UUID, context persistence
- Uses StubLLMService for deterministic tool calls; completes in <2 seconds

### Final Verification (P7-08 through P7-17)
`python -m pytest --tb=short -q` → **903 passed, 22 skipped** (92s) — zero regressions

### New Tests Summary (Session 2: P7-08 through P7-17)
| Task    | File                                    | Tests |
|---------|-----------------------------------------|-------|
| P7-08   | test_agent_ui_context.py                | 26    |
| P7-10   | test_agent_persona.py                   | 17    |
| P7-12   | test_agent_tool_permissions.py          | 18    |
| P7-13   | test_agent_budget_enforcement.py        | 8     |
| P7-15   | test_sandbox_rpc.py                     | 10    |
| P7-15a  | test_sandbox_jwt_validation.py          | 9     |
| P7-16   | test_sandbox_routing.py                 | 11    |
| P7-17   | test_agent_demo_scenario.py             | 7     |
| **Total** |                                       | **106** |

### Cumulative Test Count
| Phase      | Tests |
|------------|-------|
| P7-01–P7-07 | 123  |
| P7-08–P7-17 | 106  |
| **Total Phase 7** | **229** |
