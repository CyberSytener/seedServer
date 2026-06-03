# Lesson Thread Management Endpoints

This document describes the lesson thread management endpoints that support desktop UX with multiple lesson threads.

## Endpoints

### 1. GET /v1/lessons

List all lessons for the authenticated user with minimal metadata.

**Request:**
```http
GET /v1/lessons
Authorization: Bearer <api_key>
```

**Response:**
```json
{
  "lessons": [
    {
      "lessonId": "lesson_mh3HXrNSOq0Sog",
      "title": "Basic Spanish Vocabulary",
      "nativeLang": "English",
      "targetLang": "Spanish",
      "level": "A1",
      "mode": "vocabulary",
      "createdAt": "2026-01-09T03:43:15.891552+00:00",
      "personaIdUsed": "classic_tutor",
      "tasksCount": 3,
      "completedCount": 0
    }
  ],
  "total": 1
}
```

**Fields:**
- `lessonId`: Unique lesson identifier
- `title`: Lesson title (from LLM generation)
- `nativeLang`: User's native language (e.g., "English")
- `targetLang`: Target language being learned (e.g., "Spanish")
- `level`: CEFR level (A1, A2, B1, B2, C1, C2)
- `mode`: Lesson mode (vocabulary, grammar, listening, translation)
- `createdAt`: ISO 8601 timestamp of lesson creation
- `personaIdUsed`: Persona that generated the lesson
- `tasksCount`: Total number of tasks in the lesson
- `completedCount`: Number of tasks completed correctly

**Security:**
- Only returns lessons for the authenticated user
- 401 Unauthorized if invalid/missing API key

**Example:**
```powershell
$headers = @{ "Authorization" = "Bearer seed_abc123..." }
$list = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons" -Headers $headers
Write-Host "Total lessons: $($list.total)"
```

---

### 2. GET /v1/lessons/{lessonId}

Get a specific lesson with full details and all attempts.

**Request:**
```http
GET /v1/lessons/{lessonId}
Authorization: Bearer <api_key>
```

**Response:**
```json
{
  "lesson": {
    "lessonId": "lesson_mh3HXrNSOq0Sog",
    "mode": "vocabulary",
    "targetLang": "Spanish",
    "nativeLang": "English",
    "level": "A1",
    "topic": "Basic Greetings",
    "title": "Basic Spanish Vocabulary",
    "tasks": [
      {
        "id": "task_1",
        "type": "mcq",
        "prompt": "What does 'hola' mean?",
        "skill": "vocabulary",
        "difficulty": "easy",
        "content": {
          "choices": ["Hello", "Goodbye", "Please", "Thanks"]
        },
        "grading": {
          "correctChoiceIndex": 0,
          "correctAnswer": "Hello",
          "tip": "Hola is a common Spanish greeting"
        }
      }
    ]
  },
  "attempts": [
    {
      "taskId": "task_1",
      "userAnswer": "test",
      "correct": false,
      "score": 0,
      "createdAt": "2026-01-09T03:43:32.957469+00:00"
    }
  ],
  "totalAttempts": 1,
  "completedCount": 0,
  "totalScore": 0,
  "personaIdUsed": "classic_tutor"
}
```

**Fields:**
- `lesson`: Full lesson object with all tasks
- `attempts`: All submission attempts for this lesson
  - `taskId`: Task identifier
  - `userAnswer`: User's submitted answer
  - `correct`: Whether the answer was correct
  - `score`: Points earned (0-100)
  - `createdAt`: ISO 8601 timestamp of attempt
- `totalAttempts`: Total number of attempts made
- `completedCount`: Number of tasks completed correctly (unique task_ids with correct=true)
- `totalScore`: Sum of all scores
- `personaIdUsed`: Persona that generated the lesson

**Security:**
- Only returns lesson if it belongs to the authenticated user
- 404 Not Found if lesson doesn't exist or belongs to another user
- 400 Bad Request if lessonId format is invalid (must match `^[a-zA-Z0-9_-]{1,100}$`)

**Example:**
```powershell
$lessonId = "lesson_mh3HXrNSOq0Sog"
$details = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/$lessonId" -Headers $headers
Write-Host "Tasks: $($details.lesson.tasks.Count)"
Write-Host "Attempts: $($details.totalAttempts)"
Write-Host "Completed: $($details.completedCount)"
```

---

### 3. DELETE /v1/lessons/{lessonId}

Delete a lesson and all its attempts.

**Request:**
```http
DELETE /v1/lessons/{lessonId}
Authorization: Bearer <api_key>
```

**Response:**
```json
{
  "deleted": true,
  "lessonId": "lesson_mh3HXrNSOq0Sog"
}
```

**Fields:**
- `deleted`: Always true on success
- `lessonId`: The deleted lesson identifier

**Security:**
- Only deletes lesson if it belongs to the authenticated user
- 404 Not Found if lesson doesn't exist or belongs to another user
- 400 Bad Request if lessonId format is invalid (must match `^[a-zA-Z0-9_-]{1,100}$`)

**Database Operations:**
- Deletes all lesson_attempts records for the lesson (CASCADE)
- Deletes the lesson record from lessons table
- Atomic operation (both or neither)

**Example:**
```powershell
$lessonId = "lesson_mh3HXrNSOq0Sog"
$delete = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/$lessonId" -Method DELETE -Headers $headers
Write-Host "Deleted: $($delete.deleted)"
```

---

## Security

All endpoints enforce user_id matching:
- Users can only see their own lessons
- Users can only delete their own lessons
- Cross-user access returns 404 (not 403) to avoid information leakage

**Example - Security Test:**
```powershell
# User1 creates a lesson
$user1 = Invoke-RestMethod -Uri "http://localhost:8000/v1/users" -Method POST -Body '{"username":"user1"}' -ContentType "application/json"
$headers1 = @{ "Authorization" = "Bearer $($user1.api_key)" }
$lesson1 = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/generate" -Method POST -Headers $headers1 -Body '{"mode":"vocabulary","targetLang":"Spanish","nativeLang":"English","level":"A1","lessonLength":3}' -ContentType "application/json"
$lessonId1 = $lesson1.lesson.lessonId

# User2 tries to access User1's lesson (should fail with 404)
$user2 = Invoke-RestMethod -Uri "http://localhost:8000/v1/users" -Method POST -Body '{"username":"user2"}' -ContentType "application/json"
$headers2 = @{ "Authorization" = "Bearer $($user2.api_key)" }
try {
    $details = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/$lessonId1" -Headers $headers2
    Write-Host "ERROR: User2 accessed User1's lesson!"
} catch {
    Write-Host "✓ Security OK: User2 cannot access User1's lesson (404)"
}
```

---

## Logging

All operations emit structured JSON logs:

**List Lessons:**
```json
{
  "message": "Lessons listed",
  "user_id": "usr_o3WiQx_7EjVCvQ",
  "lessons_count": 1,
  "duration_ms": 0,
  "status": "ok"
}
```

**Fetch Lesson:**
```json
{
  "message": "Lesson fetched",
  "user_id": "usr_o3WiQx_7EjVCvQ",
  "lesson_id": "lesson_mh3HXrNSOq0Sog",
  "persona_id_used": "classic_tutor",
  "attempts_count": 1,
  "completed_count": 0,
  "duration_ms": 0,
  "status": "ok"
}
```

**Delete Lesson:**
```json
{
  "message": "Lesson deleted",
  "user_id": "usr_o3WiQx_7EjVCvQ",
  "lesson_id": "lesson_mh3HXrNSOq0Sog",
  "persona_id_used": "classic_tutor",
  "duration_ms": 0,
  "status": "ok"
}
```

**Monitoring:**
```bash
# Watch lesson operations in real-time
docker logs -f seed_server-api-1 | grep -E "Lessons listed|Lesson fetched|Lesson deleted"

# Count operations by type
docker logs seed_server-api-1 | grep "Lessons listed" | wc -l
docker logs seed_server-api-1 | grep "Lesson fetched" | wc -l
docker logs seed_server-api-1 | grep "Lesson deleted" | wc -l
```

---

## Database Schema

**lessons table:**
```sql
CREATE TABLE lessons (
  id TEXT PRIMARY KEY,                  -- lessonId (e.g., "lesson_mh3HXrNSOq0Sog")
  user_id TEXT NOT NULL,                -- Owner user_id
  lesson_json TEXT NOT NULL,            -- Full lesson JSON with tasks
  persona_id_used TEXT,                 -- Persona that generated lesson
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_lessons_user_id ON lessons(user_id);
```

**lesson_attempts table:**
```sql
CREATE TABLE lesson_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id TEXT NOT NULL,              -- References lessons(id)
  task_id TEXT NOT NULL,                -- Task identifier within lesson
  user_answer TEXT NOT NULL,            -- User's submitted answer
  correct INTEGER NOT NULL,             -- 1 if correct, 0 if wrong
  score REAL NOT NULL DEFAULT 0.0,      -- Points earned (0-100)
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(lesson_id) REFERENCES lessons(id) ON DELETE CASCADE
);

CREATE INDEX idx_lesson_attempts_lesson_id ON lesson_attempts(lesson_id);
```

**Foreign Key Behavior:**
- `ON DELETE CASCADE`: When a lesson is deleted, all its attempts are automatically deleted
- `PRAGMA foreign_keys=ON`: Enabled in schema initialization

---

## Desktop Integration

**Recommended UX Flow:**

1. **Lesson List Screen:**
   - Call `GET /v1/lessons` to show all available lessons
   - Display: title, targetLang, progress (completedCount/tasksCount)
   - Sort by createdAt DESC (newest first)
   - Show persona icon/badge

2. **Resume Lesson:**
   - Call `GET /v1/lessons/{lessonId}` to load full lesson
   - Find first incomplete task (task_id not in attempts with correct=true)
   - Show progress: completedCount/tasksCount, totalScore

3. **Delete Lesson:**
   - Confirm with user ("Delete this lesson and all progress?")
   - Call `DELETE /v1/lessons/{lessonId}`
   - Remove from UI immediately
   - Show toast: "Lesson deleted"

4. **Lesson Card Component:**
   ```typescript
   interface LessonCard {
     lessonId: string;
     title: string;
     targetLang: string;
     nativeLang: string;
     level: string;
     progress: {
       completed: number;
       total: number;
       percentage: number;  // completedCount / tasksCount * 100
     };
     personaIdUsed: string;
     createdAt: Date;
   }
   ```

5. **Polling for Updates:**
   - No polling needed - all data is on-demand
   - Refresh lesson list when user returns to list screen
   - Refresh lesson details when user resumes a lesson

---

## Testing

**PowerShell Test Script:**
```powershell
# Create user
$user = Invoke-RestMethod -Uri "http://localhost:8000/v1/users" -Method POST -Body '{"username":"test"}' -ContentType "application/json"
$headers = @{ "Authorization" = "Bearer $($user.api_key)" }

# List lessons (empty)
$list1 = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons" -Headers $headers
Write-Host "Empty list: $($list1.total) lessons"  # Should be 0

# Generate lesson
$lesson = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/generate" -Method POST -Headers $headers -Body '{"mode":"vocabulary","targetLang":"Spanish","nativeLang":"English","level":"A1","lessonLength":3}' -ContentType "application/json"
$lessonId = $lesson.lesson.lessonId
Write-Host "Created lesson: $lessonId"

# List lessons (1 lesson)
$list2 = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons" -Headers $headers
Write-Host "After creation: $($list2.total) lessons"  # Should be 1

# Get lesson details
$details = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/$lessonId" -Headers $headers
Write-Host "Tasks: $($details.lesson.tasks.Count)"
Write-Host "Attempts: $($details.totalAttempts)"

# Submit answer
$task1 = $lesson.lesson.tasks[0]
$submit = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/submit" -Method POST -Headers $headers -Body (@{lessonId=$lessonId; taskId=$task1.id; userAnswer="hello"} | ConvertTo-Json) -ContentType "application/json"
Write-Host "Submitted. Correct: $($submit.grade.correct)"

# Get lesson details (with attempts)
$details2 = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/$lessonId" -Headers $headers
Write-Host "Attempts after submission: $($details2.totalAttempts)"

# Delete lesson
$delete = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/$lessonId" -Method DELETE -Headers $headers
Write-Host "Deleted: $($delete.deleted)"

# List lessons (empty again)
$list3 = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons" -Headers $headers
Write-Host "After deletion: $($list3.total) lessons"  # Should be 0
```

**Expected Output:**
```
Empty list: 0 lessons
Created lesson: lesson_mh3HXrNSOq0Sog
After creation: 1 lessons
Tasks: 3
Attempts: 0
Submitted. Correct: True
Attempts after submission: 1
Deleted: True
After deletion: 0 lessons
```

---

## Error Handling

**Common Errors:**

1. **401 Unauthorized:**
   - Missing or invalid API key
   - Solution: Include valid `Authorization: Bearer <api_key>` header

2. **404 Not Found:**
   - Lesson doesn't exist
   - Lesson belongs to another user (security check)
   - Solution: Verify lessonId and user ownership

3. **400 Bad Request:**
   - Invalid lessonId format
   - Solution: Ensure lessonId matches `^[a-zA-Z0-9_-]{1,100}$`

4. **500 Internal Server Error:**
   - Database error
   - JSON parsing error
   - Solution: Check server logs with `docker logs seed_server-api-1`

**Error Response Format:**
```json
{
  "detail": "lesson_not_found"
}
```

---

## Performance

**Expected Latency:**
- `GET /v1/lessons`: < 10ms (SQLite query + JSON parsing)
- `GET /v1/lessons/{id}`: < 10ms (SQLite query + JSON parsing)
- `DELETE /v1/lessons/{id}`: < 20ms (2 DELETE queries)

**Scalability:**
- Indexed queries on `user_id` and `lesson_id`
- No N+1 queries - single JOIN for lesson list
- Efficient counting with `COUNT(DISTINCT la.task_id)`

**Database Size:**
- Average lesson JSON: 5-10 KB
- Average attempt record: 200 bytes
- 1000 lessons with 5 tasks each and 2 attempts per task = ~15 MB

---

## Implementation Details

**Files Modified:**

1. **app/models.py:**
   - Added `LessonListItem` model (minimal metadata)
   - Added `LessonListResponse` model (list + total)
   - Added `LessonAttemptInfo` model (attempt details)
   - Added `LessonGetResponse` model (full lesson + attempts + stats)
   - Added `LessonDeleteResponse` model (deleted flag + lessonId)

2. **app/db.py:**
   - Added `get_user_lessons(db, user_id)` - list with completion stats
   - Added `get_lesson_by_id(db, lesson_id, user_id)` - single lesson with security check
   - Added `get_lesson_attempts(db, lesson_id)` - all attempts for a lesson
   - Added `delete_lesson(db, lesson_id, user_id)` - delete lesson and attempts

3. **app/main.py:**
   - Added `GET /v1/lessons` endpoint
   - Added `GET /v1/lessons/{lesson_id}` endpoint
   - Added `DELETE /v1/lessons/{lesson_id}` endpoint
   - All endpoints include authentication, logging, error handling

**Code Quality:**
- Type hints throughout
- Structured JSON logging
- Pydantic validation
- Parameterized SQL queries (no SQL injection)
- Atomic transactions (commit after both deletes)
- Proper error handling with HTTPException

---

## Future Enhancements

Potential improvements:
1. **Pagination:** Add `?limit=10&offset=0` to `GET /v1/lessons`
2. **Filtering:** Add `?targetLang=Spanish&level=A1` query parameters
3. **Sorting:** Add `?sort=createdAt&order=desc` options
4. **Lesson Archives:** Soft delete with `archived=1` flag
5. **Lesson Statistics:** Add endpoint for aggregate stats (total_lessons, avg_score, etc.)
6. **Export Lesson:** Return lesson as PDF or CSV
7. **Duplicate Lesson:** Create a copy with new lessonId

---

## Support

For issues or questions:
1. Check server logs: `docker logs seed_server-api-1`
2. Verify authentication: `curl -H "Authorization: Bearer <key>" http://localhost:8000/v1/lessons`
3. Test with PowerShell script above
4. Review security checks (user_id matching)
