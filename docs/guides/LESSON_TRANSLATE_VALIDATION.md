# Translate Task Validation System

## Overview

This document describes the validation, auto-repair, and retry logic for translate tasks in the lesson generation system.

## Problem Statement

Desktop client reported: **"Invalid translate task payload (no source text)"**

This occurs when the LLM generates translate tasks without the required `content.sourceText` field, causing the client to crash or display errors.

## Solution

Three-layer defense:
1. **Validation**: Strict checks for all required translate fields
2. **Auto-repair**: Safe data movement from legacy field locations
3. **Retry**: Regenerate with specific corrections if still invalid

---

## Validation Rules

For each task where `task.type == "translate"`:

### Required Fields

| Field | Type | Validation |
|-------|------|------------|
| `content.sourceText` | string | Non-empty, the text to be translated |
| `content.targetLang` | string | Non-empty, target language name (e.g., "Spanish") |
| `grading.correctAnswer` | string | Non-empty, canonical translation |
| `task.prompt` | string | Non-empty, instruction for the user |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `grading.acceptedVariants` | string[] | Alternative valid translations |
| `grading.partialCreditKeywords` | string[] | Keywords for partial credit |
| `grading.tip` | string | Hint to show on wrong answer |

### Example Valid Translate Task

```json
{
  "id": "task_1",
  "type": "translate",
  "prompt": "Translate to Spanish: 'Hello, how are you?'",
  "skill": "greetings",
  "difficulty": 1,
  "content": {
    "sourceText": "Hello, how are you?",
    "targetLang": "Spanish"
  },
  "grading": {
    "correctAnswer": "Hola, ¿cómo estás?",
    "acceptedVariants": ["Hola, ¿cómo está?", "Hola, ¿qué tal?"],
    "partialCreditKeywords": ["hola", "cómo"],
    "tip": "Remember the informal 'tú' form uses 'estás'"
  }
}
```

---

## Auto-Repair Logic

Auto-repair attempts to fix translate tasks by **moving existing data** from legacy field locations. It **never invents content**.

### Repair Priority for `content.sourceText`

If `content.sourceText` is missing, check these locations in order:

1. `task.text` → `content.sourceText`
2. `task.sourceText` → `content.sourceText`
3. `task.question` → `content.sourceText`
4. `content.question` → `content.sourceText`
5. Extract from `task.prompt` (e.g., `Translate: "Hello"` → `Hello`)

### Repair for `content.targetLang`

If `content.targetLang` is missing:
- Set `content.targetLang = req.target_lang` (from `/v1/lessons/generate` request)

### No Repair for `grading.correctAnswer`

If `grading.correctAnswer` or `grading.acceptedVariants` are missing:
- **Mark invalid** and trigger retry
- **Do NOT invent** translations

### Example Auto-Repair

**Before Repair:**
```json
{
  "type": "translate",
  "text": "Good morning",
  "content": {},
  "grading": {
    "correctAnswer": "Buenos días"
  }
}
```

**After Repair:**
```json
{
  "type": "translate",
  "content": {
    "sourceText": "Good morning",
    "targetLang": "Spanish"
  },
  "grading": {
    "correctAnswer": "Buenos días"
  }
}
```

**Repair Log:**
```json
{
  "event": "lesson_autorepair_applied",
  "lesson_id": "lesson_xyz",
  "repaired_fields": [
    "Task[0]: moved text to content.sourceText"
  ]
}
```

---

## Retry Policy

If translate task is still invalid after auto-repair:

1. Log validation failure with specific missing fields
2. Regenerate lesson (max 2 retries)
3. Add corrective message to LLM prompt:

```
For translate tasks you MUST include:
- content.sourceText: the text to translate (non-empty string)
- content.targetLang: target language name (e.g., "Spanish", "French")
- grading.correctAnswer: the correct translation (string)
- grading.acceptedVariants: alternative valid translations (string array, can be empty)

CRITICAL: content.sourceText must be the actual text to translate, not empty or null.
```

---

## Observability

### Log Events

#### 1. Auto-Repair Applied
```json
{
  "event": "lesson_autorepair_applied",
  "lesson_id": "lesson_xyz",
  "attempt_number": 1,
  "repaired_fields": [
    "Task[0]: moved text to content.sourceText",
    "Task[0]: added targetLang from request"
  ],
  "duration_ms": 2340
}
```

#### 2. Validation Failed
```json
{
  "event": "lesson_validation_failed",
  "lesson_id": "lesson_xyz",
  "attempt_number": 1,
  "invalid_reasons": [
    "Task[0]: translate missing content.sourceText (non-empty string)",
    "Task[0]: translate missing content.targetLang (non-empty string)"
  ],
  "duration_ms": 2340
}
```

#### 3. Task-Level Invalid (Future Enhancement)
```json
{
  "event": "lesson_task_invalid",
  "lesson_id": "lesson_xyz",
  "task_id": "task_1",
  "task_type": "translate",
  "missing_fields": ["content.sourceText", "content.targetLang"],
  "persona_id_used": "classic_tutor",
  "attempt_number": 1
}
```

---

## Testing

### Test Case 1: Missing sourceText (Recoverable)

**Request:**
```bash
curl -X POST http://localhost:8000/v1/lessons/generate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "vocabulary",
    "targetLang": "Spanish",
    "nativeLang": "English",
    "level": "A1",
    "lessonLength": 3
  }'
```

**Scenario:**
- LLM returns translate task with `task.text = "Good morning"` but no `content.sourceText`

**Expected Behavior:**
1. Validation detects missing `content.sourceText`
2. Auto-repair moves `task.text` → `content.sourceText`
3. Auto-repair adds `content.targetLang = "Spanish"` from request
4. Re-validation passes
5. Client receives valid lesson with complete translate task

**Expected Logs:**
```
lesson_autorepair_applied: Task[0]: moved text to content.sourceText
lesson_generated: status=ok
```

### Test Case 2: Missing sourceText (Unrecoverable)

**Request:** Same as above

**Scenario:**
- LLM returns translate task with NO sourceText in any location
- No `task.text`, no `task.question`, no extractable quoted text

**Expected Behavior:**
1. Validation detects missing `content.sourceText`
2. Auto-repair finds no recoverable data
3. Validation still fails
4. Retry triggered with corrective prompt
5. Attempt 2: LLM generates valid translate task
6. Client receives valid lesson

**Expected Logs:**
```
lesson_validation_failed: Task[0]: translate missing content.sourceText (non-empty string)
lesson_generated: status=ok (attempt 2)
```

### Test Case 3: Missing grading.correctAnswer

**Scenario:**
- LLM returns translate task with `content.sourceText` but no `grading.correctAnswer`

**Expected Behavior:**
1. Validation detects missing `grading.correctAnswer`
2. Auto-repair does NOT invent translation
3. Validation fails
4. Retry triggered with corrective prompt
5. Attempt 2: LLM includes `grading.correctAnswer`
6. Client receives valid lesson

**Expected Logs:**
```
lesson_validation_failed: Task[0]: translate missing grading.acceptedAnswers or grading.correctAnswer
lesson_generated: status=ok (attempt 2)
```

---

## Monitoring Commands

### Check Auto-Repair Rate
```powershell
docker compose logs api --since 1h | Select-String "lesson_autorepair_applied" | Select-String "sourceText"
```

### Check Validation Failures
```powershell
docker compose logs api --since 1h | Select-String "lesson_validation_failed" | Select-String "translate"
```

### Check Translate-Specific Issues
```powershell
docker compose logs api --since 1h | Select-String "translate missing content.sourceText"
```

### Calculate Translate Task Success Rate
```powershell
# Count total translate tasks in generated lessons
$generated = (docker compose logs api --since 1h | Select-String '"type": "translate"').Count

# Count translate validation failures
$failed = (docker compose logs api --since 1h | Select-String "translate missing content.sourceText").Count

# Success rate
$successRate = [math]::Round((($generated - $failed) / $generated) * 100, 1)
Write-Output "Translate task success rate: $successRate%"
```

---

## Success Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| First-attempt pass rate | > 80% | Tasks valid without repair or retry |
| Auto-repair success rate | > 90% | Repaired tasks pass re-validation |
| Final failure rate | < 1% | Tasks fail after all retries |
| Translate field coverage | 100% | All translate tasks have sourceText + targetLang |

---

## Error Response Format

If lesson generation fails after all retries:

**HTTP 502 Bad Gateway**
```json
{
  "detail": "lesson_generation_failed: Validation failed: Task[0]: translate missing content.sourceText (non-empty string)"
}
```

---

## Related Files

- `app/lesson_engine.py`: Validation and auto-repair implementation
- `prompts/lesson_generator.md`: System prompt with translate requirements
- `LESSON_VALIDATION_TESTS.md`: General validation testing guide

---

## Future Enhancements

1. **Task-level logging**: Add `lesson_task_invalid` and `lesson_task_repaired` events for per-task observability
2. **Validation rules API**: Expose validation rules to desktop client for client-side pre-validation
3. **LLM fine-tuning**: Collect validation failure examples to fine-tune LLM on translate task schema
4. **Fallback templates**: If LLM repeatedly fails, use template-based translate task generation
