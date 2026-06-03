# Diagnostic V0 - Placement Test System

## Overview

The Diagnostic V0 system provides a complete placement test orchestration with session management, deterministic scoring, and CEFR level estimation. It generates 25 diagnostic items from a fixed blueprint and evaluates user performance to produce:

- **Estimated CEFR level** (A1, A2, B1, B2, C1)
- **Skill scores** (0-100 per skill: grammar, vocabulary, reading, writing)
- **Weak subskills** (top 3 areas needing improvement)
- **Complete attempt log** with tags snapshots

## Architecture

### Database Schema

**diagnostic_sessions**
- `id`: Session ID (diag_xxxxxxxxxxxxxxxx)
- `user_id`: User taking the test
- `native_lang`, `target_lang`: Language pair
- `start_level_guess`: Initial level guess (A1-C1)
- `status`: running, finished, abandoned
- `seed`: Random seed for reproducibility
- `created_at`, `finished_at`: Timestamps

**diagnostic_session_items**
- `session_id`: Foreign key
- `item_id`: Unique item identifier
- `item_json`: Full item data (JSON)
- `order_index`: Item position (0-24)
- `tags_json`: Metadata snapshot (skill, subskill, topic, difficulty, CEFR)
- `item_hash`: Deduplication hash

**diagnostic_attempts**
- `session_id`, `item_id`: Foreign keys
- `answer_raw`: User's raw answer
- `is_correct`: Boolean correctness
- `score`: 0.0 or 1.0
- `response_time_ms`: Time taken (optional)
- `tags_snapshot_json`: Item tags at time of attempt
- `created_at`: Timestamp

### Components

1. **Taxonomy** (`learning_taxonomy_v0_1.json`)
   - Skills: grammar, vocabulary, reading, writing
   - Subskills: verb_conjugation, articles, prepositions, etc.
   - Standard 25-item blueprint with progression A1→C1

2. **Session Engine** (`app/diagnostic_session.py`)
   - Session creation and lifecycle
   - Blueprint loading
   - Item generation (calls existing diagnostic_engine)
   - Answer evaluation
   - Scoring and CEFR estimation

3. **API Endpoints** (`app/main.py`)
   - Four RESTful endpoints under `/v1/learning/diagnostic/`

## API Endpoints

### 1. POST `/v1/learning/diagnostic/start`

Start a new diagnostic session.

**Request:**
```json
{
  "nativeLanguage": "English",
  "targetLanguage": "French",
  "startLevelGuess": "A2"
}
```

**Response:**
```json
{
  "sessionId": "diag_abc123def456",
  "totalItems": 25,
  "nextItem": {
    "id": "item_001",
    "type": "mcq",
    "prompt": "Complete: Je _____ français.",
    "choices": ["parle", "parles", "parlons", "parlent"],
    "answer": {
      "accepted": ["parle"],
      "normalize": "lower_trim"
    },
    "tags": {
      "skill": "grammar",
      "subskill": "verb_conjugation",
      "topic": "present_tense",
      "difficulty": 1.5,
      "taskType": "mcq",
      "cefrBand": "A1",
      "languagePair": "en->fr"
    }
  }
}
```

**Behavior:**
- Creates new session (status=running)
- Generates 25 items from fixed blueprint
- Stores items in database
- Returns first item to display

**Errors:**
- 401 Unauthorized
- 500 Internal server error

### 2. POST `/v1/learning/diagnostic/attempt`

Submit an answer for an item.

**Request:**
```json
{
  "sessionId": "diag_abc123def456",
  "itemId": "item_001",
  "userAnswerRaw": "parle",
  "responseTimeMs": 3500
}
```

**Response:**
```json
{
  "ok": true,
  "isCorrect": true,
  "correctAnswer": "parle"
}
```

**Behavior:**
- Validates session belongs to user
- Loads item from session
- Evaluates answer:
  - **MCQ/Reading MCQ**: Compares to `answer.accepted[0]`
  - **Fill blank/Translate**: Normalizes and checks all variants
  - **Reorder sentence**: Compares normalized joined string
- Stores attempt with correctness + score
- Returns immediate feedback

**Evaluation Rules:**
- Normalization: `lower_trim` (default), `exact`, `ignore_punctuation`
- Case-insensitive for `lower_trim`
- Multiple accepted variants supported
- Score: 1.0 if correct, 0.0 if incorrect

**Errors:**
- 404 session_not_found
- 404 item_not_found
- 400 session_not_running
- 401 Unauthorized

### 3. POST `/v1/learning/diagnostic/next`

Get the next unanswered item.

**Request:**
```json
{
  "sessionId": "diag_abc123def456"
}
```

**Response (more items):**
```json
{
  "complete": false,
  "item": { /* next DiagnosticItem */ },
  "index": 5,
  "totalItems": 25
}
```

**Response (all complete):**
```json
{
  "complete": true
}
```

**Behavior:**
- Queries unanswered items by order_index
- Returns first unanswered
- Returns `complete: true` if all answered

**Errors:**
- 404 session_not_found
- 401 Unauthorized

### 4. POST `/v1/learning/diagnostic/finish`

Finish session and get results.

**Request:**
```json
{
  "sessionId": "diag_abc123def456"
}
```

**Response:**
```json
{
  "estimatedCefr": "B1",
  "skillScores": {
    "grammar": 72,
    "vocabulary": 65,
    "reading": 80,
    "writing": 68
  },
  "weakSubskills": [
    {
      "subskill": "verb_conjugation",
      "skill": "grammar",
      "accuracy": 0.40,
      "suggestedFocus": "Needs focused review in verb conjugation"
    },
    {
      "subskill": "prepositions",
      "skill": "grammar",
      "accuracy": 0.50,
      "suggestedFocus": "Needs light reinforcement in prepositions"
    }
  ],
  "attemptsCount": 25,
  "itemsCount": 25
}
```

**Behavior:**
- Calculates results from all attempts
- Updates session status to "finished"
- Returns comprehensive results

**Scoring Logic:**
1. **Skill Scores**: Per-skill accuracy × 100
2. **Weak Subskills**: 
   - Requires ≥2 items per subskill
   - Selects accuracy < 0.6
   - Sorts by accuracy (weakest first)
   - Returns top 3 (or fewer if not enough data)
3. **CEFR Estimation**:
   - Considers accuracy AND average item difficulty
   - Difficulty-adjusted score = accuracy × (avg_difficulty / 3.0)
   - Mapping:
     - <0.30 → A1
     - 0.30-0.50 → A2
     - 0.50-0.70 → B1
     - 0.70-0.85 → B2
     - \>0.85 → C1

**Errors:**
- 404 session_not_found
- 401 Unauthorized

## Taxonomy Structure

The taxonomy defines:

### Skills & Subskills

**Grammar**
- verb_conjugation (present, past, future, perfect)
- articles (definite, indefinite, zero)
- prepositions (location, time, movement, abstract)
- pronouns (subject, object, possessive, reflexive)
- word_order (basic_svo, questions, negation, complex_clauses)
- adjective_agreement (gender, number, position)

**Vocabulary**
- common_words (greetings, numbers, colors, family, food)
- everyday_objects (home, clothes, transport, technology)
- verbs_daily_life (routines, hobbies, work, travel)
- academic_vocab (education, science, abstract_concepts)
- idiomatic_expressions (common_phrases, colloquialisms)

**Reading**
- literal_comprehension (factual_details, main_idea, sequence)
- inferential_comprehension (implicit_meaning, author_intent, tone)
- vocabulary_in_context (word_meaning, synonyms, context_clues)

**Writing**
- sentence_construction (basic, compound, complex sentences)
- spelling_mechanics (common_words, accents, capitalization)

### Standard Blueprint (25 items)

The blueprint progressively increases difficulty from A1 (items 1-5) through C1 (items 23-25):

- **Items 1-5**: A1 level (difficulty 1.0-1.5)
- **Items 6-10**: A2 level (difficulty 2.0-2.5)
- **Items 11-16**: B1 level (difficulty 3.0)
- **Items 17-22**: B2 level (difficulty 4.0-4.5)
- **Items 23-25**: C1 level (difficulty 4.5-5.0)

Task type distribution:
- MCQ: 8 items
- Fill blank: 4 items
- Translate: 5 items
- Reorder sentence: 5 items
- Reading MCQ: 3 items

## Usage Flow

### Client Implementation

```javascript
// 1. Start session
const startResp = await fetch('/v1/learning/diagnostic/start', {
  method: 'POST',
  headers: { 
    'Authorization': `Bearer ${apiKey}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    nativeLanguage: 'English',
    targetLanguage: 'French',
    startLevelGuess: 'A2'
  })
});
const { sessionId, totalItems, nextItem } = await startResp.json();

// 2. Display item and collect answer
let currentItem = nextItem;
let itemIndex = 0;

async function submitAnswer(userAnswer, timeMs) {
  // Submit attempt
  const attemptResp = await fetch('/v1/learning/diagnostic/attempt', {
    method: 'POST',
    headers: { 
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      sessionId,
      itemId: currentItem.id,
      userAnswerRaw: userAnswer,
      responseTimeMs: timeMs
    })
  });
  const { isCorrect, correctAnswer } = await attemptResp.json();
  
  // Show feedback
  showFeedback(isCorrect, correctAnswer);
  
  // Get next item
  const nextResp = await fetch('/v1/learning/diagnostic/next', {
    method: 'POST',
    headers: { 
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ sessionId })
  });
  const nextData = await nextResp.json();
  
  if (nextData.complete) {
    // All items completed - finish session
    await finishSession();
  } else {
    currentItem = nextData.item;
    itemIndex = nextData.index;
    displayItem(currentItem, itemIndex, totalItems);
  }
}

async function finishSession() {
  const finishResp = await fetch('/v1/learning/diagnostic/finish', {
    method: 'POST',
    headers: { 
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ sessionId })
  });
  const results = await finishResp.json();
  
  displayResults(results);
}
```

### Desktop App Integration

For Seed Desktop:

1. **Pre-flight**: Check auth, show instructions
2. **Test execution**: Call start → loop through attempt/next
3. **Results display**: Show CEFR, skill breakdown, recommendations
4. **Learning path**: Use weak_subskills to suggest content

## Logging

All operations are logged with structured JSON:

**Session Start:**
```json
{
  "message": "Diagnostic session started",
  "session_id": "diag_abc123",
  "user_id": "user_xyz",
  "native_lang": "English",
  "target_lang": "French",
  "items_count": 25,
  "duration_ms": 8500,
  "status": "ok"
}
```

**Attempt Recorded:**
```json
{
  "message": "Diagnostic attempt recorded",
  "session_id": "diag_abc123",
  "item_id": "item_003",
  "is_correct": true,
  "response_time_ms": 3200,
  "duration_ms": 12,
  "status": "ok"
}
```

**Session Finished:**
```json
{
  "message": "Diagnostic session finished",
  "session_id": "diag_abc123",
  "user_id": "user_xyz",
  "estimated_cefr": "B1",
  "attempts_count": 25,
  "items_count": 25,
  "duration_ms": 45,
  "status": "ok"
}
```

## Testing

### Unit Tests

Located in `tests/test_diagnostic_simple.py`:

- `test_normalize_answer`: Answer normalization
- `test_evaluate_mcq_correct`: MCQ evaluation
- `test_evaluate_mcq_case_insensitive`: Case handling
- `test_evaluate_translate_multiple_accepted`: Multiple variants
- `test_estimate_cefr_levels`: CEFR mapping
- `test_generate_focus_suggestion`: Focus generation

Run tests:
```bash
docker-compose exec api python tests/test_diagnostic_simple.py
```

### Manual Testing

1. **Start session**: POST to `/v1/learning/diagnostic/start`
2. **Verify item structure**: Check returned item has all required fields
3. **Submit correct answer**: Verify `isCorrect: true`
4. **Submit incorrect answer**: Verify `isCorrect: false` and `correctAnswer` shown
5. **Get next items**: Loop through all 25
6. **Finish session**: Verify CEFR estimation and skill scores

## Future Enhancements (V1+)

1. **Adaptive Selection**: Use CAT (Computer Adaptive Testing) to select next items based on performance
2. **Item Bank**: Expand beyond 25-item fixed blueprint
3. **Retry Logic**: Allow users to retake after cooldown period
4. **Detailed Analytics**: Item-level difficulty calibration, response time analysis
5. **Multi-language Support**: Expand taxonomy for more language pairs
6. **Partial Completion**: Resume abandoned sessions
7. **Progress Tracking**: Compare multiple attempts over time

## Database Queries

### Get all sessions for a user
```sql
SELECT * FROM diagnostic_sessions 
WHERE user_id = ? 
ORDER BY created_at DESC;
```

### Get session summary
```sql
SELECT 
  ds.id, ds.status, ds.native_lang, ds.target_lang,
  COUNT(DISTINCT da.item_id) as attempts_count,
  SUM(CASE WHEN da.is_correct = 1 THEN 1 ELSE 0 END) as correct_count
FROM diagnostic_sessions ds
LEFT JOIN diagnostic_attempts da ON ds.id = da.session_id
WHERE ds.id = ?
GROUP BY ds.id;
```

### Get weak areas for user
```sql
SELECT 
  json_extract(tags_snapshot_json, '$.skill') as skill,
  json_extract(tags_snapshot_json, '$.subskill') as subskill,
  AVG(is_correct) as accuracy,
  COUNT(*) as attempts
FROM diagnostic_attempts
WHERE session_id = ?
GROUP BY skill, subskill
HAVING attempts >= 2
ORDER BY accuracy ASC
LIMIT 5;
```

## Files

**Core Implementation:**
- `app/models.py`: Pydantic models for requests/responses
- `app/diagnostic_session.py`: Session engine with evaluation logic
- `app/main.py`: API endpoints
- `app/db.py`: Database schema
- `learning_taxonomy_v0_1.json`: Taxonomy and blueprint

**Tests:**
- `tests/test_diagnostic_session.py`: Pytest unit tests
- `tests/test_diagnostic_simple.py`: Simple Python tests (no pytest)

**Documentation:**
- `DIAGNOSTIC_V0.md`: This file
- `DIAGNOSTIC_ITEMS.md`: Diagnostic item generation

## Constraints & Design Decisions

1. **Fixed Blueprint**: V0 uses a predetermined 25-item sequence for simplicity and debugging
2. **Deterministic Scoring**: No probabilistic models, just accuracy-based
3. **Synchronous Generation**: Items generated at session start (not adaptive)
4. **Single Attempt**: Each item can be answered once (no retries)
5. **Session Isolation**: Items stored per-session (no cross-session item reuse)
6. **No Authentication on Items**: Items are public once session is created
7. **Simple CEFR Mapping**: Basic accuracy+difficulty formula (can be refined)

## Troubleshooting

**"session_not_found"**: Check sessionId matches and belongs to authenticated user

**"item_not_found"**: Verify itemId exists in session's items

**"session_not_running"**: Session was already finished or abandoned

**Items not generating**: Check LLM provider settings, API keys, and logs

**Incorrect CEFR estimate**: May need calibration with real user data

**Weak subskills empty**: Requires at least 2 items per subskill with <60% accuracy
