# Agent WebSocket Streaming Discovery (P0-31)

**Date:** 2026-02-27
**Branch:** `feature/phase0-followup`
**Status:** DONE

---

## Overview

This document audits the existing WebSocket gateway (`app/api/ws/gateway.py`)
and answers four questions about extending it for agent session streaming.

---

## Q1: Can WebSocketGateway support a second message "channel" for agent sessions?

**Yes, with minor extension.**

The current `WebSocketGateway` is a "dumb pipe" transport layer:
- JWT auth via query param (`token`)
- `session_id` for reconnect/resume
- Routes `ClientMessage` to `action_router_queue`
- Streams responses from a `response_queue` Redis channel back to the WS client
- Tracks `active_connections: Dict[str, WebSocket]`

**Key observation:** The gateway routes ALL messages through a single
`action_router_queue` and streams responses from a single `response_queue`.
There is no inherent channel separation today.

**Recommended approach — "Agent stream binding" pattern:**

1. Add `agent_session_id` as an optional field in `ClientMessage` (or a new
   `AgentStreamStart` message type).
2. When a client sends `{type: "agent.stream_start", agent_session_id: "..."}`,
   the gateway validates ownership and subscribes to a Redis channel
   `agent_session:{id}:events`.
3. Events published by the agent loop (`process_message`) are forwarded to the
   WS client in real time.
4. The existing action/saga flow continues to work in parallel — a single WS
   connection can carry both flows, distinguished by `MessageType` prefix
   (`agent.*` vs `model.*` / `action.*`).

**Why NOT a separate WebSocket endpoint:**
- Adds connection management complexity on the client.
- The gateway already handles auth, reconnect, and message queuing — reuse this.
- A single connection supports multiple concurrent "bindings" (saga + agent).

---

## Q2: What new message types are needed?

The following 8 agent-specific message types are recommended, following the
existing `MessageType` enum + Pydantic `BaseModel` pattern:

| Type | Direction | Purpose | Key Fields |
|------|-----------|---------|------------|
| `agent.stream_start` | Client → Server | Bind WS to an agent session | `agent_session_id` |
| `agent.partial` | Server → Client | Streaming LLM text chunks | `content`, `index` |
| `agent.tool_call_start` | Server → Client | Agent is about to call a tool | `tool_name`, `input_preview` |
| `agent.tool_call_result` | Server → Client | Tool call completed | `tool_name`, `output_summary`, `duration_ms` |
| `agent.confirmation_request` | Server → Client | Tool requires user confirmation | `tool_name`, `proposed_input`, `confirmation_id` |
| `agent.budget_update` | Server → Client | Budget snapshot after each step | `budget_snapshot` |
| `agent.final` | Server → Client | Complete agent response | `text`, `artifacts`, `trace`, `budget_snapshot` |
| `agent.error` | Server → Client | Error during processing | `error`, `recoverable` |

All types include `agent_session_id`, `message_id` (UUID), and `timestamp`.

**Compatibility:** These extend `MessageType` with an `agent.*` prefix. The
gateway's existing `_dispatch_message()` can route based on prefix without
changing the core routing logic.

---

## Q3: How to correlate WS connection with agent session_id?

**Recommended: Explicit binding via `agent.stream_start` message.**

Flow:
1. Client opens WS with JWT token (existing flow).
2. Client sends: `{type: "agent.stream_start", agent_session_id: "sess-abc"}`.
3. Gateway validates:
   - Agent session exists (query `AgentSessionStore`).
   - User owns the session (or is an active participant per P0-24).
4. Gateway stores binding: `(ws_session_id) → agent_session_id`.
5. Gateway subscribes to Redis channel `agent_session:sess-abc:events`.
6. Client can bind to ONE agent session per WS connection at a time.
   Sending a new `agent.stream_start` rebinds (stops previous subscription).

**Why not embed in the initial WS connect URL:**
- The existing `/ws?token=...&session_id=...` uses `session_id` for WS session
  resume, not for agent session binding. Overloading it would break semantics.
- Explicit binding is more flexible — client can switch agent sessions without
  reconnecting.

**Redis channel pattern:**
```
agent_session:{agent_session_id}:events   — main event stream
agent_session:{agent_session_id}:status   — session status changes (optional)
```

---

## Q4: Does RedisSessionStore need agent-session-specific state?

**Minimal changes needed.**

Current `RedisSessionStore` manages:
- `ws:session:{id}` — Connection state (user_id, created_at, last_active).
- `ws:session:{id}:pending` — Queued messages during disconnects.

**For agent streaming, add:**
- `ws:session:{id}:agent_binding` — Currently bound `agent_session_id` (string).
  TTL should match the WS session TTL. Set on `agent.stream_start`, cleared on
  unbind or disconnect.
- No need to store agent session data in `RedisSessionStore` — that lives in
  `AgentSessionStore` (SQLite). Redis is only for the ephemeral WS↔agent binding.

**Message queueing during disconnect:**
The existing `queue_message()` / `get_pending_messages()` pattern works for
agent events too. When a WS disconnects while an agent is processing, events
are queued in `ws:session:{id}:pending`. On reconnect + rebind, pending agent
events are replayed.

**Summary:**
- Add ONE key per WS session for agent binding.
- Reuse existing pending message queue for agent events.
- No schema changes to the existing Redis key structure.

---

## Recommended Architecture

```
Client (WS)
    │
    ├── Existing: ClientMessage → action_router_queue → ActionRouter → response
    │
    └── New: agent.stream_start → validate → subscribe Redis channel
         ↓
         agent_session:{id}:events ← AgentSession.process_message() publishes
         ↓
         Gateway forwards events to WS client
```

**Key design decisions:**
1. Single WS connection, multiplexed via `MessageType` prefix.
2. Agent events flow through Redis pub/sub (not the `action_router_queue`).
3. One agent binding per WS session at a time.
4. Reuse existing JWT auth, session resume, and message queueing.

---

## Implementation Order

1. **P0-32:** Define `AgentStreamStart`, `AgentPartial`, `AgentFinal`,
   `AgentToolCallStart`, `AgentToolCallResult`, `AgentConfirmationRequest`,
   `AgentBudgetUpdate`, `AgentError` types in `app/api/ws/agent_types.py`.
2. **P0-33:** Add agent binding to gateway, Redis pub/sub subscription,
   event forwarding loop.
3. **P0-34:** Add event emission hooks to `AgentSession.process_message()`.
