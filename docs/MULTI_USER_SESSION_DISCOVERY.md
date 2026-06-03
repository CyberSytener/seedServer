# Multi-User Session Discovery Report (P0-23)

> **Task:** P0-23 — Audit session isolation and auth context for multi-user extension
> **Date:** 2026-02-27
> **Branch:** `feature/phase0-followup`
> **Status:** ✅ DONE

---

## Question 1: Session Ownership Check Locations

All files that compare `user_id` to enforce session ownership:

### `app/api/agent_routes.py` — centralized `_ensure_owner` gate

| Location | What it does |
|---|---|
| L165–168 | **Definition** of `_ensure_owner(session, user_id)` — raises HTTP 403 if `session.user_id != user_id` |
| L216 | Called in `send_message` (POST `/sessions/{id}/messages`) |
| L243 | Called in `get_session` (GET `/sessions/{id}`) |
| L291 | Called in `update_persona` (POST `/sessions/{id}/persona`) |
| L324 | Called in `delete_session` (DELETE `/sessions/{id}`) |
| L347 | Called in `get_session_tree` (GET `/sessions/{id}/tree`) |
| L381 | Called in `ingest_context` (POST `/sessions/{id}/context`) |

### `app/api/job_queue.py` — direct `row["user_id"] != ctx.user_id` checks

| Location | What it does |
|---|---|
| L222 | Ownership check on job fetch |
| L299 | Ownership check on job SSE stream |

### `app/api/diagnostics_routes.py` — session ownership logging

| Location | What it does |
|---|---|
| L400 | Calls `get_session_info(db, session_id, user_id)` |
| L411 | Logs `actual_session_owner` on mismatch |
| L515 | Same pattern, second endpoint |

### `app/api/path.py` — per-row ownership checks

| Location | What it does |
|---|---|
| L282 | `row["user_id"] != user_id` on node fetch |
| L449 | `unit["user_id"] != ctx.user_id` on unit |
| L499 | `row["user_id"] != ctx.user_id` on fetch |
| L572 | `node_row["user_id"] != user_id` on node |

### `app/core/agent/session.py` — child session inherits parent's `user_id`

| Location | What it does |
|---|---|
| L227 | `user_id=parent_session.user_id` — child session always inherits parent's owner |

**Key finding:** No ownership check inside `AgentSession` or the core loop. All enforcement is at the API route layer via `_ensure_owner`. The core runtime trusts whatever it receives.

---

## Question 2: How `auth_context` Is Threaded Through the Session Loop

### Entry point — `agent_routes.py`

```
_require_auth(request, scope) → ctx (AuthContext)
```

Auth is resolved by `auth_provider(request, scope)` or fallback to `app.core.authz.require_scope`. The `ctx` is used for:
1. Extract `user_id` via `_effective_user_id(ctx)`
2. Passed into `_make_agent_session(ctx)` → `AgentSession(auth_context=ctx)`

### Into `AgentSession.__init__()` — `session.py` L143

```python
auth_context: Any = None,    # UnifiedAuthContext
...
self.auth_context = auth_context
```

### Downstream propagation

| Where | What happens |
|---|---|
| `spawn_child_session` | `auth_context=self.auth_context` — forwarded unchanged to child |
| `_execute_tool` | auth_context **NOT passed** to `build_action()` or `execute_action()`. Only `session.user_id` is used. |
| Budget checks | auth_context **NOT passed** to `AgentBudget`. Budget loaded from `session.budget_config`. |
| Sandbox dispatch | Only `session_id`, `tool_name`, `tool_input` sent — no auth context. |

**Key finding:** `auth_context` is stored and propagated to children but **never consumed** by tool execution, budget, or sandbox. It's dead weight after the route-layer check. Multi-user needs it threaded into `build_action()`, `execute_action()`, and sandbox dispatch.

---

## Question 3: Whether `agent_sessions` Table Supports Multiple Participants

### DDL — `sqlite.py` L424–441

```sql
CREATE TABLE IF NOT EXISTS agent_sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  persona_id TEXT NOT NULL DEFAULT 'seed',
  persona_overrides TEXT NOT NULL DEFAULT '{}',
  budget_config TEXT NOT NULL DEFAULT '{}',
  tool_scopes TEXT NOT NULL DEFAULT '[]',
  pending_confirmations TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  parent_session_id TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### Data model — `models.py` L222–237

`AgentSessionData` has a single `user_id: str` field. No participants list, no join table.

**Key findings:**
- **No `participants` table exists.** No junction/association table in schema.
- `user_id` is a single `TEXT NOT NULL` with FK to `users(id)` — one owner per session.
- Child sessions inherit the **same** `user_id` from parent.
- `_ensure_owner` means no second user can interact with any session they didn't create.

**Changes needed:**
1. Add `agent_session_participants` table: `(session_id, user_id, role, tool_scopes, joined_at, left_at)`
2. Change `_ensure_owner` to check participants table (owner/editor/viewer roles)
3. Keep `user_id` on `agent_sessions` as "creator" field
4. Update `session_store.list_sessions()` to JOIN through participants

---

## Question 4: How `AgentBudget` Would Work for Shared Sessions

### Budget definition — `budget.py` L20–47

`AgentBudget` is a pure dataclass with limits and consumed counters. **No `user_id` field.** It tracks:
- `max_total_tokens`, `max_total_cost_units`, `max_wall_time_seconds`, `max_tool_calls`
- `consumed_*` counters
- `budget_id`, `_parent`, `child_budget_ids` for hierarchy

### Budget tied to session, not user

Budget serialized to `budget_config` JSON on `agent_sessions` row. Since `user_id` is a single owner, budget is implicitly charged to that owner.

### Parent-child hierarchy

`create_child()` produces capped child budgets. `consume_llm()` / `consume_tool_call()` cascade upward. Session owner always "pays."

### Can multiple users share a budget?

**No — not currently.** No per-user attribution, no split-billing, no per-participant consumption tracking.

### Changes needed for shared-session billing:

1. **Per-user attribution**: Add `user_id` param to `consume_llm()`/`consume_tool_call()`, plus `consumed_by_user: Dict[str, float]` ledger.
2. **Budget policy selection**:
   - **Session owner pays all** (simplest — current behavior, just lift ownership gate)
   - **Each participant has own sub-budget** (use `create_child()` per participant)
   - **Proportional split** (track per-user, bill accordingly)
3. **Enforcement**: `process_message` loads budget from `session.budget_config`. For per-user budgets, load participant's budget/sub-budget instead.
4. **Concurrency**: Existing `asyncio.Lock` serializes concurrent consumption — works for shared budget. Per-user sub-budgets would each need own lock.

---

## Summary

| Question | Current State | Multi-User Gap |
|---|---|---|
| Ownership checks | 7 callsites in `agent_routes.py` via `_ensure_owner` | Need participants-table lookup |
| auth_context | Passed to `AgentSession`, unused by tools/budget | Must thread into `build_action`, sandbox |
| DB schema | Single `user_id TEXT NOT NULL`, no participants table | Need junction table + role column |
| Budget billing | Session-scoped, no user attribution | Need per-user ledger or sub-budget |
