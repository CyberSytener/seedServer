# Learning Profile & Plan API Reference

## Diagnostic Enhancements

### POST `/v1/learning/diagnostic/finish`

**Enhanced Response (Backward Compatible):**
```json
{
  "estimatedCefr": "A1",
  "skillScores": {
    "grammar": 33,
    "vocabulary": 50
  },
  "weakSubskills": [
    {
      "subskill": "verb_conjugation",
      "skill": "grammar",
      "accuracy": 0.33,
      "suggestedFocus": "Practice present tense conjugations"
    }
  ],
  "attemptsCount": 5,          // Legacy field
  "itemsCount": 25,            // Legacy field
  "totalCorrect": 2,           // NEW: Desktop-friendly
  "totalAttempts": 5,          // NEW: Desktop-friendly
  "accuracy": 0.4              // NEW: 0.0-1.0 ratio
}
```

---

## Learning Profile Endpoints

### GET `/v1/learning/profile`

Get user's learning profile.

**Auth:** Required  
**Method:** GET  
**URL:** `/v1/learning/profile`

**Response: 200 OK**
```json
{
  "profile": {
    "version": 1,
    "targetLanguage": "es",
    "nativeLanguage": "en",
    "estimatedCefr": "A1",
    "skillScores": [
      {
        "skill": "grammar",
        "score": 33,
        "itemCount": 3
      },
      {
        "skill": "vocabulary",
        "score": 50,
        "itemCount": 2
      }
    ],
    "weakSubskills": [
      {
        "subskill": "verb_conjugation",
        "skill": "grammar",
        "accuracy": 0.33,
        "suggestedFocus": "Practice present tense conjugations"
      }
    ],
    "preferences": {
      "topic": "travel",
      "personaId": "classic_tutor",
      "lessonLength": 5
    },
    "history": {
      "diagnostics": [
        {
          "sessionId": "diag_xxx",
          "completedAt": "2026-01-10T07:18:34Z",
          "estimatedCefr": "A1",
          "totalCorrect": 2,
          "totalAttempts": 5,
          "accuracy": 0.4
        }
      ]
    },
    "updatedAt": "2026-01-10T07:18:34Z"
  }
}
```

**Response: 404 Not Found**
```json
{
  "detail": "profile_not_found"
}
```

---

### POST `/v1/learning/profile/upsert`

Create or replace entire learning profile.

**Auth:** Required  
**Method:** POST  
**URL:** `/v1/learning/profile/upsert`

**Request Body:**
```json
{
  "profile": {
    "version": 1,
    "targetLanguage": "es",
    "nativeLanguage": "en",
    "estimatedCefr": "A2",
    "skillScores": [...],
    "weakSubskills": [...],
    "preferences": {
      "topic": "business",
      "personaId": "code_mentor",
      "lessonLength": 7
    },
    "history": null,
    "updatedAt": "2026-01-10T07:18:34Z"
  }
}
```

**Response: 200 OK**
```json
{
  "ok": true,
  "updatedAt": "2026-01-10T07:18:34Z"
}
```

**Notes:**
- `updatedAt` is automatically set by server
- Full profile replacement (not a merge)
- Use PATCH for partial updates

---

### PATCH `/v1/learning/profile`

Merge updates into existing profile.

**Auth:** Required  
**Method:** PATCH  
**URL:** `/v1/learning/profile`

**Request Body (all fields optional):**
```json
{
  "targetLanguage": "fr",
  "nativeLanguage": "en",
  "preferences": {
    "topic": "business",
    "personaId": "code_mentor",
    "lessonLength": 7
  }
}
```

**Response: 200 OK**
```json
{
  "profile": {
    // Updated profile with merged changes
    "version": 1,
    "targetLanguage": "fr",    // Updated
    "nativeLanguage": "en",     // Updated
    "estimatedCefr": "A1",      // Unchanged
    "skillScores": [...],        // Unchanged
    "weakSubskills": [...],      // Unchanged
    "preferences": {             // Updated
      "topic": "business",
      "personaId": "code_mentor",
      "lessonLength": 7
    },
    "history": {...},
    "updatedAt": "2026-01-10T07:20:00Z"
  }
}
```

**Notes:**
- Creates new profile with defaults if none exists
- Only updates provided fields
- Returns complete updated profile

---

## Learning Plan Generation

### POST `/v1/learning/plan/generate`

Generate structured learning plan based on diagnostic results.

**Auth:** Required  
**Method:** POST  
**URL:** `/v1/learning/plan/generate`

**Request Body:**
```json
{
  "targetLanguage": "es",      // Required
  "nativeLanguage": "en",      // Required
  "topic": "travel",           // Optional (default: "everyday_conversations")
  "sessionId": "diag_xxx",     // Optional: specific diagnostic session
  "estimatedCefr": "A2",       // Optional: override CEFR level
  "weakSubskills": [...],      // Optional: override weak areas
  "lessonLength": 5,           // Optional (default: 5)
  "personaId": "classic_tutor" // Optional
}
```

**Resolution Priority:**
1. If `sessionId` provided → use that session's results
2. Else if `estimatedCefr` + `weakSubskills` provided → use those
3. Else → use latest finished diagnostic for user
4. Else → use defaults (A2, generic weak areas)

**Response: 200 OK**
```json
{
  "planId": "plan_xxx",
  "profile": {
    // Full LearningProfile (created/updated)
    "version": 1,
    "targetLanguage": "es",
    "nativeLanguage": "en",
    "estimatedCefr": "A1",
    "skillScores": [...],
    "weakSubskills": [...],
    "preferences": {
      "topic": "travel",
      "personaId": "classic_tutor",
      "lessonLength": 5
    },
    "history": {
      "diagnostics": [...]
    },
    "updatedAt": "2026-01-10T07:18:34Z"
  },
  "plan": {
    "level": "A1",
    "focusAreas": [
      "grammar: verb_conjugation",
      "grammar: articles",
      "vocabulary: common_words"
    ],
    "recommendedLessons": [
      {
        "order": 1,
        "mode": "translate",
        "topic": "travel",
        "lessonLength": 5,
        "rationale": "Focus on grammar weakness identified in diagnostic",
        "tags": ["grammar", "a1", "foundational"]
      },
      {
        "order": 2,
        "mode": "fill_blank",
        "topic": "travel",
        "lessonLength": 5,
        "rationale": "Reinforce grammar with contextual practice",
        "tags": ["grammar", "a1", "contextual"]
      },
      // ... 5-7 lessons total
    ]
  },
  "firstLessonRequest": {
    // Ready-to-use payload for /v1/lessons/generate
    "mode": "translate",
    "targetLanguage": "es",
    "nativeLanguage": "en",
    "level": "A1",
    "topic": "travel",
    "lessonLength": 5,
    "personaId": "classic_tutor"
  }
}
```

**Side Effects:**
- Creates or updates user's learning profile
- Adds diagnostic history entry if `sessionId` provided

---

## Lesson Modes Reference

Generated plans include lessons with these modes:

- `translate` - Translate sentences between languages
- `fill_blank` - Fill in missing words in sentences
- `mcq` - Multiple choice questions
- `mixed` - Combination of multiple task types

---

## Error Responses

All endpoints may return:

**401 Unauthorized**
```json
{
  "detail": "missing api key"
}
```

**500 Internal Server Error**
```json
{
  "detail": "internal_server_error"
}
```

---

## Field Naming Convention

All API responses use **camelCase** for JSON fields:
- `userId` (not `user_id`)
- `targetLanguage` (not `target_language`)
- `estimatedCefr` (not `estimated_cefr`)

Pydantic models handle automatic conversion between Python snake_case and JSON camelCase.

---

## Complete Workflow Example

### 1. User Completes Diagnostic
```javascript
// Finish diagnostic
const finish = await fetch('/v1/learning/diagnostic/finish', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${apiKey}` },
  body: JSON.stringify({ sessionId: 'diag_xxx' })
});

const { totalCorrect, totalAttempts, accuracy, estimatedCefr } = await finish.json();

// Display: "Score: 2/5 (40%) - Estimated Level: A1"
console.log(`Score: ${totalCorrect}/${totalAttempts} (${accuracy * 100}%) - Level: ${estimatedCefr}`);
```

### 2. Generate Learning Plan
```javascript
const plan = await fetch('/v1/learning/plan/generate', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${apiKey}` },
  body: JSON.stringify({
    targetLanguage: 'es',
    nativeLanguage: 'en',
    sessionId: 'diag_xxx',
    topic: 'travel',
    lessonLength: 5,
    personaId: 'classic_tutor'
  })
});

const { planId, profile, plan: learningPlan, firstLessonRequest } = await plan.json();

// Show plan to user
console.log(`Plan ${planId} created for ${learningPlan.level}`);
console.log('Focus Areas:', learningPlan.focusAreas);
console.log('Recommended Lessons:', learningPlan.recommendedLessons.length);
```

### 3. Start First Lesson
```javascript
// Use firstLessonRequest directly
const lesson = await fetch('/v1/lessons/generate', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${apiKey}` },
  body: JSON.stringify(firstLessonRequest)
});

const { lesson: lessonData } = await lesson.json();
// Present lesson to user
```

### 4. View/Update Profile
```javascript
// Get current profile
const profile = await fetch('/v1/learning/profile', {
  headers: { 'Authorization': `Bearer ${apiKey}` }
});

const { profile: userData } = await profile.json();
console.log('Current Level:', userData.estimatedCefr);
console.log('Diagnostic History:', userData.history.diagnostics.length);

// Update preferences
const updated = await fetch('/v1/learning/profile', {
  method: 'PATCH',
  headers: { 'Authorization': `Bearer ${apiKey}` },
  body: JSON.stringify({
    preferences: {
      topic: 'business',
      personaId: 'code_mentor',
      lessonLength: 7
    }
  })
});

const { profile: updatedProfile } = await updated.json();
console.log('Updated preferences:', updatedProfile.preferences);
```

---

## Performance Characteristics

- **Profile GET:** <10ms (indexed query)
- **Profile PATCH:** <50ms (JSON update)
- **Plan Generate:** <100ms (rule-based, no LLM)
- **Profile Storage:** ~1-5KB per user (JSON)

---

## Version History

**v1.0 (2026-01-10)**
- Initial implementation
- Diagnostic finish enhancements
- Learning profile storage
- Learning plan generation
- History tracking

---

## Future Enhancements

**Planned:**
- LLM-powered personalized plan generation
- Plan progress tracking
- Adaptive difficulty adjustment
- Profile analytics and insights
- Multi-language profile support

**Under Consideration:**
- Profile export/import
- Teacher/tutor profile access
- Social learning features
- Achievement tracking
