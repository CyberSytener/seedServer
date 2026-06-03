# Diagnostic Items Feature

## Overview

The diagnostic items feature generates language learning assessment items with detailed metadata, distractor analysis, and flexible task types. This system is designed for placement tests, progress assessments, and skill diagnostics.

## Key Differences from Lessons

| Feature | Lessons | Diagnostic Items |
|---------|---------|------------------|
| Structure | `content` + `grading` nested objects | Flat structure with `choices`, `answer`, `tags` |
| Task Types | mcq, translate, fill_blank, word_order | mcq, fill_blank, reorder_sentence, translate, reading_mcq |
| Metadata | Basic skill/difficulty | Rich tags: skill, subskill, topic, CEFR band, language pair |
| Answers | Single `correctAnswer` | Multiple accepted variants with normalization |
| Distractors | None | Detailed `distractorsReason` with error tags |
| Context | Embedded in content | Separate `context` object |

## Schema

### Diagnostic Item Structure

```json
{
  "id": "item_001",
  "type": "mcq",
  "prompt": "Complete: Je _____ au cinéma.",
  "context": {
    "sentence": "Je vais au cinéma.",
    "hint": "Present tense"
  },
  "choices": [
    "vais",
    "va",
    "aller",
    "allons"
  ],
  "answer": {
    "accepted": ["vais"],
    "normalize": "lower_trim"
  },
  "distractorsReason": [
    {"choice": "va", "reasonTag": "agreement"},
    {"choice": "aller", "reasonTag": "tense_confusion"},
    {"choice": "allons", "reasonTag": "agreement"}
  ],
  "tags": {
    "skill": "grammar",
    "subskill": "verb_conjugation",
    "topic": "present_tense",
    "difficulty": 2.5,
    "task_type": "mcq",
    "cefr_band": "A2",
    "languagePair": "en->fr"
  }
}
```

## API Endpoint

### POST `/v1/diagnostics/generate`

Generate diagnostic items based on blueprint specifications.

**Request:**

```json
{
  "nativeLang": "English",
  "targetLang": "French",
  "blueprint": [
    {
      "skill": "grammar",
      "subskill": "verb_conjugation",
      "topic": "present_tense",
      "difficulty": 2.0,
      "taskType": "mcq",
      "cefrBand": "A2"
    },
    {
      "skill": "vocabulary",
      "subskill": "common_words",
      "topic": "food",
      "difficulty": 1.5,
      "taskType": "translate",
      "cefrBand": "A1"
    }
  ],
  "personaId": "classic_tutor"
}
```

**Response:**

```json
{
  "diagnosticSet": {
    "items": [
      {
        "id": "diag_001",
        "type": "mcq",
        "prompt": "Choose the correct conjugation:",
        "choices": ["mange", "manger", "manges", "mangent"],
        "answer": {
          "accepted": ["mange"],
          "normalize": "lower_trim"
        },
        "tags": {
          "skill": "grammar",
          "difficulty": 2.0,
          "cefrBand": "A2"
        }
      }
    ]
  },
  "personaIdUsed": "classic_tutor",
  "fallbackReason": null
}
```

## Task Types

### 1. MCQ (Multiple Choice Question)

Choose one correct answer from 4 options.

```json
{
  "type": "mcq",
  "prompt": "Select the correct preposition:",
  "choices": ["à", "de", "en", "pour"],
  "answer": {"accepted": ["à"]},
  "distractorsReason": [
    {"choice": "de", "reasonTag": "preposition_error"},
    {"choice": "en", "reasonTag": "preposition_error"},
    {"choice": "pour", "reasonTag": "false_meaning"}
  ]
}
```

### 2. Fill Blank

Complete a sentence with missing word(s).

```json
{
  "type": "fill_blank",
  "prompt": "Complete the sentence:",
  "context": {
    "sentence": "She _____ to school every day."
  },
  "answer": {
    "accepted": ["goes", "walks", "drives"],
    "normalize": "lower_trim"
  }
}
```

### 3. Reorder Sentence

Arrange words in correct order.

```json
{
  "type": "reorder_sentence",
  "prompt": "Put the words in order:",
  "tokens": ["Je", "mange", "une", "pomme"],
  "answer": {
    "accepted": ["Je mange une pomme"],
    "normalize": "lower_trim"
  }
}
```

### 4. Translate

Translate from source to target language.

```json
{
  "type": "translate",
  "prompt": "Translate to French:",
  "context": {
    "sentence": "Hello, how are you?"
  },
  "answer": {
    "accepted": [
      "Bonjour, comment allez-vous?",
      "Bonjour, comment vas-tu?",
      "Salut, comment vas-tu?"
    ],
    "normalize": "lower_trim"
  }
}
```

### 5. Reading MCQ

Answer questions about a passage.

```json
{
  "type": "reading_mcq",
  "prompt": "What is the main idea?",
  "context": {
    "passage": "Marie lives in Paris. She works at a bakery. Every morning, she makes fresh bread for the customers."
  },
  "choices": [
    "Marie's job",
    "How to make bread",
    "Paris landmarks",
    "Customer service"
  ],
  "answer": {"accepted": ["Marie's job"]}
}
```

## Blueprint Structure

Each blueprint entry specifies what kind of item to generate:

```json
{
  "skill": "grammar|vocabulary|reading|writing",
  "subskill": "specific_area (e.g., verb_conjugation)",
  "topic": "content_area (e.g., present_tense)",
  "difficulty": 0.0-5.0,
  "taskType": "mcq|fill_blank|reorder_sentence|translate|reading_mcq",
  "cefrBand": "A1|A2|B1|B2|C1"
}
```

## Distractor Reason Tags

Common error tags for wrong choices:

- `tense_confusion` - Wrong tense used
- `article_omission` - Missing article
- `article_error` - Wrong article
- `preposition_error` - Wrong preposition
- `word_order` - Incorrect word order
- `false_friend` - False cognate
- `spelling` - Spelling mistake
- `agreement` - Gender/number agreement error
- `false_meaning` - Wrong meaning/context
- `literal_translation` - Too literal translation

## Answer Normalization

The `normalize` field in `answer` controls how user responses are compared:

- `lower_trim` - Lowercase and trim whitespace (default)
- `exact` - Exact match required
- `ignore_punctuation` - Ignore punctuation differences

## Usage Example

```bash
# Generate 5 diagnostic items
curl -X POST http://localhost:8000/v1/diagnostics/generate \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "nativeLang": "English",
    "targetLang": "Spanish",
    "blueprint": [
      {
        "skill": "grammar",
        "subskill": "ser_estar",
        "topic": "descriptive_adjectives",
        "difficulty": 2.5,
        "taskType": "mcq",
        "cefrBand": "A2"
      },
      {
        "skill": "vocabulary",
        "subskill": "common_verbs",
        "topic": "daily_activities",
        "difficulty": 1.5,
        "taskType": "translate",
        "cefrBand": "A1"
      }
    ]
  }'
```

## Integration Notes

1. **Validation**: The server validates that:
   - MCQ items have exactly 4 choices
   - MCQ items have exactly 3 distractor reasons
   - Reorder_sentence has tokens array
   - All items have required tags
   - Difficulty is 0.0-5.0

2. **Persona Support**: Diagnostic generation uses the same persona system as lessons for consistent tone.

3. **Logging**: All generations are logged with structured JSON including:
   - User ID
   - Language pair
   - Item count
   - Persona used
   - Duration

4. **Error Handling**: Returns 502 on validation errors with specific error messages.

## Frontend Implementation

When rendering diagnostic items:

```javascript
function renderDiagnosticItem(item) {
  switch(item.type) {
    case 'mcq':
    case 'reading_mcq':
      return <MultipleChoice item={item} />;
    case 'fill_blank':
      return <FillBlank sentence={item.context.sentence} />;
    case 'reorder_sentence':
      return <ReorderTokens tokens={item.tokens} />;
    case 'translate':
      return <Translation source={item.context.sentence} />;
  }
}
```

## Testing

Test the endpoint:

```python
import requests

response = requests.post(
    "http://localhost:8000/v1/diagnostics/generate",
    headers={"Authorization": "Bearer YOUR_KEY"},
    json={
        "nativeLang": "English",
        "targetLang": "French",
        "blueprint": [
            {
                "skill": "grammar",
                "subskill": "articles",
                "topic": "definite_articles",
                "difficulty": 1.0,
                "taskType": "mcq",
                "cefrBand": "A1"
            }
        ]
    }
)

print(response.json())
```

## Files Changed

1. **app/models.py**: Added diagnostic models (DiagnosticItem, DiagnosticGenerateRequest, DiagnosticResponse, etc.)
2. **app/diagnostic_engine.py**: Created validation and generation logic
3. **prompts/diagnostic_generator.md**: Added LLM prompt for item generation
4. **app/main.py**: Added `/v1/diagnostics/generate` endpoint

## Next Steps

Consider adding:
- `/v1/diagnostics/validate` - Validate user answers
- `/v1/diagnostics/score` - Score diagnostic sets
- Database storage for diagnostic results
- Adaptive testing algorithms based on responses
