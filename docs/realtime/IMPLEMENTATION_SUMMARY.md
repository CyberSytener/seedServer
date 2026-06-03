# Real-Time Conversational AI - Foundation: Message Contracts & Action Specification

**Status: ✅ COMPLETE** — All tests passing (18/18)

## What Was Created

This is the foundational layer for a real-time conversational AI system. It defines:

### 1. **Message Contracts** (LLM-agnostic protocol)

All communication between client, gateway, model runtime, and action router is based on JSON messages:

**Client → Server:**
- `client.message` — User input (text, audio, or file)
- `client.command` — UI commands (stop, regenerate, upload_resume)
- `client.action.confirm` — User confirms/rejects actions (e.g., booking)

**Server → Client:**
- `model.partial` — Streaming response (tokens as they arrive)
- `model.final` — Complete response
- `model.invoke_action` — Model requests action execution (KEY TYPE)
- `action.result` — Result from action execution
- `system.event` — Auth, errors, warnings

### 2. **Core Principle: Model Never Has Side-Effects**

```
❌ WRONG: Model calls API directly
✅ RIGHT: Model declares intention via action → Gateway executes → Model gets result
```

This means:
- Model is **LLM-agnostic** (works with OpenAI, Gemini, or local models)
- Model cannot perform side-effects (safety guardrail)
- Gateway/Router has complete control and audit trail
- Easy to test without real APIs

### 3. **Standard Actions**

Model can invoke these actions:

| Action | Purpose | Needs Confirmation |
|--------|---------|-------------------|
| `search_listings` | Search properties | ❌ No |
| `get_listing_details` | Get full property details | ❌ No |
| `book_viewing` | **Book property viewing** | ✅ YES |
| `create_or_update_cv` | Generate/update CV | ❌ No |
| `schedule_lesson` | Schedule language lesson | ✅ YES |
| `record_practice` | Log practice session | ❌ No |
| `send_email` | Send email | ✅ YES |
| `send_sms` | Send SMS | ✅ YES |

### 4. **Validation & Audit**

- `MessageValidator` — Validates all messages against schemas
- `AuditTrail` — Records complete history: actions invoked, results, user confirmations
- `ActionRateLimiter` — Rate limits (e.g., max 3 bookings/session, max 5 emails/session)
- `GuardrailChecker` — Ensures model follows rules (e.g., booking must require confirmation)

### 5. **Confirmation Pattern (for Safety)**

For sensitive actions (booking, email, SMS):

```
1. Model invokes action with requires_user_confirmation=true
2. Gateway shows preview to client
3. User confirms via client.action.confirm
4. Gateway executes only if confirmed
5. Audit trail records: action, confirmation, execution
```

---

## File Structure

```
app/realtime/
├── contracts.py              # Pydantic models (Python)
├── contracts.ts              # TypeScript interfaces (Frontend)
├── actions.py                # Action specs + LLM system prompt
├── validators.py             # Message validation, audit, rate limits
├── schemas.json              # JSON schemas (OpenAPI reference)
├── test_contracts.py         # 18 unit tests (ALL PASSING ✅)
├── MESSAGE_CONTRACTS.md      # Full documentation
└── __init__.py               # Public API
```

---

## Quick Example

### Search Flow (No Confirmation)

```python
# User sends
ClientMessage(text="Find 2-bed apartments in Oslo with balcony")

# Model invokes
ModelInvokeAction(
    action=Action(
        name="search_listings",
        params={"location": "Oslo", "beds_min": 2, "keywords": ["balcony"]},
        metadata=ActionMetadata(session_id="...", requires_user_confirmation=False)
    )
)

# Gateway executes, returns
ActionResult(
    status="success",
    result={"listings": [{"id": "L1", "title": "...", "price": 350000}]}
)

# Model sends final response to user
ModelFinal(content="Found 23 apartments! Here are the top ones...")
```

### Booking Flow (WITH Confirmation)

```python
# User wants to book
ClientMessage(text="Book the first one for Thursday 5-7pm")

# Model invokes WITH confirmation required
ModelInvokeAction(
    action=Action(
        name="book_viewing",
        params={"listing_id": "L1", "preferred_windows": ["2026-02-05T17:00/19:00"]},
        metadata=ActionMetadata(
            session_id="...",
            requires_user_confirmation=True  # CRITICAL
        )
    )
)

# Model shows preview
ModelFinal(content="Preview: 123 Main St, Feb 5 at 5 PM, Agent: John Smith. Confirm?")

# User confirms
ClientActionConfirm(action_id="act_123", confirm=True)

# Gateway executes NOW
ActionResult(status="success", result={"booking_id": "bk_789", "time": "2026-02-05T17:30Z"})

# Model notifies
ModelFinal(content="✅ Booking confirmed! You'll get a confirmation email.")

# Audit trail recorded complete flow with timestamps + confirmations
```

---

## Tests Passing (18/18)

```
✅ test_client_message_creation
✅ test_action_creation
✅ test_action_confirmation
✅ test_validate_action_success
✅ test_validate_action_unknown_action
✅ test_validate_client_message
✅ test_validate_client_message_empty
✅ test_audit_trail_action_invoked
✅ test_audit_trail_user_confirmation
✅ test_audit_trail_export
✅ test_rate_limiter_booking
✅ test_rate_limiter_email
✅ test_rate_limiter_reset
✅ test_guardrail_booking_requires_confirmation
✅ test_guardrail_booking_missing_confirmation
✅ test_guardrail_low_confidence
✅ test_e2e_search_flow
✅ test_e2e_booking_flow
```

---

## Key Design Benefits

| Benefit | How |
|---------|-----|
| **LLM Independence** | Model never calls APIs; Gateway does. Switch Gemini↔OpenAI↔Local instantly |
| **Testability** | Mock actions without real APIs. Test end-to-end flows with synthetic data |
| **Auditability** | Complete trail: who did what, when, with user confirmation timestamps |
| **Safety** | Model cannot perform side-effects; user confirms sensitive actions |
| **Scalability** | Stateless model runtime; state in Redis/Postgres; easy to horizontal scale |
| **Compliance** | GDPR/PII: masking in logs, consent tracking, opt-out handling |

---

## LLM System Prompt

See [app/realtime/actions.py](./actions.py) for `LLM_SYSTEM_PROMPT_REALTIME`:

Key rules enforced:
1. Model NEVER performs side-effects directly
2. Model ONLY invokes actions via JSON structure
3. Model MUST wait for user confirmation for sensitive actions
4. Model MUST show previews before actions
5. Rate limits: max 3 bookings, 5 emails per session
6. Error handling: graceful fallback to human-in-loop

---

## Next Steps (When Ready)

1. **WebSocket Gateway** — Real-time connection handler (Node.js or Python)
2. **Action Router** — Executes actions, calls external APIs, returns results
3. **LLM Integration** — Connect to Gemini/OpenAI with system prompt
4. **Persistence** — Redis session storage, Postgres for audit trail
5. **UI Implementation** — Display streaming responses, preview modals, confirmation buttons
6. **Monitoring** — Prometheus metrics, error tracking, user satisfaction surveys

---

## Files Reference

| File | Purpose |
|------|---------|
| [MESSAGE_CONTRACTS.md](./MESSAGE_CONTRACTS.md) | **Read this first** — Complete protocol documentation with 3 scenarios |
| [contracts.py](./contracts.py) | Pydantic models (Python backend) |
| [contracts.ts](./contracts.ts) | TypeScript interfaces (Frontend) |
| [actions.py](./actions.py) | Action specifications + system prompt |
| [validators.py](./validators.py) | Validation, audit, rate limiting |
| [schemas.json](./schemas.json) | JSON schemas for OpenAPI/client-side validation |
| [test_contracts.py](./test_contracts.py) | Unit tests (18 passing) |

---

## Run Tests

```bash
cd c:\Users\Exempel\Desktop\seed.server.v5\seed_server
python -m pytest app/realtime/test_contracts.py -v
```

Expected output: **18 passed** ✅

---

## Import in Your Code

### Python (Backend)

```python
from app.realtime import (
    ClientMessage, ModelInvokeAction, Action, ActionResult,
    MessageValidator, AuditTrail, GuardrailChecker
)

# Create and validate
msg = ClientMessage(text="Hello")
action = Action(name="search_listings", ...)

validator = MessageValidator()
is_valid, errors = validator.validate_action(action)

# Track audit
trail = AuditTrail("sess_123")
trail.record_action_invoked(action, "gemini-2.0-flash", "turn_001")
```

### TypeScript (Frontend)

```typescript
import {
  ClientMessage, ModelInvokeAction, dispatchMessage,
  isModelPartial, isModelFinal, isActionResult
} from './app/realtime/contracts';

// Send user message
const msg: ClientMessage = { type: "client.message", text: "..." };

// Handle responses
const handler = {
  onModelPartial: (msg) => console.log(msg.chunk),
  onModelFinal: (msg) => console.log(msg.content),
  onActionResult: (msg) => console.log(msg.result),
};

dispatchMessage(msg, handler);
```

---

## Architecture Diagram

```
┌─────────────┐
│   Client    │
│ (Web/Mobile)│
└──────┬──────┘
       │ WebSocket
       │ (client.message, client.action.confirm, etc.)
       │
       ▼
┌────────────────────────┐
│   Realtime Gateway     │
│  - Auth & Rate Limit   │
│  - Message Router      │
│  - Confirmation Handler│
└────┬─────────┬─────────┘
     │         │
     │         └─────────────────────┐
     │                               │
     ▼                               ▼
┌─────────────────┐       ┌──────────────────────┐
│  LLM Runtime    │       │   Action Router      │
│ (Gemini/OpenAI) │       │  - Validation        │
│                 │       │  - Rate Limiting     │
│  system prompt: │       │  - Execution         │
│  - NO side fx   │       │  - Audit Trail       │
│  - Actions only │       └────┬────────┬────────┘
│                 │            │        │
│                 │            ▼        ▼
│                 │   ┌──────────────────────┐
│                 │   │  External Services   │
│                 │   │ - Property API       │
│                 │   │ - Email Service      │
│                 │   │ - Calendar API       │
│                 │   └──────────────────────┘
└─────────────────┘
       │
       │ model.invoke_action, model.partial, model.final
       │
       ▼
┌────────────────────────┐
│  Message Response      │
│ Sent to Client         │
└────────────────────────┘

Persistence (attached to Gateway/Router):
┌──────────────────────┐
│  Redis: Sessions     │
│  Postgres: Audit Log │
└──────────────────────┘
```

---

**Version:** 1.0  
**Status:** Foundation Complete, Ready for WebSocket Gateway Implementation  
**Tests:** 18/18 Passing ✅
