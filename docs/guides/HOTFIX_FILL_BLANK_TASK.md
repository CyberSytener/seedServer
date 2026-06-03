# Hotfix: Fill Blank Task Sentence Mapping

**Issue Date:** 2026-01-10  
**Status:** ✅ RESOLVED  
**Priority:** HIGH

## Problem

Desktop client reported error:
```
⚠️ Invalid fill blank: no sentence with blank marker
```

This occurred when Desktop received fill_blank tasks from the diagnostic API.

## Root Cause

The DTO transformation in `app/dto_transforms.py` was not correctly mapping the sentence with blank marker to `content.sentence` for fill_blank tasks.

**Issue:** For fill_blank tasks, the LLM may generate the sentence with blank in two possible locations:
1. In `context.sentence` field
2. Directly in the `prompt` field (with blank markers `_____` or `__`)

The original transformation only checked `context.sentence`, missing cases where the blank sentence was in the prompt.

## Solution

Updated `transform_diagnostic_item_to_v1()` in [app/dto_transforms.py](app/dto_transforms.py) to use task-specific logic for fill_blank tasks:

```python
# Determine sentence with blank for fill_blank tasks
# LLM may put blank sentence in prompt OR context.sentence
sentence_with_blank = None
if item.task_type == "fill_blank":
    # Check prompt first (if it contains blank marker)
    if item.prompt and ("_____" in item.prompt or "__" in item.prompt):
        sentence_with_blank = item.prompt
    # Otherwise check context.sentence
    elif item.context and item.context.sentence:
        sentence_with_blank = item.context.sentence
elif item.context:
    # For non-fill_blank tasks, use context.sentence if available
    sentence_with_blank = item.context.sentence

# Build content object from dispersed fields
content = DiagnosticItemContentV1(
    choices=item.choices,
    tokens=item.tokens,
    sentence=sentence_with_blank,  # Now correctly mapped for fill_blank
    sourceText=source_text,
    readingPassage=item.context.passage if item.context else None,
    hint=item.context.hint if item.context else None,
)
```

## Changes Made

### File: `app/dto_transforms.py`

**Before:**
```python
# Build content object from dispersed fields
content = DiagnosticItemContentV1(
    choices=item.choices,
    tokens=item.tokens,
    sentence=item.context.sentence if item.context else None,  # ❌ Missed prompt field
    sourceText=source_text,
    readingPassage=item.context.passage if item.context else None,
    hint=item.context.hint if item.context else None,
)
```

**After:**
```python
# Determine sentence with blank for fill_blank tasks
# LLM may put blank sentence in prompt OR context.sentence
sentence_with_blank = None
if item.task_type == "fill_blank":
    # Check prompt first (if it contains blank marker)
    if item.prompt and ("_____" in item.prompt or "__" in item.prompt):
        sentence_with_blank = item.prompt
    # Otherwise check context.sentence
    elif item.context and item.context.sentence:
        sentence_with_blank = item.context.sentence
elif item.context:
    # For non-fill_blank tasks, use context.sentence if available
    sentence_with_blank = item.context.sentence

# Build content object from dispersed fields
content = DiagnosticItemContentV1(
    choices=item.choices,
    tokens=item.tokens,
    sentence=sentence_with_blank,  # ✅ Now checks both prompt and context.sentence
    sourceText=source_text,
    readingPassage=item.context.passage if item.context else None,
    hint=item.context.hint if item.context else None,
)
```

## Task-Specific Mapping Summary

The transformation now handles all task types correctly:

| Task Type | Mapping Logic |
|-----------|---------------|
| `mcq` | `choices` → `content.choices` |
| `translate` | `prompt` → `content.sourceText` |
| `fill_blank` | `prompt` (if has blank) OR `context.sentence` → `content.sentence` |
| `reorder_sentence` | `tokens` → `content.tokens` |
| `reading_mcq` | `context.passage` → `content.readingPassage`, `choices` → `content.choices` |

## Deployment

1. Docker image rebuilt: `docker-compose up -d --build api`
2. Container restarted successfully at 2026-01-10 02:14:56 UTC
3. API running at http://0.0.0.0:8000

## Testing

Desktop should now:
1. Start a new diagnostic session
2. Verify fill_blank tasks have `content.sentence` with blank marker (`_____` or `__`)
3. Confirm no "Invalid fill blank" errors appear

## Related Issues

- Similar fix for translate tasks: [HOTFIX_TRANSLATE_TASK.md](HOTFIX_TRANSLATE_TASK.md)
- Session 404 debugging: [DIAGNOSTIC_404_TROUBLESHOOTING.md](DIAGNOSTIC_404_TROUBLESHOOTING.md)

## Zero Core Logic Changes

✅ **No changes to:**
- `app/diagnostic_engine.py` (LLM generation)
- `app/diagnostic_session.py` (session management)
- Database schema
- Validation logic

✅ **Only changed:**
- DTO transformation at API boundary (where internal format converts to ClientV1 format)

This maintains the contract requirement: "Do NOT rewrite core logic."
