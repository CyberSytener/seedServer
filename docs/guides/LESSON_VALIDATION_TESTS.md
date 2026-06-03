# Lesson Validation Tests

## Overview
The lesson engine now includes strict validation and auto-repair for LLM-generated lessons. This ensures the desktop client never receives malformed tasks.

## Validation Rules

### Common Task Fields
All tasks must have:
- `id`: string
- `type`: one of ["mcq", "translate", "fill_blank", "word_order"]
- `prompt`: string
- `skill`: string  
- `difficulty`: integer 1-5
- `content`: object (type-specific)
- `grading`: object (type-specific)

### Task Type Requirements

#### MCQ (Multiple Choice Question)
```json
{
  "type": "mcq",
  "content": {
    "choices": ["Option1", "Option2", "Option3"],  // Required: non-empty array
    "question": "What is..."  // Required: question text
  },
  "grading": {
    "correctChoiceIndex": 0,  // Required: integer 0 to choices.length-1
    "correctAnswer": "Option1",
    "tip": "Hint text"
  }
}
```

#### Translate
```json
{
  "type": "translate",
  "content": {
    "sourceText": "Hello"  // Required
  },
  "grading": {
    "correctAnswer": "Hola",  // Required
    "acceptedVariants": ["¡Hola!"],  // Optional
    "tip": "Informal greeting"
  }
}
```

#### Fill Blank
```json
{
  "type": "fill_blank",
  "content": {
    "sentenceWithBlank": "I _____ happy"  // Required: must contain __ or ___
  },
  "grading": {
    "correctAnswer": "am",  // Required
    "acceptedVariants": ["'m"],  // Optional
    "tip": "Present tense of 'to be'"
  }
}
```

#### Word Order
```json
{
  "type": "word_order",
  "content": {
    "tokens": ["the", "cat", "is", "black"]  // Required: array with 2+ items
  },
  "grading": {
    "correctAnswer": "The cat is black",  // Required
    "tip": "Subject-verb-adjective"
  }
}
```

## Auto-Repair Logic

The server attempts to fix common LLM mistakes:

1. **MCQ choices in wrong location**:
   - Moves `task.choices` → `content.choices`
   - Moves `task.options` → `content.choices`
   - Renames `content.options` → `content.choices`

2. **Question text in wrong location**:
   - Moves `task.question` → `content.question`
   - Moves `task.text` → `content.question`

3. **Translate sourceText missing**:
   - Moves `task.text` → `content.sourceText`

4. **Fill blank sentence field**:
   - Renames `content.sentence` → `content.sentenceWithBlank`

5. **Word order tokens field**:
   - Renames `content.words` → `content.tokens`

## Test Cases

### Test 1: Valid Lesson (No Repair Needed)
```bash
curl -X POST http://localhost:8000/v1/lessons/generate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "vocabulary",
    "targetLang": "Spanish",
    "nativeLang": "English",
    "level": "A1",
    "lessonLength": 3,
    "personaId": "classic_tutor"
  }'
```

**Expected**: HTTP 200 with valid lesson containing 3 tasks

**Check**: All tasks have required fields, no validation errors logged

---

### Test 2: MCQ Missing Choices (Auto-Repair)
If LLM returns:
```json
{
  "type": "mcq",
  "choices": ["Red", "Blue", "Green"],  // Wrong location!
  "prompt": "What color is 'rojo'?",
  "content": {},
  "grading": { "correctChoiceIndex": 0 }
}
```

**Expected**: Server auto-repairs by moving `choices` to `content.choices`

**Logs**: Should see:
```json
{
  "event": "lesson_autorepair_applied",
  "repaired_fields": ["Task[0]: moved choices from task.choices to content.choices"]
}
```

---

### Test 3: MCQ correctChoiceIndex Out of Range
If LLM returns:
```json
{
  "type": "mcq",
  "content": {
    "choices": ["Red", "Blue"],
    "question": "Pick a color"
  },
  "grading": { "correctChoiceIndex": 5 }  // Out of range!
}
```

**Expected**: 
1. First attempt fails validation
2. Server retries with specific error correction
3. Either succeeds on retry or returns HTTP 502

**Logs**: Should see:
```json
{
  "event": "lesson_validation_failed",
  "invalid_reasons": ["Task[0]: correctChoiceIndex 5 out of range [0, 1]"]
}
```

---

### Test 4: Translate Missing Source Text
If LLM returns translate task without `content.sourceText`:

**Expected**: Validation fails, retry with specific correction prompt

---

### Test 5: Fill Blank Missing Blank Marker
If LLM returns:
```json
{
  "type": "fill_blank",
  "content": {
    "sentenceWithBlank": "I am happy"  // No blank!
  }
}
```

**Expected**: Validation error, retry with correction

---

## PowerShell Test Commands

```powershell
# Set API key
$env:TEST_API_KEY = "seed_YOUR_KEY_HERE"
$headers = @{ "Authorization" = "Bearer $env:TEST_API_KEY" }

# Test 1: Valid lesson
$body = @{
  mode = "vocabulary"
  targetLang = "Spanish"
  nativeLang = "English"
  level = "A1"
  lessonLength = 3
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/generate" `
  -Method POST -Headers $headers -Body $body -ContentType "application/json"

Write-Output "✅ Lesson generated: $($response.lesson.lessonId)"
Write-Output "Tasks: $($response.lesson.tasks.Count)"

# Check task 1 structure
$task1 = $response.lesson.tasks[0]
Write-Output "`nTask 1 Type: $($task1.type)"
Write-Output "Has prompt: $($null -ne $task1.prompt)"
Write-Output "Has content: $($null -ne $task1.content)"
Write-Output "Has grading: $($null -ne $task1.grading)"

# For MCQ tasks, check choices
if ($task1.type -eq "mcq") {
  Write-Output "MCQ Choices: $($task1.content.choices.Count)"
  Write-Output "Choices: $($task1.content.choices -join ', ')"
}
```

## Monitoring Validation

Check Docker logs for validation events:

```bash
# See auto-repairs
docker compose logs api | grep "lesson_autorepair_applied"

# See validation failures
docker compose logs api | grep "lesson_validation_failed"

# See generation failures
docker compose logs api | grep "lesson_generation_failed"
```

## Error Response Format

If lesson generation fails after all retries:

```json
{
  "detail": "lesson_generation_failed: Validation failed: Task[0]: mcq missing content.choices"
}
```

HTTP Status: **502 Bad Gateway**

## Success Metrics

A healthy lesson generation should:
- ✅ Generate lessons in < 5 seconds
- ✅ Validation pass rate > 80% on first attempt
- ✅ Auto-repair rate < 20%
- ✅ Final failure rate < 1%

Monitor these in your logs to tune the generator prompt.
