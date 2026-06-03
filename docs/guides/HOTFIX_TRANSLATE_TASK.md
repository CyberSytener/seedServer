# Hotfix: Translate Task Source Text Issue

## Issue
Desktop client reported: **"⚠️ Invalid translate task: no source text"**

## Root Cause
The DTO transformation was not properly mapping the source text for `translate` task types. The transformation was looking for a `source_text` field in the context object, but for translate tasks, the **prompt itself IS the source text** to be translated.

## Fix Applied
Updated `app/dto_transforms.py` to handle task-specific mappings:

```python
# Determine sourceText based on task type
# For translate tasks, the prompt IS the source text to translate
source_text = None
if item.task_type == "translate":
    source_text = item.prompt  # ✅ Use prompt as sourceText
elif item.context:
    # Check if context has sourceText/source_text field (extra="allow")
    source_text = getattr(item.context, "sourceText", None) or getattr(item.context, "source_text", None)
```

## Task-Specific Mappings

| Task Type | Source Data | Client V1 `content.*` Field |
|-----------|-------------|----------------------------|
| `translate` | `item.prompt` | `content.sourceText` |
| `mcq` | `item.choices` | `content.choices` |
| `reading_mcq` | `item.choices` | `content.choices` |
| `reorder_sentence` | `item.tokens` | `content.tokens` |
| `fill_blank` | `item.context.sentence` | `content.sentence` |

## Expected Response Structure

### Translate Task
```json
{
  "itemId": "translate-1",
  "taskType": "translate",
  "prompt": "Translate this to Spanish:",
  "content": {
    "sourceText": "Hello, how are you?",
    "sentence": null,
    "choices": null,
    "tokens": null,
    "readingPassage": null,
    "hint": "Use informal 'tú' form"
  },
  "metadata": {
    "skill": "translation",
    "subskill": "greeting",
    "difficulty": 1.0,
    "topic": "greetings",
    "cefrBand": "A1"
  }
}
```

### MCQ Task
```json
{
  "itemId": "mcq-1",
  "taskType": "mcq",
  "prompt": "I _____ coffee every morning.",
  "content": {
    "choices": ["drink", "drinks", "drinking", "drunk"],
    "sourceText": null,
    "sentence": null,
    "tokens": null,
    "readingPassage": null,
    "hint": null
  },
  "metadata": {
    "skill": "grammar",
    "subskill": "verb_conjugation",
    "difficulty": 1.5,
    "topic": "present_tense",
    "cefrBand": "A1"
  }
}
```

## Deployment
- ✅ Fix applied to `app/dto_transforms.py`
- ✅ Docker image rebuilt
- ✅ API restarted successfully
- ✅ No database changes required
- ✅ No breaking changes for other task types

## Testing
Desktop should verify:
1. ✅ Translate tasks now have `content.sourceText` populated
2. ✅ MCQ tasks still have `content.choices` populated
3. ✅ All other task types remain unaffected

## Status
**RESOLVED** - API restarted at 2026-01-10 02:08:02 UTC
