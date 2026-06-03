# Diagnostic V0 - Quick Reference

## 🚀 Quick Start

### 1. Start a Diagnostic Session

```bash
POST /v1/learning/diagnostic/start
{
  "nativeLanguage": "English",
  "targetLanguage": "French",
  "startLevelGuess": "A2"
}
```

Returns: `sessionId`, `totalItems` (25), and first `nextItem`

### 2. Answer Items Loop

For each item (0-24):

```bash
# Submit answer
POST /v1/learning/diagnostic/attempt
{
  "sessionId": "diag_abc123",
  "itemId": "item_001",
  "userAnswerRaw": "user's answer",
  "responseTimeMs": 3500
}
# Returns: { ok, isCorrect, correctAnswer }

# Get next item
POST /v1/learning/diagnostic/next
{
  "sessionId": "diag_abc123"
}
# Returns: { complete, item, index, totalItems } or { complete: true }
```

### 3. Finish and Get Results

```bash
POST /v1/learning/diagnostic/finish
{
  "sessionId": "diag_abc123"
}
```

Returns:
- `estimatedCefr`: "A1" | "A2" | "B1" | "B2" | "C1"
- `skillScores`: { grammar: 72, vocabulary: 65, reading: 80, writing: 68 }
- `weakSubskills`: Top 3 areas needing work
- `attemptsCount`, `itemsCount`

## 📊 Scoring Logic

### CEFR Estimation
```
adjusted_score = accuracy × (avg_difficulty / 3.0)

< 0.30  → A1
0.30-0.50 → A2
0.50-0.70 → B1
0.70-0.85 → B2
> 0.85  → C1
```

### Skill Scores
Per-skill accuracy × 100 (e.g., 15/20 correct grammar items = 75)

### Weak Subskills
- Requires ≥2 items per subskill
- Selects accuracy < 60%
- Returns top 3 weakest

## 🎯 Task Types

| Type | Description | Example |
|------|-------------|---------|
| `mcq` | Multiple choice (4 options) | "Choose correct verb: ___" |
| `fill_blank` | Complete sentence | "She _____ to school." |
| `translate` | Translate phrase | "Translate: Hello" |
| `reorder_sentence` | Arrange words | ["Je", "mange", "une", "pomme"] |
| `reading_mcq` | Reading comprehension | Passage + question |

## ✅ Answer Evaluation

### Normalization Methods
- `lower_trim` (default): Lowercase + trim whitespace
- `exact`: Exact match required
- `ignore_punctuation`: Ignore punctuation differences

### Correctness
- User answer normalized and compared to ALL accepted variants
- Any match = correct (score: 1.0)
- No match = incorrect (score: 0.0)

## 📝 Item Structure

```json
{
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
```

## 🗂️ Database Tables

### `diagnostic_sessions`
- Session metadata, language pair, status, seed

### `diagnostic_session_items`
- 25 items per session, ordered 0-24
- Full item JSON + tags snapshot

### `diagnostic_attempts`
- User answers with correctness, score, timing
- Tags snapshot for analytics

## 📦 Files

```
app/
  models.py              # +9 diagnostic models
  diagnostic_session.py  # Session engine
  main.py                # +4 endpoints
  db.py                  # +3 tables

learning_taxonomy_v0_1.json  # Skills + 25-item blueprint
DIAGNOSTIC_V0.md             # Full documentation
tests/
  test_diagnostic_simple.py  # 6 unit tests
```

## 🔍 Debugging

### Check session status
```sql
SELECT * FROM diagnostic_sessions WHERE id = 'diag_abc123';
```

### Count attempts
```sql
SELECT COUNT(*) FROM diagnostic_attempts WHERE session_id = 'diag_abc123';
```

### View weak areas
```sql
SELECT 
  json_extract(tags_snapshot_json, '$.subskill') as subskill,
  AVG(is_correct) as accuracy
FROM diagnostic_attempts
WHERE session_id = 'diag_abc123'
GROUP BY subskill
ORDER BY accuracy ASC;
```

## 🚨 Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `session_not_found` | Invalid sessionId or wrong user | Check auth + sessionId |
| `item_not_found` | ItemId not in session | Verify itemId from session items |
| `session_not_running` | Session already finished | Start new session |
| 401 Unauthorized | Invalid/missing API key | Check Authorization header |

## 🎨 Frontend Integration

```javascript
// Start
const { sessionId, nextItem } = await startDiagnostic();

// Loop through items
for (let i = 0; i < 25; i++) {
  const answer = await getUserAnswer(nextItem);
  const { isCorrect, correctAnswer } = await submitAttempt(sessionId, nextItem.id, answer);
  showFeedback(isCorrect, correctAnswer);
  
  const nextData = await getNext(sessionId);
  if (nextData.complete) break;
  nextItem = nextData.item;
}

// Finish
const results = await finishSession(sessionId);
showResults(results); // CEFR, scores, recommendations
```

## 📈 Next Steps (V1+)

- [ ] Adaptive item selection (CAT)
- [ ] Expanded item bank (100+ items)
- [ ] Retry cooldown logic
- [ ] Multi-attempt tracking
- [ ] Item calibration from real data
- [ ] Resume abandoned sessions

## 📞 Support

See full documentation: `DIAGNOSTIC_V0.md`
