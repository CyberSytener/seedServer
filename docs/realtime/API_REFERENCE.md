# Public API Reference

## Import Path

```python
from app.realtime import ...
```

---

## Message Types

```python
from app.realtime import (
    # Client → Server
    ClientMessage,           # User message (text/audio/file)
    ClientCommand,           # UI command (stop, regenerate, etc.)
    ClientActionConfirm,     # User confirms/rejects action
    
    # Server → Client
    ModelPartial,            # Streaming response chunk
    ModelFinal,              # Complete response
    ModelInvokeAction,       # Model requests action execution
    ActionResult,            # Action execution result
    SystemEvent,             # Error/warning/auth event
    
    # Helpers
    ConversationTurn,        # Complete conversation turn record
    ClientMessageUnion,      # Union type for client messages
    ServerMessageUnion,      # Union type for server messages
)
```

---

## Action Types

```python
from app.realtime import (
    Action,                  # Action to invoke
    ActionMetadata,          # Audit metadata for action
    ActionStatus,            # Status enum (success, failed, pending, etc.)
)

# Enum values
ActionStatus.SUCCESS                  # ✅ Action succeeded
ActionStatus.FAILED                   # ❌ Action failed
ActionStatus.PENDING                  # ⏳ Action queued
ActionStatus.IN_PROGRESS              # 🔄 Executing
ActionStatus.REQUIRES_MANUAL_REVIEW   # 🔍 Escalate to human
```

---

## Validators

```python
from app.realtime import (
    MessageValidator,        # Validate messages and actions
    AuditTrail,             # Track audit events
    ActionRateLimiter,      # Rate limit actions per session
    GuardrailChecker,       # Check action guardrails
    ValidationError,        # Validation exception
    AuditEvent,             # Audit event enum
)

# Usage
validator = MessageValidator()
is_valid, errors = validator.validate_action(action)

trail = AuditTrail(session_id="sess_123")
trail.record_action_invoked(action, model_used="gemini", turn_id="turn_001")

limiter = ActionRateLimiter()
allowed, msg = limiter.check_limit(session_id, "book_viewing")

checker = GuardrailChecker()
passes, violations = checker.check_guardrails(action)
```

---

## Action Specifications

```python
from app.realtime import (
    ActionSpec,              # Action specification
    ACTION_REGISTRY,         # Dict of all action specs
    LLM_SYSTEM_PROMPT_REALTIME,  # System prompt for LLM
    get_action_spec,         # Look up action spec by name
    get_all_action_specs,    # Get all action specs
)

# Usage
spec = get_action_spec("search_listings")
all_specs = get_all_action_specs()
print(LLM_SYSTEM_PROMPT_REALTIME)
```

---

## Standard Actions

Available actions (in ACTION_REGISTRY):

1. **`search_listings`**
   - Search properties by location, price, amenities
   - `requires_confirmation: False`
   - Params: `location`, `price_min`, `price_max`, `beds_min`, `beds_max`, `keywords`, `radius_km`, `limit`

2. **`get_listing_details`**
   - Get full listing details
   - `requires_confirmation: False`
   - Params: `listing_id`

3. **`book_viewing`** ⭐
   - Book property viewing
   - `requires_confirmation: True` (MANDATORY)
   - Params: `listing_id`, `user_id`, `preferred_windows`, `notes`

4. **`create_or_update_cv`**
   - Create or update CV
   - `requires_confirmation: False`
   - Params: `user_id`, `cv_payload` (sections), `format` (pdf/docx/json)

5. **`schedule_lesson`** ⭐
   - Schedule language lesson
   - `requires_confirmation: True` (MANDATORY)
   - Params: `user_id`, `tutor_id`, `datetime`, `duration_minutes`, `lesson_type`

6. **`record_practice`**
   - Record practice session
   - `requires_confirmation: False`
   - Params: `user_id`, `lesson_id`, `duration_seconds`, `exercise_type`, `score`, `feedback`

7. **`send_email`** ⭐
   - Send email notification
   - `requires_confirmation: True` (MANDATORY)
   - Params: `to`, `subject`, `body`, `cc`, `bcc`

8. **`send_sms`** ⭐
   - Send SMS notification
   - `requires_confirmation: True` (MANDATORY)
   - Params: `phone`, `message` (max 160 chars)

---

## JSON Schema Reference

```python
# All message schemas available in
import json
with open("app/realtime/schemas.json") as f:
    schemas = json.load(f)

# Access schemas
schemas["definitions"]["ClientMessage"]
schemas["definitions"]["ModelInvokeAction"]
schemas["definitions"]["ActionResult"]
schemas["definitions"]["Action"]
schemas["definitions"]["ActionStatus"]
# ... etc
```

---

## Testing Utilities

```python
from app.realtime.validators import (
    create_mock_action,           # Create test action
    create_mock_action_result,    # Create test result
)

# Usage
action = create_mock_action(
    name="search_listings",
    session_id="sess_test",
    location="Oslo"
)

result = create_mock_action_result(
    action_id=action.id,
    action_name="search_listings",
    status=ActionStatus.SUCCESS,
    result={"listings": [...]}
)
```

---

## Complete Example

### Python Backend

```python
import json
from uuid import uuid4
from datetime import datetime

from app.realtime import (
    ClientMessage,
    Action,
    ActionMetadata,
    ModelInvokeAction,
    ActionResult,
    ActionStatus,
    MessageValidator,
    AuditTrail,
    ActionRateLimiter,
    GuardrailChecker,
)

# Session setup
session_id = "sess_" + uuid4().hex[:8]
user_id = "user_" + uuid4().hex[:8]
trail = AuditTrail(session_id)
limiter = ActionRateLimiter()
validator = MessageValidator()
checker = GuardrailChecker()

# User sends message
user_msg = ClientMessage(text="Find 2-bed apartments in Oslo")
print(f"User: {user_msg.text}")

# Model creates action
action = Action(
    name="search_listings",
    id="act_" + uuid4().hex[:8],
    params={
        "location": "Oslo",
        "beds_min": 2,
        "keywords": ["balcony"],
    },
    metadata=ActionMetadata(
        session_id=session_id,
        user_id=user_id,
        confidence=0.92,
        requires_user_confirmation=False,
    ),
)

# Validate
is_valid, errors = validator.validate_action(action)
assert is_valid, f"Validation failed: {errors}"

# Check rate limit
allowed, msg = limiter.check_limit(session_id, action.name)
assert allowed, msg

# Check guardrails
passes, violations = checker.check_guardrails(action)
assert passes, f"Guardrail violations: {violations}"

# Record action
trail.record_action_invoked(action, "gemini-2.0-flash", "turn_001")

# Send action
response = ModelInvokeAction(action=action)
print(f"Model invokes: {response.json()}")

# [Gateway executes action here]

# Simulate result
result = ActionResult(
    action_id=action.id,
    action_name=action.name,
    status=ActionStatus.SUCCESS,
    result={
        "listings": [
            {"id": "L1", "title": "Cozy 2-bed", "price": 350000},
            {"id": "L2", "title": "Modern apartment", "price": 380000},
        ]
    },
)

# Record result
trail.record_action_result(result, "turn_001")

# Model sends final
print(f"Results: {len(result.result['listings'])} apartments found")
print(f"Audit trail: {len(trail.get_events())} events recorded")
```

### TypeScript Frontend

```typescript
import {
  ClientMessage,
  ModelInvokeAction,
  ActionResult,
  SystemEvent,
  dispatchMessage,
  isModelPartial,
  isModelFinal,
  isActionResult,
  isSystemEvent,
} from './app/realtime/contracts';

const ws = new WebSocket('ws://localhost:8000/realtime');

// Send user message
const msg: ClientMessage = {
  type: "client.message",
  text: "Find apartments in Oslo",
};
ws.send(JSON.stringify(msg));

// Handle incoming messages
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  const handler = {
    onModelPartial: (msg: ModelPartial) => {
      console.log("Streaming:", msg.chunk);
      document.getElementById('response').innerText += msg.chunk;
    },

    onModelFinal: (msg: ModelFinal) => {
      console.log("Final:", msg.content);
    },

    onModelInvokeAction: (msg: ModelInvokeAction) => {
      console.log("Action:", msg.action.name);
      
      if (msg.action.metadata.requires_user_confirmation) {
        showConfirmationDialog(msg.action);
      }
    },

    onActionResult: (msg: ActionResult) => {
      if (msg.status === 'success') {
        console.log("Results:", msg.result);
      } else if (msg.status === 'failed') {
        console.error("Error:", msg.error);
      }
    },

    onSystemEvent: (msg: SystemEvent) => {
      if (msg.level === 'error') {
        console.error(msg.message);
      }
    },
  };

  dispatchMessage(data, handler);
};
```

---

## Debugging

```python
# Export audit trail to CSV
csv = trail.export_csv()
print(csv)

# Get all events
events = trail.get_events()
for event in events:
    print(f"{event['timestamp']}: {event['event']} - {event.get('action_name')}")

# Validate before sending
validator = MessageValidator()

# Check all actions in registry
from app.realtime import get_all_action_specs
for spec in get_all_action_specs():
    print(f"{spec.name}: {spec.requires_confirmation}")
```

---

## Configuration

All defaults in code. For production:

```python
# Override rate limits
limiter = ActionRateLimiter()
limiter.limits["booking"] = 5  # Allow 5 bookings instead of 3

# Custom guardrails
checker = GuardrailChecker()
# (extend check_guardrails method)
```

---

## Error Handling

```python
from app.realtime import ValidationError

try:
    is_valid, errors = validator.validate_action(action)
    if not is_valid:
        raise ValidationError(f"Invalid action: {errors}")
except ValidationError as e:
    # Handle validation error
    pass
```

---

**Version:** 1.0  
**Last Updated:** 2026-01-30  
**Status:** Production Ready ✅
