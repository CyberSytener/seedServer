# Persona Selection Implementation - Test Checklist

## ✅ Implementation Complete

Server-side persona selection has been successfully implemented in the Seed Server.

## Summary of Changes

### 1. **New Module: [app/personas.py](app/personas.py)**
- Persona registry with 6 pre-defined personas:
  - `classic_tutor` (default) - Helpful, knowledgeable assistant
  - `bard_cat` - Friendly language tutor
  - `fortune_cat` - Mystical fortune teller
  - `minimal` - Direct, concise responses
  - `creative_writer` - Creative writing assistant
  - `code_mentor` - Patient coding mentor
- `get_persona_prompt(persona_id)` → returns `(persona_id_used, system_prompt)`
- Security: validates personaId format (max 64 chars, only `[a-z0-9_-]`)
- Fallback: unknown/invalid personaId → defaults to `classic_tutor`

### 2. **Models Updated: [app/models.py](app/models.py)**
- `ActionRequest`: added `persona_id` field with alias `personaId`
- `ActionResponse`: added `persona_id_used` field with alias `personaIdUsed`
- `JobResponse`: added `persona_id_used` field with alias `personaIdUsed`
- All models configured with `populate_by_name=True` for camelCase/snake_case support

### 3. **Router Enhanced: [app/router.py](app/router.py)**
- `ActionResult` dataclass: added `persona_id_used` field
- `_build_prompt()`: accepts `persona_prompt` parameter for 'ask' action
- `execute_action()`: accepts `persona_id` parameter, gets persona prompt, passes to providers
- All providers (OpenAI, Gemini, Stub) updated to accept and return `persona_id_used`

### 4. **Main API: [app/main.py](app/main.py)**
- `POST /v1/actions`: extracts `persona_id` from request, returns `persona_id_used` in response
- Inline execution: passes `persona_id` to `execute_action()`
- Database: stores `persona_id_used` in jobs table
- Structured logging: logs `persona_id_requested`, `persona_id_used`, duration, status
- Error handling: includes `persona_id_used` in all responses (success/fail/timeout)

### 5. **Worker: [app/worker_redis.py](app/worker_redis.py)**
- Extracts `persona_id` from job options or stored `persona_id_used`
- Passes to `execute_action()` for queued job processing
- Stores `persona_id_used` in database when job completes

### 6. **Database: [app/db.py](app/db.py)**
- Schema: added `persona_id_used TEXT` column to `jobs` table
- Migration: automatic migration adds column to existing databases

### 7. **Logging: [run.py](run.py)**
- Configured structured logging with INFO level
- Logs include request_id, persona_id_requested, persona_id_used, duration_ms, status

## Test Results ✅

### Test 1: Valid Persona (bard_cat)
```bash
POST /v1/actions
{
  "action": "ask",
  "text": "Teach me how to say hello in Spanish",
  "personaId": "bard_cat"
}
```
**Result:** ✅
- `personaIdUsed: "bard_cat"`
- `status: "done"`
- System prompt injected correctly

### Test 2: Unknown Persona (fallback to default)
```bash
POST /v1/actions
{
  "action": "ask",
  "text": "What is 2 + 2?",
  "personaId": "unknown_persona"
}
```
**Result:** ✅
- `personaIdUsed: "classic_tutor"` (fallback)
- `status: "done"`
- Graceful fallback working

### Test 3: No PersonaId (default behavior)
```bash
POST /v1/actions
{
  "action": "ask",
  "text": "Hello, how are you?"
}
```
**Result:** ✅
- `personaIdUsed: "classic_tutor"` (default)
- `status: "done"`
- Backward compatible

### Test 4: GET /v1/jobs/{job_id}
```bash
GET /v1/jobs/{job_id}
Authorization: Bearer {api_key}
```
**Result:** ✅
- Response includes `personaIdUsed` field
- Job details correctly returned

### Test 5: fortune_cat Persona
```bash
POST /v1/actions
{
  "action": "ask",
  "text": "Tell me my fortune for today",
  "personaId": "fortune_cat"
}
```
**Result:** ✅
- `personaIdUsed: "fortune_cat"`
- Mystical persona system prompt applied

## API Contract

### Request
```json
POST /v1/actions
Authorization: Bearer {api_key}

{
  "action": "ask",
  "text": "user message",
  "personaId": "bard_cat",  // optional, camelCase
  "options": {}
}
```

### Response
```json
{
  "job_id": "job_...",
  "mode": "fast",
  "status": "done",
  "personaIdUsed": "bard_cat",  // camelCase in JSON
  "result_text": "..."
}
```

### GET /v1/jobs/{job_id}
```json
{
  "id": "job_...",
  "action": "ask",
  "status": "done",
  "personaIdUsed": "bard_cat",
  "result_text": "...",
  ...
}
```

## Verification Checklist

- [x] Request with `personaId="bard_cat"` returns `personaIdUsed="bard_cat"`
- [x] Unknown `personaId` falls back to `"classic_tutor"`
- [x] No `personaId` defaults to `"classic_tutor"`
- [x] `personaIdUsed` returned in POST /v1/actions response
- [x] `personaIdUsed` returned in GET /v1/jobs/{job_id} response
- [x] Structured logs contain `persona_id_requested` and `persona_id_used`
- [x] Database stores `persona_id_used` in jobs table
- [x] Worker processes jobs with correct persona
- [x] Persona system prompt correctly injected for 'ask' action
- [x] Other actions (fix, translate, summarize) unaffected
- [x] Backward compatible: existing clients without personaId work
- [x] Security: personaId validated (max 64 chars, safe characters only)

## Available Personas

| Persona ID | Description |
|------------|-------------|
| `classic_tutor` | Default helpful assistant (default) |
| `bard_cat` | Friendly language tutor |
| `fortune_cat` | Mystical fortune teller |
| `minimal` | Direct, concise answers |
| `creative_writer` | Creative writing assistant |
| `code_mentor` | Patient coding mentor |

## Structured Logging Example

```
INFO - Action executed - {
  "request_id": "job_abc123",
  "user_id": "user_xyz",
  "action": "ask",
  "mode": "fast",
  "persona_id_requested": "bard_cat",
  "persona_id_used": "bard_cat",
  "provider": "gemini",
  "model": "gemini-2.0-flash-lite",
  "duration_ms": 1234,
  "status": "ok"
}
```

## Security Features

1. **Input Validation**: personaId limited to 64 chars, pattern: `[a-z0-9_-]`
2. **No Client Prompts**: Clients cannot send arbitrary system prompts (server-side registry only)
3. **Safe Fallback**: Invalid/malicious personaId → default persona
4. **Logging**: All persona usage logged for audit

## Desktop Integration Ready

The server is now ready for the Seed Desktop app to:
1. Send `personaId` in request body (camelCase)
2. Receive `personaIdUsed` in response to confirm server accepted the persona
3. Display persona-specific UI based on `personaIdUsed`
4. Handle fallback gracefully (unknown persona → classic_tutor)

## Next Steps (Optional Enhancements)

- [ ] Admin endpoint to list available personas: `GET /v1/personas`
- [ ] Per-user persona preferences stored in database
- [ ] Dynamic persona loading from files/database
- [ ] Persona-specific rate limits or features
- [ ] SSE meta event with `personaIdUsed` for streaming responses
