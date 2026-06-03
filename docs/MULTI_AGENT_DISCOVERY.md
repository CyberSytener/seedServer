# Multi-Agent Discovery Report (P0-18)

**Date:** 2026-02-27
**Author:** Automated discovery (Codex)
**Purpose:** Audit current `AgentSession` for sub-agent extension points before implementing P0-19 through P0-22.

---

## Question 1: Can `AgentSession` be instantiated with a parent session reference?

**Finding: NO — not currently supported.**

- `app/core/agent/session.py:128` — `AgentSession.__init__()` accepts:
  - `session_store: AgentSessionStore`
  - `tool_registry: ToolRegistry`
  - `action_router: Any`
  - `llm_service: Any`
  - `artifact_store: Any`
  - `persona_loader: Any`
  - `auth_context: Any`
  - `audit_emitter: Optional[Callable]`
  - `sandbox_dispatcher: Any`
  - `sandbox_enabled: bool`
- There is **no** `parent_session_id`, `parent_session`, or `parent_budget` parameter.
- `app/core/agent/models.py:243` — `AgentSessionData` has `session_id`, `user_id`, `persona_id`, `persona_overrides`, `budget_config`, `tool_scopes`, `pending_confirmations`, `status`, `created_at`, `updated_at`. **No `parent_session_id` field.**
- `app/core/agent/session_store.py:35` — `create_session()` SQL INSERT uses 10 columns matching `AgentSessionData.to_row()`. No `parent_session_id` column.
- `app/infrastructure/db/sqlite.py` — `agent_sessions` table DDL has 10 columns. No `parent_session_id`.

**Required changes for P0-20:**
1. Add `parent_session_id: Optional[str]` to `AgentSessionData` (default `None`).
2. Add `parent_session_id` column to `agent_sessions` table DDL.
3. Update `to_row()` / `from_row()` to include the new column.
4. Update `create_session()` INSERT to include the column.
5. Add `parent_budget: Optional[AgentBudget]` parameter to `AgentSession.__init__()` in `session.py` for budget linkage.
6. Add `spawn_child_session()` method to `AgentSession` in `session.py`.

---

## Question 2: Can `AgentBudget` be derived from a parent budget (shared ceiling)?

**Finding: NO — standalone budget, no parent link.**

- `app/core/agent/budget.py:15` — `AgentBudget` fields:
  - `max_total_tokens: Optional[int] = 10_000`
  - `max_total_cost_units: Optional[float] = 20.0`
  - `max_wall_time_seconds: Optional[float] = 120.0`
  - `max_tool_calls: int = 20`
  - `per_tool_limits: Dict[str, int]`
  - `consumed_*` counters
  - `started_at: float`
- There is **no** `parent_budget`, `parent_budget_id`, `child_budgets`, or `create_child()` method.
- `budget.py:49` — `from_config(config)` creates a standalone budget from a dict. No parent reference.
- `budget.py:90` — `consume_llm(tokens, cost_units)` and `consume_tool_call(tool_name)` are plain counter increments. No parent cascade.
- `budget.py:110` — `snapshot()` returns flat dict with no parent reference.

**Required changes for P0-19:**
1. Add `_parent: Optional[AgentBudget] = None` internal reference.
2. Add `create_child(max_tool_calls, max_tokens, max_cost) -> AgentBudget`:
   - Caps child limits at `min(requested, parent.remaining)`.
   - Sets `_parent = self` on the child.
3. Override `consume_llm()` and `consume_tool_call()` in child to also call `parent.consume*()`.
4. Add `asyncio.Lock` for concurrency safety when parallel children consume (per Plan Delta Rec 1).
5. Add `child_budgets: List[str]` tracking field for audit.

---

## Question 3: Can `ToolRegistry` produce a strict subset view for a child?

**Finding: YES — `list_tools_for_llm(session_scopes)` already filters by allowlist.**

- `app/core/agent/tool_registry.py:125` — `is_tool_allowed(name, session_scopes)`:
  - Checks `name in session_scopes` (or `"*"` wildcard).
  - Checks block exists in `BlockRegistry`.
  - Checks per-tool scope requirement.
- `app/core/agent/tool_registry.py:155` — `list_tools_for_llm(session_scopes)`:
  - Iterates all blocks, filters via `is_tool_allowed()`.
  - Returns only manifests for allowed tools.
- This means: passing a **subset** of `session_scopes` to a child session automatically restricts which tools the child LLM can see.

**No changes needed for ToolRegistry itself.** The subset enforcement happens at session creation time in `session.py`:
- Parent has `tool_scopes = ["recipe_generator", "inventory_sync", "github_fetch"]`
- Child created with `tool_scopes = ["recipe_generator"]` → child LLM sees only 1 tool.
- **Validation required:** `spawn_child_session()` in `session.py` must verify `child_scopes ⊆ parent_scopes`.

---

## Question 4: Can the trace include sub-session references?

**Finding: NO — trace has `session_id` but no `parent_trace_id` or `parent_session_id`.**

- `app/core/agent/models.py:82` — `AgentTrace` fields:
  - `trace_id: str` (UUID)
  - `session_id: str`
  - `user_id: str`
  - `started_at`, `ended_at`
  - `steps: List[AgentTraceStep]`
  - `budget_snapshot: Dict`
- There is **no** `parent_trace_id`, `parent_session_id`, or `child_trace_ids` field.
- `app/core/agent/models.py:52` — `AgentTraceStep` has `step_type` with values: `llm_call`, `tool_executed`, `tool_denied`, `confirmation_required`, `confirmation_cancelled`. No `child_session_spawned` step type.

**Required changes for P0-20:**
1. Add `parent_session_id: Optional[str] = None` to `AgentTrace`.
2. Add `parent_trace_id: Optional[str] = None` to `AgentTrace`.
3. Add step type `"child_session_spawned"` to `AgentTraceStep.step_type` vocabulary.
4. Add `child_session_id: Optional[str]` to `AgentTraceStep.extra` when spawning children.
5. Update `to_dict()` to include new fields.

---

## Summary of Extension Points

| Component | Ready for Sub-Agents? | Changes Needed |
|-----------|----------------------|----------------|
| `AgentSession.__init__()` | No | Add `parent_budget` param |
| `AgentSessionData` | No | Add `parent_session_id` field + DB column |
| `AgentBudget` | No | Add `create_child()`, parent link, `asyncio.Lock` |
| `ToolRegistry` | **Yes** | No changes (subset filtering already works) |
| `AgentTrace` | No | Add `parent_session_id`, `parent_trace_id` |
| `AgentTraceStep` | No | Add `child_session_spawned` step type |
| `AgentSessionStore` | No | Update SQL for `parent_session_id` column |

**Recommendation:** Implement P0-19 (budget hierarchy) first, then P0-20 (session spawning), as the budget hierarchy is the foundation for all sub-agent work.
