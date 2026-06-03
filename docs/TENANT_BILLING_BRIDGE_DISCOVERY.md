# Tenant Billing Bridge Discovery (P0-35)

**Date:** 2026-02-27
**Status:** Complete

---

## Question 1: Where should `record_usage()` be called?

### Recommendation: After each consumption event, in the agent loop

There are **two** integration points in `app/core/agent/session.py`:

| Point | Location | Data Available |
|---|---|---|
| **After LLM call** | After `budget.consume_llm()` (≈ line 538) | `gen_result.tokens_in`, `gen_result.tokens_out`, `gen_result.cost_usd`, `session_id`, `_sender_uid` |
| **After tool call** | Inside `_execute_tool()` after `budget.consume_tool_call()` (≈ line 842) | `tool_name`, `session.user_id`, `session.session_id`, `duration_ms`, `status` |

**Architecture:** Add a `_record_tenant_usage()` async helper on `AgentSession` that:
1. Checks if `session.tenant_id` is set (skip if not — personal/non-tenant sessions)
2. Calls `tenant_governance.record_usage()` fire-and-forget (wrapped in `asyncio.create_task` or `try/except`)
3. Never blocks the agent loop on failure

**NOT at session end** — that would lose granularity and risk data loss if the session crashes mid-loop.

---

## Question 2: Should `check_quota()` be a pre-check?

### Recommendation: Yes, as an optional pre-check before each LLM call

| When | What | Why |
|---|---|---|
| Before `budget.pre_check()` | `check_quota(tenant_id, operation="agent_llm", cost_usd=estimated_cost)` | Prevents expensive LLM calls when tenant quota is exhausted |
| Before first tool call in a batch | `check_quota(tenant_id, operation="agent_tool_call")` | Prevents tool execution when tool-call quota is exhausted |

**Caching:** Cache the quota result for the duration of one `process_message()` call (one variable, refreshed if a tool call changes the balance significantly). This avoids N+1 quota checks for N tool calls.

**Signature mapping:** `check_quota()` uses `operation` (not `metric`), and accepts `quantity`, `cost_usd`, `credits`. For agent sessions:
- `operation="agent_llm"` with `cost_usd=estimated_cost`
- `operation="agent_tool_call"` with `quantity=1`

If `check_quota()` returns `allowed=False`, the agent stops with `stopped_reason="tenant_quota_exceeded"` — same UX as budget exhaustion.

---

## Question 3: Which `metric` values (operations) to use?

### Recommendation: Three operations, mapping to existing governance columns

| Operation | Governance Column | Source |
|---|---|---|
| `agent_llm` | `cost_usd` column via `cost_usd=gen_result.cost_usd` | After each LLM call |
| `agent_llm` | `quantity` column via `quantity=tokens_in+tokens_out` | Same call, tokens as quantity |
| `agent_tool_call` | `quantity` column via `quantity=1` | After each tool execution |

The governance layer's `record_usage()` already supports `quantity`, `cost_usd`, and `credits` as separate columns — no need for custom metric names beyond the `operation` string.

**Note:** `record_usage()` calls `check_quota()` internally when `enforce_quotas=True` (default). So recording also enforces — but by that time the cost has already been incurred. Pre-check is still valuable to prevent the next call.

---

## Question 4: How to map `user_id` → `tenant_id` → `project_id`?

### Current state:
- `AgentSessionData` has `user_id` but NO `tenant_id` or `project_id`
- `tenant_governance.record_usage()` requires `tenant_id` and `actor_id` (the user)
- `project_id` is optional (scopes quotas to a project within the tenant)

### Recommended mapping:

```
User creates session via POST /v1/agent/sessions
  → Body includes optional `tenant_id` and `project_id`
  → Server validates: is user a member of tenant? (via tenant_governance)
  → AgentSessionData stores tenant_id, project_id
  → During agent loop:
      record_usage(
          tenant_id=session.tenant_id,
          project_id=session.project_id,
          operation="agent_llm",
          actor_id=session.user_id,
          cost_usd=gen_result.cost_usd,
          quantity=tokens,
      )
```

**If no tenant_id:** Session runs without billing (personal/free-tier). `record_usage()` is skipped entirely.

**If tenant_id but no project_id:** Usage recorded at tenant level (project_id=None is valid in governance).

---

## Recommended Integration Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ POST /v1/agent/sessions                                         │
│   body: { ..., tenant_id?, project_id? }                        │
│   → validate_tenant_membership(user_id, tenant_id)              │
│   → check_quota(tenant_id, "agent_llm", cost_usd=budget.max)   │
│   → cap budget if remaining_quota < requested_max_cost          │
│   → AgentSessionData(tenant_id=..., project_id=...)             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ AgentSession.process_message()                                  │
│                                                                 │
│   [Pre-check] check_quota(tenant_id, "agent_llm") — cached     │
│                                                                 │
│   [LLM call] → budget.consume_llm()                             │
│             → _record_tenant_usage(op="agent_llm",              │
│                   quantity=tokens, cost_usd=cost)                │
│             → emit_budget_update()                               │
│                                                                 │
│   [Tool call] → budget.consume_tool_call()                      │
│              → _record_tenant_usage(op="agent_tool_call",       │
│                    quantity=1)                                    │
│              → emit_tool_call_result()                            │
│                                                                 │
│   [Final] → _record_tenant_usage(op="agent_session_complete",   │
│               cost_usd=budget.total_cost)  — summary record     │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation sequence:
1. **P0-36:** Add `tenant_id`, `project_id` to `AgentSessionData` and session creation endpoint
2. **P0-37:** Add `_record_tenant_usage()` calls after each `consume_llm()` and `consume_tool_call()`
3. **P0-38:** Add `check_quota()` pre-check before LLM calls, with caching

### Key design decisions:
- **Fire-and-forget billing:** `_record_tenant_usage()` must never crash the agent loop
- **Idempotency key:** `{trace_id}:{step_index}:{call_type}` — prevents double-billing on retries
- **Session-level summary:** One final `record_usage()` at session end with `operation="agent_session_complete"` for dashboards
- **No new DB tables needed:** `tenant_usage_events` table already supports the data model
