# Message Contracts - Quick Reference

## Message Types Cheat Sheet

### Client → Server

| Type | When | Example |
|------|------|---------|
| `client.message` | User sends text/audio/file | `{"type": "client.message", "text": "Find apartments"}` |
| `client.command` | User clicks UI button | `{"type": "client.command", "command": "stop"}` |
| `client.action.confirm` | User confirms action | `{"type": "client.action.confirm", "action_id": "act_123", "confirm": true}` |

### Server → Client

| Type | When | Next Step |
|------|------|-----------|
| `model.partial` | Model generating response | Add to chat bubble in real-time |
| `model.final` | Model done with response | Display full response |
| `model.invoke_action` | Model wants to execute action | Show preview + confirmation (if `requires_user_confirmation=true`) |
| `action.result` | Action execution complete | Pass back to model + show to user |
| `system.event` | Error/warning/auth | Show error toast/modal |

---

## Action Quick Reference

### Status
- ✅ `success` → Action worked
- ❌ `failed` → Action failed (error in message)
- ⏳ `pending` / `in_progress` → Waiting/executing
- 🔍 `requires_manual_review` → Escalate to human

### Common Actions & Confirmation

| Action | Requires Confirm? | When Used |
|--------|------------------|-----------|
| `search_listings` | ❌ | "Find apartments in Oslo" |
| `book_viewing` | ✅ | "Book the first one" |
| `create_or_update_cv` | ❌ | "Generate my CV" |
| `schedule_lesson` | ✅ | "Schedule a lesson" |
| `send_email` | ✅ | Auto-generated confirmations |
| `send_sms` | ✅ | Send text notifications |

---

## Validation Rules (Must Pass)

### Actions
1. ✅ Action name in registry
2. ✅ Action ID starts with `act_`
3. ✅ Has `session_id` in metadata
4. ✅ Required params present
5. ✅ If spec says `requires_confirmation=true`, model must set it

### Messages
1. ✅ Has text OR audio_ref OR file_ref (not empty)
2. ✅ Text < 50K characters
3. ✅ Confirmation action_id matches actual action

---

## Rate Limits (Per Session)

```
booking (book_viewing):    3 max per session
email (send_email):        5 max per session
sms (send_sms):            5 max per session
other actions:             unlimited
```

---

## Guardrails (Auto-Checked)

| Rule | Enforced? | Example |
|------|-----------|---------|
| Model CANNOT bypass confirmation | ✅ | `requires_user_confirmation=false` for booking → VIOLATION |
| Critical actions need confidence | ✅ | send_email with confidence 0.5 → VIOLATION |
| Booking must have time windows | ✅ | book_viewing without preferred_windows → VIOLATION |
| No low-confidence critical actions | ✅ | book_viewing with confidence < 0.7 → WARNING |

---

## Audit Trail

Every turn recorded:
- ✅ Action name, ID, params
- ✅ Model used, confidence level
- ✅ User confirmation (yes/no)
- ✅ Execution result & error (if any)
- ✅ Timestamps (ISO 8601)

Export as CSV for compliance/debugging.

---

## Example Flows

### ✅ Valid: Search (No Confirmation)

```
User: "Find 2-bed apartments in Oslo"
    ↓
Model sends: model.invoke_action
  name: search_listings
  requires_user_confirmation: false
    ↓
Gateway executes → action.result
    ↓
Model sends: model.final with results
```

### ✅ Valid: Booking (WITH Confirmation)

```
User: "Book the first one"
    ↓
Model sends: model.invoke_action
  name: book_viewing
  requires_user_confirmation: true
    ↓
Model sends: model.final (preview)
  "Preview: 123 Main St, Feb 5 at 5 PM. Confirm?"
    ↓
User sends: client.action.confirm (confirm: true)
    ↓
Gateway executes ONLY NOW → action.result
    ↓
Model sends: model.final
  "✅ Booking confirmed!"
```

### ❌ Invalid: Booking Without Confirmation

```
Model sends: model.invoke_action
  name: book_viewing
  requires_user_confirmation: false  ← VIOLATION!
    ↓
GuardrailChecker REJECTS
  error: "booking_viewing MUST require user confirmation"
```

---

## Testing Without Real APIs

Use mock actions:

```python
from app.realtime.validators import create_mock_action, create_mock_action_result

# Create test action
action = create_mock_action(
    name="search_listings",
    session_id="sess_test",
    location="Oslo"
)

# Create test result
result = create_mock_action_result(
    action_id=action.id,
    action_name="search_listings",
    status=ActionStatus.SUCCESS,
    result={"listings": [{"id": "L1", "title": "Test"}]}
)

# Test end-to-end without real API
```

---

## Code Examples

### Python: Validate & Send Action

```python
from app.realtime import (
    Action, ActionMetadata, ModelInvokeAction,
    MessageValidator, GuardrailChecker
)

# Create action
action = Action(
    name="search_listings",
    id="act_search_001",
    params={"location": "Oslo", "beds_min": 2},
    metadata=ActionMetadata(
        session_id="sess_123",
        user_id="user_456",
        confidence=0.92,
        requires_user_confirmation=False
    )
)

# Validate
validator = MessageValidator()
is_valid, errors = validator.validate_action(action)
if not is_valid:
    print(f"Invalid: {errors}")

# Check guardrails
checker = GuardrailChecker()
passes, violations = checker.check_guardrails(action)
if not passes:
    print(f"Guardrail violations: {violations}")

# Send to client
response = ModelInvokeAction(action=action)
print(response.json())
```

### TypeScript: Handle Responses

```typescript
import { dispatchMessage, isModelPartial, isActionResult } from './contracts';

const handler = {
  onModelPartial: (msg) => {
    // Stream in real-time
    document.getElementById('response').innerText += msg.chunk;
  },
  
  onModelFinal: (msg) => {
    // Complete response
    console.log('Final:', msg.content);
  },
  
  onModelInvokeAction: (msg) => {
    if (msg.action.metadata.requires_user_confirmation) {
      // Show confirmation modal
      showConfirmationModal(msg.action);
    }
  },
  
  onActionResult: (msg) => {
    if (msg.status === 'success') {
      console.log('Success:', msg.result);
    } else if (msg.status === 'failed') {
      console.error('Action failed:', msg.error);
    }
  },
  
  onSystemEvent: (msg) => {
    console.error(`${msg.level}: ${msg.message}`);
  }
};

// Incoming message
const incomingJson = `{"type": "model.partial", "chunk": "Searching..."}`;
const msg = JSON.parse(incomingJson);
dispatchMessage(msg, handler);
```

---

## Files to Read

| File | For |
|------|-----|
| [MESSAGE_CONTRACTS.md](./MESSAGE_CONTRACTS.md) | Full protocol spec + examples |
| [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) | Overview + architecture |
| [contracts.py](./contracts.py) | Python data models |
| [contracts.ts](./contracts.ts) | TypeScript types |
| [actions.py](./actions.py) | Action specs + LLM system prompt |
| [validators.py](./validators.py) | Validation logic |

---

**TL;DR:**
- Model → `model.invoke_action` (not direct API call)
- Gateway → validates + executes + returns `action.result`
- For sensitive actions → model shows preview + waits for user `client.action.confirm`
- Complete audit trail recorded
- All messages JSON-based, LLM-agnostic ✅
