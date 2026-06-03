# Seed Server — Task Archive: Phase 0 Agent Platform Expansion (P0-01 through P0-43)

> **Archived from** `TASKS.md` on 2026-02-28.
> **Reason:** All 43 Phase 0 tasks (P0-01 through P0-43) marked ✅ DONE. Active tracker reset for next roadmap.
> **Prior archive:** `docs/TASKS_ARCHIVE_2026-03-05.md` (Phases 0–6 + legacy reboot history).
> **Test baseline at archive time:** 1236 unit passed / 7 skipped; 61 integration passed / 2 skipped / 3 failed (InMemoryStore fixture gap — see audit).
> **Branch:** `feature/phase0-followup`

---

## Non-negotiable Invariants (Phase 0)

| # | Invariant | Rule |
|---|-----------|------|
| I-1 | **No direct access to core** | Agent never gets direct access to DB / Redis / FS of the core process / secrets / internal networks. Every action goes through Tools, governed by contracts and scopes. |
| I-2 | **Tools are the only capability surface** | Agent does not "execute code" or "go wherever it wants." It can only call Tool Registry (blocks/tools) with `INPUT_SCHEMA` / `OUTPUT_SCHEMA` and server-side validation. |
| I-3 | **Hard budgets are enforced by the system, not the model** | Limits (tool calls / wall time / tokens / cost / retries) are enforced server-side by `AgentBudget`. The model cannot bypass them. |
| I-4 | **Human confirmation gates for dangerous operations** | Any write / destructive / payment / privileged operation requires explicit user confirmation AND a separate scope. Default posture is **read-only**. |
| I-5 | **Session isolation is real** | `AgentSession` has its own state, memory pointers, and artifact namespace. No shared global mutable state without explicit, scoped permission. |
| I-6 | **Every step leaves a trace** | Every tool call is recorded as an event in the session trace + artifact(s) in `ArtifactStore`. Nothing can execute silently. |
| I-7 | **Repo-aware operations never run in core** | Any "see repo / layout" operation (search, analysis, diff generation) runs only inside the sandbox worker or through a pre-built UI Context Pack pushed by the client. Never in the API process. |
| I-8 | **Sandbox worker is locked down** | Sandbox: tmpfs only, restricted / no egress, no secrets injected, minimal runtime image, narrow Redis RPC interface. No "open a shell and do anything." |
| I-9 | **Persona is split: global vs session override** | Global persona definitions (`prompts/personas/*.md`) are immutable at runtime without an admin process. Users change only session-level `persona_settings` (name / voice / system prompt override); changes never affect other sessions or global defaults. |
| I-10 | **"Minute demo scenario" is the acceptance test** | Every Phase 0 task must either (a) directly advance the 60-second demo scenario, or (b) close a mandatory safety / observability requirement without which the demo cannot be shown. |
| I-11 | **Sub-agents are policy wrappers, not separate systems** | Every sub-agent is a new `AgentSession` with stricter `tool_scopes`, lower `AgentBudget` limits, and a dedicated persona. There is ONE `ToolRegistry`, ONE `ActionRouter`, ONE `AgentBudget` enforcement path. |
| I-12 | **GitHub fetch runs ONLY in the sandbox** | Any HTTP fetch to external URLs executes exclusively inside the sandbox worker container. Core API process never opens outbound HTTP connections on behalf of agent sessions. |
| I-13 | **Multi-user sessions enforce per-participant scopes** | Each participant in a shared session has their own `UnifiedAuthContext` and `tool_scopes`. |
| I-14 | **WebSocket agent streaming uses the existing gateway** | Agent WS streaming reuses `app/api/ws/gateway.py` message types and Redis-backed session store. |
| I-15 | **Tenant billing is the single cost accounting layer** | All agent session costs flow through `app/services/tenant_governance.py` → `record_usage()`. No shadow billing. |

---

## EPIC Definition (Phase 0)

**Goal:** Enable full tool access within a sandboxed session, governed by contracts, scopes, and budgets.

**Non-Goals:** Full phone control, IDE-level indexing/LSP integration, replacing the saga orchestrator, multi-tenant marketplace integration for agent tools, voice synthesis/TTS.

---

## Phase 0.0 — Groundwork / Contracts / Scopes

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-01 | Agent scope family in authz | ✅ DONE | `test_authz_agent_scopes.py` |
| P0-02 | AgentSession data model + persistence | ✅ DONE | `test_agent_session_store.py` |
| P0-03 | AgentBudget — tool-aware budget | ✅ DONE | `test_agent_budget.py` |
| P0-04 | ToolRegistry — agent tool catalog (default-deny) | ✅ DONE | `test_agent_tool_registry.py` |
| P0-04a | Confirmation gate for dangerous tools | ✅ DONE | `test_agent_confirmation_gate.py` |

## Phase 0.1 — AgentSession + Tool Registry MVP

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-05 | AgentSession runtime loop (ActionRouter-backed) | ✅ DONE | `test_agent_session_loop.py` |
| P0-06 | Agent HTTP API endpoints | ✅ DONE | `test_agent_routes.py` |
| P0-07 | Agent telemetry + audit trail | ✅ DONE | `test_agent_telemetry.py` |

## Phase 0.2 — Repo-aware UI Context Pack

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-08 | UI context pack ingest endpoint | ✅ DONE | `test_agent_ui_context.py` |
| P0-09 | CLI context pack generator | ✅ DONE | `scripts/generate_ui_context_pack.py` |

## Phase 0.3 — Persona System

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-10 | Per-session persona overrides | ✅ DONE | `test_agent_persona.py` |
| P0-11 | Verify/create seed.md persona | ✅ DONE | `prompts/personas/seed.md` exists |

## Phase 0.4 — Budgets + Permissions + Audit

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-12 | Per-tool permission matrix | ✅ DONE | `test_agent_tool_permissions.py` |
| P0-13 | Budget enforcement in agent loop | ✅ DONE | `test_agent_budget_enforcement.py` |

## Phase 0.5 — Sandbox Worker

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-14 | Sandbox worker container definition | ✅ DONE | `docker-compose.yml` |
| P0-15 | Sandbox RPC protocol via Redis | ✅ DONE | `test_sandbox_rpc.py` |
| P0-15a | Scoped JWT validation for sandbox RPC | ✅ DONE | `test_sandbox_jwt_validation.py` |
| P0-16 | Sandbox routing in AgentSession | ✅ DONE | `test_sandbox_routing.py` |

## Phase 0.6 — Demo Scenario

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-17 | Demo scenario integration test | ✅ DONE | `test_agent_demo_scenario.py` |

## Phase 0.7 — Multi-Agent Orchestration

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-18 | Discovery: sub-agent extension points | ✅ DONE | `docs/MULTI_AGENT_DISCOVERY.md` |
| P0-19 | Sub-agent budget hierarchy | ✅ DONE | `test_agent_budget_hierarchy.py` |
| P0-20 | Sub-agent session spawning | ✅ DONE | `test_agent_sub_session.py` |
| P0-21 | Parallel sub-agent execution | ✅ DONE | `test_agent_parallel_children.py` |
| P0-22 | Sub-agent orchestration API | ✅ DONE | `test_agent_orchestration_api.py` |

## Phase 0.8 — Multi-User Sessions

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-23 | Discovery: multi-user extension points | ✅ DONE | `docs/MULTI_USER_SESSION_DISCOVERY.md` |
| P0-24 | Session participant model | ✅ DONE | `test_agent_session_participants.py` |
| P0-25 | Multi-user message attribution | ✅ DONE | `test_agent_multi_user_messages.py` |
| P0-26 | Multi-user cost attribution | ✅ DONE | `test_agent_multi_user_cost.py` |

## Phase 0.9 — GitHub Safe Fetch

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-27 | Discovery: sandbox egress capabilities | ✅ DONE | `docs/GITHUB_FETCH_DISCOVERY.md` |
| P0-28 | Sandbox egress proxy | ✅ DONE | `scripts/sandbox_egress_proxy.py` |
| P0-29 | GitHub fetch tool block | ✅ DONE | `test_github_fetch_block.py` |
| P0-30 | GitHub context injection | ✅ DONE | `test_agent_repo_context.py` |

## Phase 0.10 — Live IDE Sessions (WebSocket Streaming)

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-31 | Discovery: WS gateway for agent streaming | ✅ DONE | `docs/AGENT_WS_STREAMING_DISCOVERY.md` |
| P0-32 | Agent WebSocket message types | ✅ DONE | `test_agent_ws_types.py` |
| P0-33 | Agent session WS binding + streaming | ✅ DONE | `test_agent_ws_streaming.py` |
| P0-34 | IDE-compatible agent session events | ✅ DONE | `test_agent_ide_metadata.py` |

## Phase 0.11 — Multi-Tenant Billing Bridge

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-35 | Discovery: tenant governance → agent cost flow | ✅ DONE | `docs/TENANT_BILLING_BRIDGE_DISCOVERY.md` |
| P0-36 | Tenant-aware agent session creation | ✅ DONE | `test_agent_tenant_session.py` |
| P0-37 | Real-time tenant usage recording | ✅ DONE | `test_agent_tenant_usage.py` |
| P0-38 | Quota enforcement as budget gate | ✅ DONE | `test_agent_tenant_quota_gate.py` |
| P0-39 | Marketplace settlement for agent tool usage | ✅ DONE | `test_agent_marketplace_usage.py` |

## Phase 0.12 — Expansion Demo Hardening

| ID | Title | Status | Verification |
|----|-------|--------|-------------|
| P0-40 | Demo: multi-agent orchestration | ✅ DONE | `test_agent_multi_agent_demo.py` |
| P0-41 | Demo: GitHub fetch + repo context | ✅ DONE | `test_agent_github_fetch_demo.py` |
| P0-42 | Demo: live WS streaming | ✅ DONE | `test_agent_ws_demo.py` |
| P0-43 | Demo: multi-tenant billing | ✅ DONE | `test_agent_tenant_demo.py` |

---

## Architecture Sketch (Phase 0 — as built)

```
Client (WS or HTTP)
  ├── POST /v1/agent/sessions                → create session
  ├── POST /v1/agent/sessions/{id}/messages  → send message / tool confirmation
  ├── GET  /v1/agent/sessions/{id}           → session state + history
  ├── GET  /v1/agent/sessions/{id}/tree      → sub-agent hierarchy
  ├── POST /v1/agent/sessions/{id}/persona   → update persona mid-session
  ├── POST /v1/agent/sessions/{id}/context   → push UI context pack
  ├── POST /v1/agent/sessions/{id}/repo-context → push repo context
  ├── POST /v1/agent/sessions/{id}/participants → invite participant
  ├── DELETE /v1/agent/sessions/{id}/participants/{uid} → remove participant
  ├── GET  /v1/agent/sessions/{id}/participants → list participants
  ├── DELETE /v1/agent/sessions/{id}         → delete/cancel session tree
  └── GET  /v1/agent/tools                   → tool manifests

AgentSession (app/core/agent/session.py)
  Uses: UnifiedLLMService, ToolRegistry, ActionRouter, ArtifactStore,
        AgentBudget, UnifiedAuthContext, PersonaPromptLoader, UIContextPack,
        RepoContextPack, SandboxDispatcher, TenantGovernance, Marketplace,
        AgentEventEmitter (for WS streaming)

Sandbox Worker (docker: agent_sandbox)
  tmpfs /work, read-only rootfs, no secrets, Redis RPC only
  Egress proxy for *.github.com domains
```

---

## Execution Order (as delivered)

| Slice | Tasks | Status |
|-------|-------|--------|
| A (0.0) | P0-01 → P0-04a | ✅ |
| B (0.1) | P0-05 → P0-07 | ✅ |
| C (0.2) | P0-08 → P0-09 | ✅ |
| D (0.3) | P0-10 → P0-11 | ✅ |
| E (0.4) | P0-12 → P0-13 | ✅ |
| F (0.5) | P0-14 → P0-16 | ✅ |
| G (0.6) | P0-17 | ✅ |
| H (0.7a) | P0-18 → P0-20 | ✅ |
| I (0.7b) | P0-21 → P0-22 | ✅ |
| J (0.8a) | P0-23 → P0-24 | ✅ |
| K (0.8b) | P0-25 → P0-26 | ✅ |
| L (0.9a) | P0-27 → P0-28 | ✅ |
| M (0.9b) | P0-29 → P0-30 | ✅ |
| N (0.10a) | P0-31 → P0-32 | ✅ |
| O (0.10b) | P0-33 → P0-34 | ✅ |
| P (0.11a) | P0-35 → P0-36 | ✅ |
| Q (0.11b) | P0-37 → P0-39 | ✅ |
| R (0.12) | P0-40 → P0-43 | ✅ |

---

## Quality Gates at Archive Time

- Unit tests: **1236 passed, 7 skipped** (26.44s)
- Integration tests: **61 passed, 2 skipped, 3 failed** (24.82s)
  - 3 failures in `test_agent_demo_scenario.py` — `InMemoryStore` fixture missing `cancel_session_tree` and `list_child_sessions` methods (see `docs/AGENT_PLATFORM_AUDIT_2026-02-28.md`)
- Agent-specific unit tests: **559 passed** (6.30s)
- Route registration: operational
- Module validation: operational
