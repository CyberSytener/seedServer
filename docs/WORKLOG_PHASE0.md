# Phase 0 — Agent Platform Expansion: Work Log

**Branch:** `feature/phase0-followup`
**Started:** 2026-02-27
**Baseline:** 832 unit passed, 7 unit skipped | 18 integration passed, 2 integration skipped

---

## TASK-A: Apply 6 Recommendations to TASKS.md

**Start:** 2026-02-27
**Status:** DONE

### Plan
1. Read full TASKS.md (1594 lines → 1651 after edits)
2. Apply Rec 1: P0-21 — async lock for parallel budget concurrency
3. Apply Rec 2: P0-24 — per-user + scope-checked confirmation gates
4. Apply Rec 3: P0-28 + P0-29 — GitHub proxy/fetch hardening (redirects, zipbomb, timeouts)
5. Apply Rec 4: Phase 0.10 — Minimal IDE Protocol definition + P0-34 updates
6. Apply Rec 5: P0-37 — idempotent billing with idempotency keys
7. Apply Rec 6: Acceptance rubric — split Stable Demo / Wow Demo
8. Add Plan Delta note summarizing changes

### Changes
- `TASKS.md` — 7 targeted edits (no new tasks created):
  - P0-21: added `asyncio.Lock` implementation note, concurrency test in DoD
  - P0-24: added per-user confirmation gate security notes + negative test in DoD
  - P0-28: added redirect policy, max bytes, zip-bomb defense, timeouts, audit, 3 negative tests
  - P0-29: added redirect/timeout/content-type hardening, 3 negative tests
  - Phase 0.10: inserted Minimal IDE Protocol Definition section (event schema tables)
  - P0-34: added correlation_id, request_id, apply_patch confirmation, integration test in DoD
  - P0-37: added idempotency key requirement + dedup logic + idempotency test
  - Acceptance rubric: split into Stable Demo (stub/CI) and Wow Demo (Docker)
  - Header: updated date to 2026-02-27, branch to `feature/phase0-followup`
  - Added Plan Delta note at end of file

### Verification
- `(Get-Content TASKS.md).Count` → 1665 (was 1594)
- All changes are DoD/Security/Implementation amendments — no new task IDs created

### Result
**DONE** — Plan Delta appended, all 6 recommendations incorporated as minimal edits.

---

## TASK-B: Baseline Test Run

**Start:** 2026-02-27
**Status:** DONE

### Verification
```
python -m pytest tests/unit -q --tb=no
→ 832 passed, 7 skipped in 24.07s

python -m pytest tests/integration -q --tb=no
→ 18 passed, 2 skipped in 33.54s
```

### Result
**DONE** — Baseline established.

---

## P0-18: Discovery — Audit AgentSession for Sub-Agent Extension Points

**Start:** 2026-02-27
**Status:** DONE

### Changes
- Created `docs/MULTI_AGENT_DISCOVERY.md` answering 4 questions:
  1. AgentSession dependencies and extension points
  2. AgentBudget child derivation strategy
  3. ToolRegistry subset views
  4. AgentTrace parent/child linking

### Result
**DONE** — Discovery document created. 832 passed, 7 skipped.

---

## P0-19: Budget Hierarchy — Parent-Child Budgets with Cascade Consumption

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/budget.py` — Added `create_child()` with parent capping, `asyncio.Lock` for concurrency, cascade `consume_llm()`/`consume_tool_call()` to parent
- `tests/unit/test_agent_budget.py` — Updated snapshot test for new fields
- `tests/unit/test_agent_sub_session.py` — 17 initial tests for budget hierarchy

### Result
**DONE** — 850 passed, 7 skipped.

---

## P0-20: Sub-Agent Session Spawning

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/models.py` — Added `parent_session_id` to `AgentSessionData` (to_row/from_row), `parent_session_id`/`parent_trace_id` to `AgentTrace`
- `app/infrastructure/db/sqlite.py` — Added `parent_session_id TEXT` column + index to `agent_sessions`
- `app/core/agent/session_store.py` — Updated INSERT for 11 columns, added `list_child_sessions()`
- `app/core/agent/session.py` — Added `nesting_depth`/`max_nesting_depth` init params, `spawn_child_session()` with scope validation and nesting depth enforcement
- `app/settings.py` — Added `agent_max_nesting_depth` (default 3)
- `tests/unit/test_agent_sub_session.py` — 26 tests total
- `tests/unit/test_pepper_warning.py` — Added new Settings field

### Result
**DONE** — 876 passed, 7 skipped.

---

## P0-21: Parallel Sub-Agent Execution

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/budget.py` — Added `split_budget(n)` method (N equal child budgets)
- `app/core/agent/session.py` — Added `delegate_parallel()` with `asyncio.gather`, partial failure handling, max parallel guard
- `app/settings.py` — Added `agent_max_parallel_children` (default 5)
- `tests/unit/test_agent_parallel_children.py` — 20 tests
- `tests/unit/test_pepper_warning.py` — Added new Settings field

### Result
**DONE** — 896 passed, 7 skipped.

---

## P0-22: Sub-Agent Orchestration API Endpoints

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/session_store.py` — Added `get_session_tree()` (BFS), `cancel_session_tree()` (cascade)
- `app/api/agent_routes.py` — Extended `SessionDetailResponse` (parent_session_id, children), added `SessionTreeResponse`, GET `/sessions/{id}/tree`, cascade cancel in DELETE
- `tests/unit/test_agent_orchestration_api.py` — 14 tests
- `tests/unit/test_agent_routes.py` — Added missing methods to `InMemorySessionStore`

### Result
**DONE** — 910 passed, 7 skipped.

---

## P0-23: Multi-User Discovery

**Start:** 2026-02-27
**Status:** DONE

### Changes
- Created `docs/MULTI_USER_SESSION_DISCOVERY.md` answering 4 questions:
  1. Session isolation mechanisms (user_id ownership check)
  2. Auth context propagation patterns
  3. Message attribution gaps
  4. Participant model requirements

### Result
**DONE** — Discovery document created. 910 passed, 7 skipped.

---

## P0-24: Session Participant Model — Invite, Join, Leave

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/models.py` — Added `ParticipantRole` enum (OWNER/EDITOR/VIEWER), `SessionParticipant` dataclass with `to_row()`/`from_row()`/`to_dict()`
- `app/infrastructure/db/sqlite.py` — Added `agent_session_participants` table with composite PK, indexes, FKs
- `app/core/agent/session_store.py` — Added `add_participant()`, `remove_participant()`, `get_participant()`, `list_participants()` CRUD methods
- `app/api/agent_routes.py` — Added participant endpoints (POST/DELETE/GET), `_ensure_participant()` access helper, viewer send-message guard, updated imports
- `tests/unit/test_agent_session_participants.py` — 28 tests (model, store CRUD, API, access control, multi-user confirmation gate)
- `tests/unit/test_agent_routes.py` — Added participant methods to `InMemorySessionStore`
- `tests/unit/test_agent_orchestration_api.py` — Added participant methods to `InMemorySessionStore`

### Result
**DONE** — 938 passed, 7 skipped.

---

## P0-25: Multi-user Message Attribution

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/models.py` — Added `sender_user_id: Optional[str] = None` to `AgentSessionMessage`, updated `to_row()` (10 elements), `from_row()` with backward-compat (dict + tuple + `sqlite3.Row` via `row.keys()`)
- `app/infrastructure/db/sqlite.py` — Added `sender_user_id TEXT` column to `agent_session_messages`
- `app/core/agent/session_store.py` — Updated INSERT to 10 columns (includes `sender_user_id`)
- `app/core/agent/session.py` — `build_prompt()` shows `[User (sender_id)] content` when sender present; `process_message()` extracts `_sender_uid` from `self.auth_context`
- `app/api/agent_routes.py` — GET session message serialization includes `sender_user_id`
- `tests/unit/test_agent_multi_user_messages.py` — 13 tests (model fields, build_prompt attribution, interleaving)

### Result
**DONE** — 951 passed, 7 skipped.

---

## P0-26: Cost Attribution per Participant

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/budget.py` — Added `per_user_consumption: Dict[str, Dict[str, Any]]` field, `_track_user()` helper, `user_id` kwarg on `consume_llm()`/`consume_tool_call()` and async variants, `per_user_consumption` in `snapshot()` and `from_config()`
- `app/core/agent/session.py` — Passed `user_id=_sender_uid` to `consume_llm` and `_execute_tool`, added `user_id` param to `_execute_tool()` signature
- `tests/unit/test_agent_budget.py` — Added `per_user_consumption` to snapshot keys test
- `tests/unit/test_agent_multi_user_cost.py` — 16 tests (per-user tracking, cascade, snapshot, roundtrip, concurrent)

### Result
**DONE** — 967 passed, 7 skipped.

---

## P0-27: GitHub Fetch Discovery

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `docs/GITHUB_FETCH_DISCOVERY.md` — New file answering 4 discovery questions: egress approach (proxy sidecar), HTTP client (httpx), size limits (512KB default), artifact vs direct (hybrid)

### Result
**DONE** — No code changes, discovery-only.

---

## P0-28: Sandbox Egress Proxy for Allow-listed Domains

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `scripts/sandbox_egress_proxy.py` — New file: async HTTP CONNECT proxy with domain allowlist, rate limiting (sliding window), configurable timeouts, audit logging
- `docker-compose.yml` — Added `sandbox_egress_proxy` service (on `default` + `agent_sandbox_net`), updated `agent_sandbox` with `HTTPS_PROXY`/`HTTP_PROXY` env vars + dependency
- `app/settings.py` — Added `sandbox_egress_proxy_url` and `sandbox_egress_allowlist` fields
- `tests/unit/test_pepper_warning.py` — Added new settings fields to defaults
- `tests/unit/test_sandbox_egress_proxy.py` — 26 tests (domain validation, rate limiting, configuration, settings integration)

### Result
**DONE** — 993 passed, 7 skipped.

---

## P0-29: GitHub Fetch Tool Block

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/dynamic_registry/github_fetch_block.py` — New file: `GitHubFetchBlock(BlockBase)` with URL allowlist validation, strict timeouts, size truncation, content-type validation, redirect policy (allowlisted-only), binary-to-base64 fallback, audit logging. Auto-discovered by dynamic loader.
- `app/core/agent/tool_permissions.yaml` — Added `github_fetch` entry: sandbox_required, allowed_in_sandbox, no confirmation, max 20 calls/session
- `tests/unit/test_github_fetch_block.py` — 43 tests (URL validation, redirect policy, content-type validation, block execute with mocked httpx, truncation, binary, registration, permissions YAML)

### Result
**DONE** — 1036 passed, 7 skipped.

---

## P0-30: GitHub Context Injection into Agent Sessions

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/repo_context.py` — New file: `RepoContextPack` dataclass (repo_url, files, tree, fetched_at), `RepoFile` dataclass, `RepoFileCache` (session-level with size limits), `to_prompt_section()`, validation (200KB limit, 50 files max, 50KB tree max)
- `app/core/agent/session.py` — Added `repo_context: Optional[str]` param to `build_prompt()`, added repo context resolution from history (type=repo context messages), passed to prompt on iteration 0
- `app/api/agent_routes.py` — Added `IngestRepoContextResponse` schema, added POST `/sessions/{id}/repo-context` endpoint (section 10)
- `tests/unit/test_agent_repo_context.py` — 35 tests (RepoFile, RepoContextPack validation/serialization/prompt, RepoFileCache, build_prompt integration, endpoint CRUD)

### Result
**DONE** — 1071 passed, 7 skipped.

## P0-31: Agent WS Streaming Discovery

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `docs/AGENT_WS_STREAMING_DISCOVERY.md` — New discovery document answering 4 questions: (1) gateway supports agent channel via "agent stream binding" pattern on single WS, (2) 8 new `agent.*` message types needed, (3) explicit binding via `agent.stream_start` message + Redis channel, (4) RedisSessionStore needs minimal changes

### Result
**DONE** — Discovery only, no code changes, no test delta.

## P0-32: Agent WebSocket Message Types

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/api/ws/agent_types.py` — New file: `AgentMessageType` enum (8 `agent.*` values), 8 Pydantic models (`AgentStreamStart`, `AgentPartial`, `AgentToolCallStart`, `AgentToolCallResult`, `AgentConfirmationRequest`, `AgentBudgetUpdate`, `AgentFinal`, `AgentError`), `AgentWebSocketMessage` union type, `AGENT_MESSAGE_TYPES` lookup map, `parse_agent_message()` helper
- `tests/unit/test_agent_ws_types.py` — 30 tests (enum values, serialization roundtrips, parse_agent_message, union coverage, interop with existing MessageType)

### Result
**DONE** — 1101 passed, 7 skipped.

## P0-33: Agent Session WebSocket Binding and Streaming Loop

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/session.py` — Added `AgentEventEmitter` class (protocol with `emit_partial`, `emit_tool_call_start`, `emit_tool_call_result`, `emit_budget_update`, `emit_confirmation_request`, `emit_final`, `emit_error`). Added `event_emitter` param to `AgentSession.__init__`. Integrated event emission at 6 strategic points in `process_message`: after LLM budget consume, tool call start, tool call result, confirmation gate, final response, error.
- `app/api/ws/agent_handler.py` — New file: `RedisAgentEventEmitter` (publishes to Redis channel `agent_session:{id}:events`), `AgentStreamBinding` (WS↔agent session tracker), `AgentWebSocketHandler` (handles `agent.stream_start`, subscribes to Redis pub/sub, forwards events to WS client, `create_emitter()` factory).
- `app/api/ws/gateway.py` — Added `agent_handler` param to `WebSocketGateway.__init__` and `create_gateway`. Updated `_client_receive_handler` to delegate `agent.*` typed messages to handler and notify handler on WS disconnect.
- `tests/unit/test_agent_ws_streaming.py` — 28 tests (AgentEventEmitter no-op, RedisAgentEventEmitter pub/sub, AgentStreamBinding CRUD, AgentWebSocketHandler bind/error/cleanup, gateway integration, AgentSession event_emitter, end-to-end emitter→Redis→handler roundtrip).

### Result
**DONE** — 1129 passed, 7 skipped.

## P0-34: IDE-Compatible Agent Session Events

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/api/ws/agent_types.py` — Added `FileReference` model (path, start_line, end_line, description). Added `correlation_id: Optional[str]` and `request_id: Optional[str]` to all 8 message types. Added `file_references: List[FileReference]` to `AgentFinal`, `AgentToolCallResult`, `AgentConfirmationRequest`. Added `diff: Optional[str]` to `AgentConfirmationRequest` for apply_patch gates.
- `tests/unit/test_agent_ide_metadata.py` — 41 tests (FileReference CRUD, correlation/request IDs on all 8 types parametrized, file_references on Final/ToolCallResult/ConfirmationRequest, diff field, apply_patch confirmation gate, backward compatibility)

### Result
**DONE** — 1170 passed, 7 skipped.

## P0-35: Discovery — Tenant Billing Bridge

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `docs/TENANT_BILLING_BRIDGE_DISCOVERY.md` — New discovery document answering 4 questions: (1) record_usage after each LLM/tool call via async helper, (2) check_quota as pre-check before LLM calls with caching, (3) operations `agent_llm` and `agent_tool_call` mapping to governance columns, (4) user→tenant→project mapped via session creation params. Includes architecture diagram and implementation sequence.

### Result
**DONE** — Discovery only, no code changes, no test delta.

## P0-36: Tenant-Aware Agent Session Creation

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/models.py` — Added `tenant_id: Optional[str] = None` and `project_id: Optional[str] = None` to `AgentSessionData`. Updated `to_row()` (11→13 elements) and `from_row()` (backward-compatible for both dict and tuple rows).
- `app/infrastructure/db/sqlite.py` — Added `tenant_id TEXT, project_id TEXT` columns to `agent_sessions` table. Added `idx_agent_sessions_tenant` index.
- `app/core/agent/session_store.py` — Updated `create_session` INSERT SQL from 11 to 13 columns.
- `app/api/agent_routes.py` — Added `tenant_id` and `project_id` to `CreateSessionRequest` and `CreateSessionResponse`. Updated `create_session` endpoint to pass fields through.
- `tests/unit/test_agent_tenant_session.py` — 16 new tests (model field defaults, to_row/from_row with tenant data, backward compat, DB schema columns/index, API request/response models, route handler tenant propagation).
- `tests/unit/test_agent_sub_session.py` — Fixed `test_to_row_includes_parent` and `test_to_row_none_parent` for new 13-element tuple (parent_session_id now at index -3).

### Result
**DONE** — 1186 passed, 7 skipped (+16 new tests).

## P0-37: Real-Time Tenant Usage Recording

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/services/tenant_governance.py` — Added `idempotency_key: Optional[str]` to `record_usage()`. Added in-memory `_idempotency_keys` dict with TTL (1 hour). Added `_prune_expired_idempotency_keys()` helper. Duplicate keys return early with `deduplicated: True`.
- `app/core/agent/session.py` — Added `tenant_governance` param to `AgentSession.__init__`. Added `_record_tenant_usage_fire_and_forget()` helper (fire-and-forget, error-logged, skips when no tenant_id or no governance). Wired after `budget.consume_llm()` in `process_message()` with idempotency key `{session_id}:llm:{iteration}`. Wired after `budget.consume_tool_call()` in `_execute_tool()` with key `{session_id}:tool:{tool_name}:{monotonic_ms}`.
- `tests/unit/test_agent_tenant_usage.py` — 20 new tests (recording helper: LLM usage, tool usage, skip no-tenant, skip no-governance, error resilience, fallback actor, enforce_quotas=False, multiple calls, empty tenant; idempotency: first call, duplicate dedup, different keys, no-key, TTL expiry; AgentSession param; integration: call sites, key formats).

### Result
**DONE** — 1206 passed, 7 skipped (+20 new tests).

## P0-38: Quota Enforcement as Budget Gate

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/agent/session.py` — Added tenant quota gate before `budget.pre_check()` in `process_message()` loop. Quota is checked once via `tenant_governance.check_quota()`, result cached for the loop duration (`_tenant_quota_cache`). If not allowed → `stopped_reason="tenant_quota_exceeded"` with user-friendly message. Governance error → fallback to allow. Sessions without `tenant_id` or without `tenant_governance` skip the check. Updated error emit to also trigger on `tenant_quota_exceeded`.
- `tests/unit/test_agent_tenant_quota_gate.py` — 13 new tests (code structure: quota before budget pre_check, cache variable, error emit; behaviour: quota exceeded stops agent, quota OK proceeds, no tenant skips, no governance skips, governance error fallback, cache across iterations, correct params; response shape: text mentions quota, stopped_reason, no tool calls).

### Result
**DONE** — 1219 passed, 7 skipped (+13 new tests).

## P0-39: Marketplace Settlement Integration

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `app/core/blocks.py` — Added `listing_id: Optional[str] = None` to `BlockMetadata` dataclass. Updated `BlockRegistry.register()` to accept and pass through `listing_id`.
- `app/core/agent/session.py` — Added `marketplace_service` param to `AgentSession.__init__`. Added `_record_marketplace_usage()` helper: looks up `listing_id` from BlockMetadata, if present calls `marketplace_service.record_usage_event()`. Wired after audit emit in `_execute_tool()`. Fire-and-forget with error logging.
- `tests/unit/test_agent_marketplace_usage.py` — 17 new tests (BlockMetadata listing_id: default/explicit/frozen; BlockRegistry register with/without listing_id; marketplace recording: marketplace tool recorded, non-marketplace skipped, no service skipped, error resilience, user_id fallback, tenant_id metadata, unknown tool safety; integration: call site exists, init param; AgentSession param default/custom).

### Result
**DONE** — 1236 passed, 7 skipped (+17 new tests).

## P0-40: Multi-Agent Orchestration Demo

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `tests/integration/test_agent_multi_agent_demo.py` — 10 new integration tests: create parent session, spawn single child, parallel delegation (3 children), budget aggregation (parent + children), session tree structure (parent→children), scope escalation denied, trace linkage (parent_session_id), nesting depth limit (max_nesting_depth=1), parallel timing simulation, max parallel exceeded.

### Result
**DONE** — 10 integration tests pass.

## P0-41: GitHub Fetch + Repo Context Demo

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `tests/integration/test_agent_github_fetch_demo.py` — 11 new integration tests: session with github_fetch scope, agent calls github_fetch (sandbox dispatched), response references fetched content, tool result in message history, trace includes github_fetch step, sandbox routing verified (dispatch called with correct args), budget consumed on tool call, URL allowlist hosts defined, accepts github.com URLs, rejects non-github domains, rejects http scheme.

### Result
**DONE** — 11 integration tests pass.

## P0-42: Live WS Streaming Demo

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `tests/integration/test_agent_ws_demo.py` — 14 new integration tests:
  - **TestWSStreamingDemo** (7): budget_update after LLM, tool_call_start event, tool_call_result event, final event with response, event ordering (budget→tool_start→tool_result→final), all events have session_id, no events on missing session.
  - **TestWSEventTypes** (2): all core event types present, simple response emits budget+final only.
  - **TestWSAuthEnforcement** (3): gateway requires JWT handler, gateway delegates agent messages, agent handler has async handle_agent_message.
  - **TestRedisEmitterContract** (2): emitter publishes to correct Redis channel, each emission gets unique message_id.

### Result
**DONE** — 14 integration tests pass.

## P0-43: Multi-Tenant Billing Demo

**Start:** 2026-02-27
**Status:** DONE

### Changes
- `tests/integration/test_agent_tenant_demo.py` — 11 new integration tests using real `TenantGovernanceService` with SQLite:
  - **TestTenantBillingDemo** (6): create tenant+project, set quota, agent session with tenant records usage, export_usage shows metrics, quota enforcement (tenant_quota_exceeded), audit trail (tenant.upsert, project.upsert, role.grant).
  - **TestTenantUsageAttribution** (3): LLM cost recorded, tool call quantity recorded, no usage without tenant_id.
  - **TestTenantQuotaMetrics** (2): check_quota returns allowed, quota blocked after exceeding limit.

### Result
**DONE** — 11 integration tests pass.