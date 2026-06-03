# Message Contracts & Action Specification

**Foundation for Real-time Conversational AI System**

This document defines the message contract, action specifications, and LLM guardrails that enable:
- **LLM Independence**: Model never executes side-effects; only declares intentions
- **Testability**: Mock actions without real APIs
- **Auditability**: Complete trail of who did what, when, and with what confirmation
- **Safety**: User confirmation enforced before sensitive actions

---

## Overview

### Architecture Pattern

```
User (Client)
    ↓ (WebSocket)
    ├─→ Gateway (message router, auth, validation)
    │    ├─→ Action Router (processes model.invoke_action)
    │    │    ├─→ External APIs (search, booking, etc.)
    │    │    └─→ Internal Services (CV gen, lesson booking)
    │    └─→ LLM Runtime (Gemini, OpenAI, etc.)
    └─← Responses (partial, final, results, events)

Model NEVER talks to external APIs directly.
Model ONLY emits: model.partial, model.final, model.invoke_action.
```

### Key Principle

**Model is a declarer, not an executor.**

```
❌ WRONG: Model calls API directly → returns result
✅ RIGHT: Model says "I want search_listings" → Gateway calls API → Model gets result back
```

---

## Message Types (JSON)

### 1. Client Messages

#### `client.message` - User Input

```json
{
  "type": "client.message",
  "text": "Find 2-bed apartments in Oslo with balcony",
  "audio_ref": null,
  "file_ref": null,
  "metadata": {
    "language": "en",
    "platform": "web"
  }
}
```

**Fields:**
- `text`: Natural language input
- `audio_ref`: Reference to audio file (S3 URL, etc.)
- `file_ref`: Reference to uploaded file (resume.pdf, etc.)
- `metadata`: User context (language, platform, timezone)

---

#### `client.command` - UI Commands

```json
{
  "type": "client.command",
  "command": "stop",
  "action_id": "act_12345",
  "payload": {}
}
```

**Commands:**
- `stop`: Stop current model response
- `regenerate`: Regenerate last response
- `upload_resume`: Upload file for CV
- `clear_context`: Clear conversation context

---

#### `client.action.confirm` - User Confirmation

```json
{
  "type": "client.action.confirm",
  "action_id": "act_12345",
  "confirm": true,
  "reason": "Looks good, book it"
}
```

**When used:**
- Booking actions
- Sending emails/SMS
- Scheduling lessons
- Any side-effect requiring user consent

---

### 2. Server Messages

#### `model.partial` - Streaming Response

```json
{
  "type": "model.partial",
  "chunk": "Here's a great CV for",
  "delta": " a great CV for"
}
```

**Purpose:** Display real-time token streaming to user

---

#### `model.final` - Complete Response

```json
{
  "type": "model.final",
  "content": "Your CV is ready! I found 3 great templates...",
  "metadata": {
    "tokens_used": 342,
    "model": "gemini-2.0-flash",
    "finish_reason": "stop"
  }
}
```

---

#### `model.invoke_action` - Model Requests Action

**This is the KEY message type.**

```json
{
  "type": "model.invoke_action",
  "action": {
    "name": "search_listings",
    "id": "act_search_001",
    "params": {
      "location": "Oslo, Norway",
      "price_min": 250000,
      "price_max": 450000,
      "beds_min": 2,
      "keywords": ["balcony", "near tram"],
      "radius_km": 5,
      "limit": 10
    },
    "metadata": {
      "session_id": "sess_9876543",
      "user_id": "user_123",
      "timestamp": "2026-01-30T10:30:00Z",
      "confidence": 0.92,
      "requires_user_confirmation": false,
      "audit_tags": ["search", "property", "external_api"]
    }
  }
}
```

**Model should emit this when:**
- Needs to search external data
- Booking an action
- Creating documents
- Sending notifications

**Gateway processes:**
1. Validate action against schema
2. Check rate limits / quotas
3. If `requires_user_confirmation=true`:
   - Send preview to client
   - Wait for `client.action.confirm`
   - Only then execute
4. Execute action (call adapter/API)
5. Send back `action.result`

---

#### `action.result` - Action Execution Result

```json
{
  "type": "action.result",
  "action_id": "act_search_001",
  "action_name": "search_listings",
  "status": "success",
  "result": {
    "listings": [
      {
        "id": "L1",
        "title": "Cozy 2-bed with balcony",
        "price": 380000,
        "address": "Frogner, Oslo",
        "coords": [59.9, 10.7],
        "images": ["http://...", "http://..."],
        "score": 0.95
      },
      {
        "id": "L2",
        "title": "Modern apartment near tram",
        "price": 420000,
        "address": "St. Hanshaugen, Oslo",
        "coords": [59.91, 10.73],
        "score": 0.88
      }
    ],
    "total_count": 42,
    "took_ms": 234
  },
  "error": null,
  "requires_manual_review": false,
  "audit": {
    "executed_at": "2026-01-30T10:30:05Z",
    "executor": "action_router",
    "external_provider": "zillow_adapter",
    "user_confirmed": false,
    "confirmation_user_id": null
  }
}
```

**Status values:**
- `success`: Action completed successfully
- `failed`: Action failed (error field contains message)
- `pending`: Action queued
- `in_progress`: Action being executed
- `requires_manual_review`: Escalate to human (e.g., fraud detection)

---

#### `system.event` - System-Level Events

```json
{
  "type": "system.event",
  "level": "error",
  "code": "auth_failed",
  "message": "Invalid session token",
  "details": {
    "session_id": "sess_9876543",
    "reason": "expired"
  }
}
```

**Event codes:**
- `auth_failed`: Authentication error
- `rate_limit`: Rate limit exceeded
- `session_expired`: Session timed out
- `action_failed`: Action execution failed
- `payment_required`: User quota exceeded

---

## Action Specification

### Available Actions

#### 1. `search_listings` - Search Properties

**Purpose:** Search property listings

```json
{
  "name": "search_listings",
  "params": {
    "location": "Oslo, Norway",
    "price_min": 250000,
    "price_max": 450000,
    "beds_min": 2,
    "beds_max": 4,
    "keywords": ["balcony", "pet-friendly"],
    "radius_km": 5,
    "sort_by": "relevance",
    "limit": 10
  }
}
```

**Returns:**
```json
{
  "listings": [
    {
      "id": "L1",
      "title": "...",
      "price": 380000,
      "address": "...",
      "coords": [59.9, 10.7],
      "images": ["..."],
      "score": 0.95
    }
  ],
  "total_count": 42
}
```

**Guardrails:**
- Model must not use real-time location without consent
- If user doesn't specify price range, ask first
- Show results before suggesting bookings

---

#### 2. `book_viewing` - Book Property Viewing

**Purpose:** Book a property viewing appointment

```json
{
  "name": "book_viewing",
  "params": {
    "listing_id": "L1",
    "user_id": "user_123",
    "preferred_windows": [
      "2026-02-05T17:00/2026-02-05T19:00",
      "2026-02-06T10:00/2026-02-06T12:00"
    ],
    "notes": "Flexible on exact time"
  }
}
```

**CRITICAL:**
- `requires_user_confirmation: true` (ALWAYS)
- Model MUST show preview first
- Model MUST wait for `client.action.confirm`

**Returns:**
```json
{
  "status": "confirmed",
  "booking_id": "bk_789",
  "confirmed_datetime": "2026-02-05T17:30:00Z",
  "agent_name": "John Smith",
  "agent_phone": "+47 98765432"
}
```

---

#### 3. `create_or_update_cv` - Create/Update CV

**Purpose:** Create or update user's CV

```json
{
  "name": "create_or_update_cv",
  "params": {
    "user_id": "user_123",
    "cv_payload": {
      "personal": {
        "name": "John Doe",
        "email": "john@example.com",
        "phone": "+47 98765432"
      },
      "summary": "Senior developer with 10 years experience",
      "experience": [
        {
          "company": "TechCorp",
          "position": "Senior Dev",
          "duration": "2020-present",
          "description": "Led team of 5 developers"
        }
      ],
      "education": [],
      "skills": ["JavaScript", "Python", "React"],
      "projects": []
    },
    "format": ["pdf", "docx"]
  }
}
```

**Returns:**
```json
{
  "cv_id": "cv_456",
  "version": 2,
  "formats": {
    "pdf": "s3://bucket/cv_456.pdf",
    "docx": "s3://bucket/cv_456.docx"
  },
  "created_at": "2026-01-30T10:30:05Z"
}
```

---

#### 4. `schedule_lesson` - Schedule Language Lesson

**Purpose:** Schedule language lesson with tutor

```json
{
  "name": "schedule_lesson",
  "params": {
    "user_id": "user_123",
    "tutor_id": "tutor_456",
    "datetime": "2026-02-10T14:00:00Z",
    "duration_minutes": 60,
    "lesson_type": "conversation"
  }
}
```

**Requires confirmation:** YES

---

#### 5. `send_email` - Send Email

**Purpose:** Send email notification

```json
{
  "name": "send_email",
  "params": {
    "to": "user@example.com",
    "subject": "Your viewing confirmation",
    "body": "Your viewing at 123 Main St is confirmed for Feb 5...",
    "cc": [],
    "bcc": []
  }
}
```

**Requires confirmation:** YES

**Guardrails:**
- Model MUST set `requires_user_confirmation=true`
- Model must show exact email content in preview
- No marketing emails without explicit consent

---

#### 6. `send_sms` - Send SMS

**Purpose:** Send SMS notification

```json
{
  "name": "send_sms",
  "params": {
    "phone": "+47 98765432",
    "message": "Your apartment viewing is confirmed for tomorrow at 5 PM."
  }
}
```

**Requires confirmation:** YES

**Guardrails:**
- Limited to 160 characters
- Must include opt-out option

---

## LLM System Prompt

See [app/realtime/actions.py](./actions.py) for the complete system prompt: `LLM_SYSTEM_PROMPT_REALTIME`.

**Key sections:**
1. NO SIDE-EFFECTS rule
2. Action invocation pattern (JSON structure)
3. Confirmation pattern
4. User experience guidelines
5. Guardrails (rate limits, privacy)
6. Error handling
7. Examples

---

## Conversation Flow Example

### Property Finder Scenario

```
User sends (1):
{
  "type": "client.message",
  "text": "Find 2-bed apartments in Oslo under 400k with balcony"
}

↓

Model responds (2a - streaming):
{
  "type": "model.partial",
  "chunk": "I'll search for 2-bed apartments"
}

Model invokes action (2b):
{
  "type": "model.invoke_action",
  "action": {
    "name": "search_listings",
    "id": "act_search_001",
    "params": {
      "location": "Oslo",
      "price_max": 400000,
      "beds_min": 2,
      "keywords": ["balcony"]
    },
    "metadata": {
      "session_id": "...",
      "requires_user_confirmation": false
    }
  }
}

↓

Gateway executes search → returns (3):
{
  "type": "action.result",
  "action_id": "act_search_001",
  "status": "success",
  "result": {
    "listings": [
      {"id": "L1", "title": "...", "price": 380000},
      {"id": "L2", "title": "...", "price": 420000}
    ]
  }
}

↓

Model sends final response (4):
{
  "type": "model.final",
  "content": "Found 23 apartments! Here are the top 2:\n1. Cozy 2-bed at 380k near tram...\n2. Modern apartment at 420k..."
}

↓

User decides & sends (5):
{
  "type": "client.message",
  "text": "Book the first one for next Thursday 5-7pm"
}

↓

Model sends preview + action (6):
{
  "type": "model.partial",
  "chunk": "Great! I'll book"
}

{
  "type": "model.invoke_action",
  "action": {
    "name": "book_viewing",
    "id": "act_book_001",
    "params": {
      "listing_id": "L1",
      "preferred_windows": ["2026-02-05T17:00/2026-02-05T19:00"]
    },
    "metadata": {
      "requires_user_confirmation": true
    }
  }
}

{
  "type": "model.final",
  "content": "Preview:\n- Property: 123 Main St\n- Time: Feb 5, 5-7 PM\n- Agent: John Smith\nConfirm?"
}

↓

User confirms (7):
{
  "type": "client.action.confirm",
  "action_id": "act_book_001",
  "confirm": true
}

↓

Gateway executes booking → returns (8):
{
  "type": "action.result",
  "action_id": "act_book_001",
  "status": "success",
  "result": {
    "booking_id": "bk_789",
    "confirmed_datetime": "2026-02-05T17:30Z"
  }
}

↓

Model notifies user (9):
{
  "type": "model.final",
  "content": "Booking confirmed! ✓ Your viewing is set for Feb 5 at 5:30 PM. You'll get a confirmation email shortly."
}
```

---

## Implementation Files

### Python (Backend)

- [app/realtime/contracts.py](./contracts.py) - Pydantic models
- [app/realtime/actions.py](./actions.py) - Action specs & system prompt
- [app/realtime/schemas.json](./schemas.json) - JSON schemas

### TypeScript (Frontend)

- [app/realtime/contracts.ts](./contracts.ts) - TypeScript interfaces & type guards

### Usage

```python
from app.realtime import ClientMessage, ModelInvokeAction, Action, ActionResult

# Receiving from client
msg = ClientMessage(text="Find apartments", metadata={})

# Sending action request
action = Action(
    name="search_listings",
    id="act_123",
    params={"location": "Oslo"},
    metadata=ActionMetadata(session_id="...", requires_user_confirmation=False)
)
response = ModelInvokeAction(action=action)
```

```typescript
import { ClientMessage, ModelInvokeAction, dispatchMessage } from './contracts';

const msg: ClientMessage = {
  type: "client.message",
  text: "Find apartments"
};

const handler = {
  onClientMessage: (msg) => console.log("User said:", msg.text),
  onModelFinal: (msg) => console.log("Model responded:", msg.content),
};

dispatchMessage(msg, handler);
```

---

## Testing Without Real APIs

Mock implementations for each action:

```python
# app/realtime/mocks.py
class MockActionRouter:
    def execute_search_listings(self, params):
        return {
            "listings": [
                {"id": "L1", "title": "Mock Apartment", "price": 300000}
            ]
        }
    
    def execute_book_viewing(self, params):
        return {
            "booking_id": "bk_mock_123",
            "status": "confirmed"
        }
```

This allows:
- ✅ Unit testing action invocation
- ✅ Integration testing message flow
- ✅ E2E testing without external APIs
- ✅ Load testing with synthetic sessions

---

## Summary

| Concept | Purpose |
|---------|---------|
| **Message Contracts** | Define exact JSON format for client-server communication |
| **Action Specs** | Declare what model CAN do (without doing it) |
| **Confirmation Pattern** | Enforce user consent before side-effects |
| **Audit Trail** | Complete record of who did what, when, with confirmation |
| **LLM Guardrails** | System prompt to keep model from violating rules |
| **Mock Support** | Test without real APIs |

**Next steps:**
1. Implement WebSocket Gateway
2. Implement Action Router
3. Integrate with existing LLM clients
4. Add persistence layer
5. Deploy & monitor
