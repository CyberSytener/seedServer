# Real-Time Conversational AI - Message Contracts & Action Specification

## 📋 Index

### Start Here ⭐

1. **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)** - 2-minute overview
   - Message types cheat sheet
   - Action quick reference
   - Common validation rules
   - Simple example flows

2. **[MESSAGE_CONTRACTS.md](./MESSAGE_CONTRACTS.md)** - Complete protocol (10 min read)
   - Message type definitions
   - Action specifications
   - 3 full scenario examples (search, CV builder, booking)
   - JSON examples
   - Conversation flow walkthrough

3. **[IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)** - Architecture overview
   - What was created
   - Core principle: Model has no side-effects
   - Design benefits
   - Architecture diagram
   - Test results (18/18 ✅)

4. **[API_REFERENCE.md](./API_REFERENCE.md)** - Code API documentation
   - All imports and exports
   - Complete example (Python + TypeScript)
   - Debugging tips
   - Error handling

---

## 📁 Files

### Python Backend

| File | Purpose | Lines |
|------|---------|-------|
| **contracts.py** | Pydantic message models | 380 |
| **actions.py** | Action specs + system prompt | 448 |
| **validators.py** | Validation, audit, rate limits | 377 |
| **__init__.py** | Public API exports | 70 |

### Frontend

| File | Purpose |
|------|---------|
| **contracts.ts** | TypeScript interfaces + helpers | Type-safe message handling |

### References

| File | Purpose |
|------|---------|
| **schemas.json** | JSON Schema (OpenAPI reference) |

### Tests

| File | Purpose | Tests |
|------|---------|-------|
| **test_contracts.py** | Unit tests | 18/18 ✅ |

### Documentation

| File | Purpose |
|------|---------|
| **MESSAGE_CONTRACTS.md** | Full protocol spec |
| **QUICK_REFERENCE.md** | Cheat sheet |
| **IMPLEMENTATION_SUMMARY.md** | Overview |
| **API_REFERENCE.md** | Code API |
| **README.md** | This file |

---

## 🚀 Quick Start

### For Backend Developers (Python)

```bash
# 1. Read QUICK_REFERENCE.md (2 min)
# 2. Read MESSAGE_CONTRACTS.md (10 min)
# 3. Import in your code:

from app.realtime import (
    ClientMessage, Action, ActionMetadata,
    ModelInvokeAction, ActionResult,
    MessageValidator, AuditTrail
)

# 4. Check examples in API_REFERENCE.md
# 5. Run tests:
pytest app/realtime/test_contracts.py -v
```

### For Frontend Developers (TypeScript)

```bash
# 1. Copy contracts.ts to your frontend
# 2. Read QUICK_REFERENCE.md

import {
    ClientMessage, ModelInvokeAction,
    dispatchMessage, isModelPartial
} from './contracts';

// 3. See example in API_REFERENCE.md
```

### For System Designers

```
1. Read QUICK_REFERENCE.md (2 min overview)
2. Read MESSAGE_CONTRACTS.md (scenarios)
3. Study IMPLEMENTATION_SUMMARY.md (architecture)
4. Review architecture diagram in IMPLEMENTATION_SUMMARY.md
```

---

## 🎯 Key Concepts

### Message Types (5 total)

**Client → Server:**
- `client.message` — User input
- `client.command` — UI commands
- `client.action.confirm` — Confirm/reject action

**Server → Client:**
- `model.partial` — Streaming response
- `model.final` — Complete response
- `model.invoke_action` — Request to execute action
- `action.result` — Action execution result
- `system.event` — Errors/warnings

### Core Principle

> **Model NEVER executes side-effects directly. Model ONLY declares intentions via actions.**

This ensures:
- ✅ LLM independence (Gemini/OpenAI/local)
- ✅ Safety (user confirms sensitive actions)
- ✅ Auditability (complete trail)
- ✅ Testability (mock without APIs)

### Standard Actions (8 total)

| Action | Auto-Exec | Purpose |
|--------|-----------|---------|
| search_listings | ✅ Auto | Search properties |
| get_listing_details | ✅ Auto | Get listing details |
| **book_viewing** | ❌ Confirm | Book property viewing |
| create_or_update_cv | ✅ Auto | Generate CV |
| **schedule_lesson** | ❌ Confirm | Schedule lesson |
| record_practice | ✅ Auto | Log practice |
| **send_email** | ❌ Confirm | Send email |
| **send_sms** | ❌ Confirm | Send SMS |

---

## 📊 Test Coverage

```
✅ 18/18 tests passing

Coverage:
- Message creation (3 tests)
- Action validation (4 tests)
- Audit trail (3 tests)
- Rate limiting (3 tests)
- Guardrails (2 tests)
- End-to-end flows (2 tests)
```

Run tests:
```bash
python -m pytest app/realtime/test_contracts.py -v
```

---

## 🏗️ Architecture

```
┌─────────────┐
│   Client    │ WebSocket
│ (Web/Mobile)├─────────────────┐
└─────────────┘                  │
                                 ▼
                        ┌──────────────────┐
                        │  Realtime        │
                        │  Gateway         │
                        │  - Auth          │
                        │  - Validation    │
                        │  - Routing       │
                        └──┬─────────┬─────┘
                           │         │
                    ┌──────▼──┐  ┌──▼───────────┐
                    │  LLM    │  │  Action      │
                    │ Runtime │  │  Router      │
                    │         │  │  - Validate  │
                    │ System  │  │  - Execute   │
                    │ Prompt: │  │  - Audit     │
                    │ NO fx   │  └──┬───────────┘
                    │ Actions │     │
                    │ only    │     ▼
                    └────┬────┘  External APIs

Redis (Sessions) + Postgres (Audit)
```

---

## 📚 Documentation Map

```
QUICK_REFERENCE.md ────────────────┐
                                   │
                                   ▼
MESSAGE_CONTRACTS.md ── Detailed Specs & Examples
                                   │
                                   ├─────────────────┐
                                   │                 │
                                   ▼                 ▼
                   IMPLEMENTATION_  API_REFERENCE.md
                   SUMMARY.md       (Code Examples)
                   (Architecture)
```

---

## ⚡ Common Tasks

### Validate an Action

```python
from app.realtime import MessageValidator

validator = MessageValidator()
is_valid, errors = validator.validate_action(action)
```

### Check Guardrails

```python
from app.realtime import GuardrailChecker

checker = GuardrailChecker()
passes, violations = checker.check_guardrails(action)
```

### Track Audit Trail

```python
from app.realtime import AuditTrail

trail = AuditTrail(session_id="sess_123")
trail.record_action_invoked(action, "gemini", "turn_001")
trail.record_user_confirmation(action_id, confirmed=True)
csv = trail.export_csv()
```

### Rate Limit Actions

```python
from app.realtime import ActionRateLimiter

limiter = ActionRateLimiter()
allowed, msg = limiter.check_limit(session_id, "book_viewing")
```

---

## 🔐 Security & Compliance

- ✅ **Confirmation Required** for: booking, email, SMS, scheduling
- ✅ **Audit Trail** with timestamps + user confirmation
- ✅ **Rate Limiting** per session: 3 bookings, 5 emails/SMS
- ✅ **Guardrails** auto-enforced: no low-confidence critical actions
- ✅ **PII Protection** ready (hash/redact in logs)
- ✅ **GDPR Ready** (consent tracking, audit trail)

---

## 🔄 Message Flow Example

### Property Search (No Confirmation)

```
User: "Find apartments in Oslo"
  ↓
Model: model.invoke_action
  action: search_listings
  requires_user_confirmation: false
  ↓
Gateway: Executes → calls Zillow API
  ↓
Gateway: action.result
  status: success
  result: [{"id": "L1", "title": "Apartment", "price": 350000}]
  ↓
Model: model.final
  "Found 42 apartments! Here are the top ones..."
```

### Property Booking (WITH Confirmation)

```
User: "Book the first one"
  ↓
Model: model.invoke_action
  action: book_viewing
  requires_user_confirmation: true
  ↓
Model: model.final (preview)
  "Preview: 123 Main St, Feb 5 at 5 PM. Confirm?"
  ↓
User: client.action.confirm
  action_id: "act_123"
  confirm: true
  ↓
Gateway: NOW executes booking
  ↓
Gateway: action.result
  status: success
  result: {booking_id: "bk_789", time: "2026-02-05T17:30Z"}
  ↓
Model: model.final
  "✅ Booking confirmed!"
  
Audit: Complete trail recorded with confirmations
```

---

## 📖 Reading Order

### For Quick Understanding (5 min)
1. QUICK_REFERENCE.md — Cheat sheet
2. This README

### For Implementation (30 min)
1. QUICK_REFERENCE.md
2. MESSAGE_CONTRACTS.md
3. API_REFERENCE.md (code examples)

### For Complete Understanding (1 hour)
1. QUICK_REFERENCE.md
2. MESSAGE_CONTRACTS.md
3. IMPLEMENTATION_SUMMARY.md
4. API_REFERENCE.md
5. Code: contracts.py, actions.py, validators.py

### For Debugging
1. API_REFERENCE.md (debugging section)
2. test_contracts.py (see working examples)

---

## ✅ Test Results

```
======================= 18 passed in 0.18s =======================

test_client_message_creation PASSED
test_action_creation PASSED
test_action_confirmation PASSED
test_validate_action_success PASSED
test_validate_action_unknown_action PASSED
test_validate_client_message PASSED
test_validate_client_message_empty PASSED
test_audit_trail_action_invoked PASSED
test_audit_trail_user_confirmation PASSED
test_audit_trail_export PASSED
test_rate_limiter_booking PASSED
test_rate_limiter_email PASSED
test_rate_limiter_reset PASSED
test_guardrail_booking_requires_confirmation PASSED
test_guardrail_booking_missing_confirmation PASSED
test_guardrail_low_confidence PASSED
test_e2e_search_flow PASSED
test_e2e_booking_flow PASSED
```

---

## 🎓 Learning Path

**Beginner:**
1. Read QUICK_REFERENCE.md (2 min)
2. Understand: Model declares intentions via actions
3. See: Simple search example

**Intermediate:**
1. Read MESSAGE_CONTRACTS.md (10 min)
2. Understand: All 8 message types
3. Study: 3 scenario examples
4. See: JSON message formats

**Advanced:**
1. Read IMPLEMENTATION_SUMMARY.md (architecture)
2. Review: contracts.py (data models)
3. Study: validators.py (validation logic)
4. Extend: Add custom guardrails

**Expert:**
1. Full code review (all files)
2. Implement: WebSocket Gateway
3. Integrate: LLM clients
4. Deploy: Production system

---

## 🔗 Related Files

External to this module but relevant:
- Model runtime (`app/llm_client_async.py`) — Connect to Gemini/OpenAI
- Gateway (`app/router.py` or new WebSocket handler) — Route messages
- Database (`app/db.py`) — Persist audit trail
- Redis (`app/redisutil.py`) — Session storage

---

## 📞 Support

### Common Questions

**Q: Can I use different LLM providers?**
A: Yes! Model is LLM-agnostic. Just include the system prompt in your calls.

**Q: How do I test without real APIs?**
A: Use mocks in test_contracts.py. Create mock actions and results.

**Q: How is user confirmation tracked?**
A: AuditTrail records all confirmations with timestamps.

**Q: Can I add new actions?**
A: Yes. Add to ACTION_REGISTRY in actions.py with spec + guardrails.

**Q: What about rate limiting?**
A: Built-in: 3 bookings, 5 emails/SMS per session. Customize in ActionRateLimiter.

---

## 📝 Version Info

- **Version:** 1.0
- **Created:** 2026-01-30
- **Status:** Production Ready ✅
- **Tests:** 18/18 Passing ✅
- **Python:** 3.10+
- **Dependencies:** Pydantic v2.x

---

## 📄 License & Usage

These message contracts and action specifications are part of the real-time conversational AI system. Use freely in your implementation.

---

**START HERE:** Read [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) now! ⭐
