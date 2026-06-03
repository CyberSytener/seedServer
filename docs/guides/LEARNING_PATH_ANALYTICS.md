# Learning Path Analytics - User Performance Tracking

## 📊 Overview

Комплексная система сбора аналитики для Learning Path API, включающая:

- **Трекинг попыток** - детальная запись всех попыток прохождения нодов
- **Task-level analytics** - анализ успеха по типам заданий
- **Adaptive difficulty** - динамическая подстройка сложности
- **Leaderboards** - таблицы лидеров и геймификация
- **Performance insights** - рекомендации для улучшения

---

## 🗄️ Database Schema

### `node_attempts` - Попытки прохождения нодов

```sql
CREATE TABLE node_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  duration_seconds INTEGER,
  tasks_total INTEGER NOT NULL DEFAULT 0,
  tasks_correct INTEGER NOT NULL DEFAULT 0,
  tasks_incorrect INTEGER NOT NULL DEFAULT 0,
  score REAL NOT NULL DEFAULT 0.0,
  success INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
```

**Индексы:** node_id, user_id, session_id, completed_at

### `task_attempts` - Детальные попытки по задачам

```sql
CREATE TABLE task_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_attempt_id INTEGER NOT NULL,
  task_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  user_answer TEXT NOT NULL,
  correct_answer TEXT NOT NULL,
  is_correct INTEGER NOT NULL,
  response_time_ms INTEGER,
  hint_used INTEGER NOT NULL DEFAULT 0,
  attempts_count INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
```

**Индексы:** node_attempt_id, task_id, task_type, is_correct

---

## 📡 API Endpoints

### 1. Submit Node Completion

**`POST /v1/path/node/submit`**

Отправляет результаты прохождения нода.

**Request:**
```json
{
  "node_id": "node-abc-123",
  "session_id": "session-xyz-789",
  "started_at": "2026-01-12T10:00:00Z",
  "completed_at": "2026-01-12T10:15:00Z",
  "task_attempts": [
    {
      "task_id": "task_1",
      "task_type": "fill_blank",
      "user_answer": "vais",
      "correct_answer": "vais",
      "is_correct": true,
      "response_time_ms": 3500,
      "hint_used": false,
      "attempts_count": 1
    },
    {
      "task_id": "task_2",
      "task_type": "translate",
      "user_answer": "chat",
      "correct_answer": "le chat",
      "is_correct": false,
      "response_time_ms": 5200,
      "hint_used": true,
      "attempts_count": 2
    }
  ],
  "metadata": {
    "device": "mobile",
    "browser": "Chrome"
  }
}
```

**Response:**
```json
{
  "attempt_id": 12345,
  "node_id": "node-abc-123",
  "score": 0.86,
  "success": true,
  "stars_earned": 2,
  "next_node_unlocked": "node-def-456",
  "feedback": "Good job! You scored 86% and earned 2 stars. You're making solid progress."
}
```

**Stars System:**
- 🌟🌟🌟 (3 stars): Score >= 95%
- 🌟🌟 (2 stars): Score >= 85%
- 🌟 (1 star): Score >= 70%
- ⭐ (0 stars): Score < 70%

**Success Criteria:** Score >= 70%

---

### 2. Get User Analytics

**`GET /v1/path/analytics/user`**

Получить сводную статистику пользователя.

**Response:**
```json
{
  "user_id": "user-123",
  "units_started": 3,
  "units_completed": 1,
  "nodes_attempted": 15,
  "nodes_completed": 12,
  "total_tasks_attempted": 105,
  "total_tasks_correct": 87,
  "overall_accuracy": 0.83,
  "total_time_minutes": 180,
  "avg_session_duration_minutes": 15,
  "strongest_task_types": ["fill_blank", "choice", "translate"],
  "weakest_task_types": ["reorder", "match"],
  "current_streak_days": 5,
  "total_stars_earned": 34
}
```

---

### 3. Get Node Analytics

**`GET /v1/path/analytics/node/{node_id}`**

Получить детальную аналитику по конкретному ноду.

**Response:**
```json
{
  "node_id": "node-abc-123",
  "unit_id": "unit-xyz-789",
  "node_type": "lesson",
  "total_attempts": 47,
  "unique_users": 32,
  "avg_score": 0.78,
  "success_rate": 0.72,
  "avg_duration_seconds": 780,
  "completion_rate": 0.94,
  "task_type_breakdown": [
    {
      "task_type": "fill_blank",
      "total_attempts": 235,
      "correct_attempts": 189,
      "accuracy": 0.80,
      "avg_response_time_ms": 4200
    },
    {
      "task_type": "translate",
      "total_attempts": 188,
      "correct_attempts": 142,
      "accuracy": 0.76,
      "avg_response_time_ms": 6800
    }
  ],
  "common_errors": [
    {
      "task_id": "task_3",
      "user_answer": "va",
      "correct_answer": "vais",
      "frequency": 12
    }
  ],
  "difficulty_rating": "medium"
}
```

**Difficulty Ratings:**
- `easy`: Success rate >= 80%
- `medium`: Success rate 60-80%
- `hard`: Success rate < 60%

---

### 4. Get Leaderboard

**`GET /v1/path/leaderboard?period=weekly&limit=100`**

Получить таблицу лидеров.

**Query Parameters:**
- `period`: "daily", "weekly", "all_time" (default: "all_time")
- `limit`: Number of entries (default: 100)

**Response:**
```json
{
  "period": "weekly",
  "entries": [
    {
      "rank": 1,
      "user_id": "user-456",
      "display_name": null,
      "total_stars": 48,
      "nodes_completed": 16,
      "avg_score": 0.92,
      "total_time_minutes": 240
    },
    {
      "rank": 2,
      "user_id": "user-123",
      "display_name": null,
      "total_stars": 45,
      "nodes_completed": 15,
      "avg_score": 0.89,
      "total_time_minutes": 225
    }
  ],
  "user_rank": 2,
  "total_users": 150
}
```

---

## 🎯 Adaptive Difficulty System

### 5. Get Difficulty Adjustment

**`GET /v1/path/adaptive/difficulty?level=A2`**

Получить рекомендацию по сложности на основе недавней производительности.

**Response:**
```json
{
  "user_id": "user-123",
  "current_mastery_score": 0.82,
  "suggested_difficulty_delta": 0.05,
  "reasoning": "Good performance (82% avg). Gradual difficulty increase recommended.",
  "based_on_attempts": 10
}
```

**Mastery Score Calculation:**
- Weighted average of recent 10 attempts
- More recent attempts weighted higher (exponential decay)
- Clamped between 0.3 and 1.0

**Difficulty Adjustment Logic:**

| Success Rate | Avg Score | Delta | Reasoning |
|-------------|-----------|-------|-----------|
| >= 90% | >= 85% | +0.10 | Excellent - increase challenge |
| >= 70% | >= 75% | +0.05 | Good - gradual increase |
| >= 50% | - | 0.00 | Steady - maintain |
| >= 30% | - | -0.05 | Struggling - reduce difficulty |
| < 30% | - | -0.10 | Very difficult - review fundamentals |

---

### 6. Get Adaptive Recommendations

**`GET /v1/path/adaptive/recommendations?level=A2`**

Получить персонализированные рекомендации.

**Response:**
```json
{
  "user_id": "user-123",
  "recommended_topics": ["Business", "Travel", "Health"],
  "recommended_grammar": ["Past Simple", "Future (going to)", "Comparatives"],
  "difficulty_level": "Moderate",
  "focus_areas": [
    "Improve: translate, reorder",
    "Maintain: fill_blank, choice"
  ],
  "reasoning": "Steady progress. Balancing review with new material for optimal learning."
}
```

**Recommendation Strategy:**

| Mastery | Approach | Topics | Difficulty |
|---------|----------|--------|------------|
| < 0.6 | Review fundamentals | Previously completed | Beginner-friendly |
| 0.6-0.8 | Balanced (1 review + 2 new) | Mix of old and new | Moderate |
| > 0.8 | Advance | New challenging topics | Challenging |

---

## 💻 Client Integration Examples

### JavaScript/TypeScript

```typescript
interface NodeSubmission {
  node_id: string;
  session_id: string;
  started_at: string;
  completed_at: string;
  task_attempts: TaskAttempt[];
  metadata?: Record<string, any>;
}

interface TaskAttempt {
  task_id: string;
  task_type: string;
  user_answer: string;
  correct_answer: string;
  is_correct: boolean;
  response_time_ms?: number;
  hint_used?: boolean;
  attempts_count?: number;
}

class LearningPathTracker {
  private sessionId: string;
  private startTime: Date;
  private attempts: TaskAttempt[] = [];
  
  constructor(private nodeId: string, private apiKey: string) {
    this.sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    this.startTime = new Date();
  }
  
  recordAttempt(attempt: TaskAttempt) {
    this.attempts.push(attempt);
  }
  
  async submit(): Promise<any> {
    const submission: NodeSubmission = {
      node_id: this.nodeId,
      session_id: this.sessionId,
      started_at: this.startTime.toISOString(),
      completed_at: new Date().toISOString(),
      task_attempts: this.attempts,
      metadata: {
        device: navigator.userAgent,
        viewport: `${window.innerWidth}x${window.innerHeight}`
      }
    };
    
    const response = await fetch('/v1/path/node/submit', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${this.apiKey}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(submission)
    });
    
    return response.json();
  }
}

// Usage
const tracker = new LearningPathTracker('node-123', 'YOUR_API_KEY');

// User completes task
const startTime = Date.now();
const userAnswer = getUserAnswer();
const isCorrect = checkAnswer(userAnswer, correctAnswer);

tracker.recordAttempt({
  task_id: 'task_1',
  task_type: 'fill_blank',
  user_answer: userAnswer,
  correct_answer: correctAnswer,
  is_correct: isCorrect,
  response_time_ms: Date.now() - startTime
});

// After all tasks
const result = await tracker.submit();
console.log(`Score: ${result.score * 100}%`);
console.log(`Stars: ${result.stars_earned}`);
console.log(`Feedback: ${result.feedback}`);
```

### Python

```python
import asyncio
import httpx
from datetime import datetime
from typing import List, Dict, Any

class LearningPathTracker:
    def __init__(self, node_id: str, api_key: str, base_url: str = "http://localhost:8000"):
        self.node_id = node_id
        self.api_key = api_key
        self.base_url = base_url
        self.session_id = f"session_{int(datetime.now().timestamp())}"
        self.start_time = datetime.now()
        self.attempts: List[Dict] = []
    
    def record_attempt(
        self,
        task_id: str,
        task_type: str,
        user_answer: str,
        correct_answer: str,
        is_correct: bool,
        response_time_ms: int = None,
        hint_used: bool = False
    ):
        """Record a task attempt"""
        self.attempts.append({
            "task_id": task_id,
            "task_type": task_type,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "response_time_ms": response_time_ms,
            "hint_used": hint_used,
            "attempts_count": 1
        })
    
    async def submit(self) -> Dict:
        """Submit all attempts"""
        submission = {
            "node_id": self.node_id,
            "session_id": self.session_id,
            "started_at": self.start_time.isoformat() + "Z",
            "completed_at": datetime.now().isoformat() + "Z",
            "task_attempts": self.attempts,
            "metadata": {
                "environment": "python",
                "total_tasks": len(self.attempts)
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/path/node/submit",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=submission
            )
            response.raise_for_status()
            return response.json()
    
    async def get_user_analytics(self) -> Dict:
        """Get user's overall analytics"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v1/path/analytics/user",
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            return response.json()

# Usage
tracker = LearningPathTracker("node-123", "YOUR_API_KEY")

# Simulate task attempts
tracker.record_attempt(
    task_id="task_1",
    task_type="fill_blank",
    user_answer="vais",
    correct_answer="vais",
    is_correct=True,
    response_time_ms=3500
)

tracker.record_attempt(
    task_id="task_2",
    task_type="translate",
    user_answer="chat",
    correct_answer="le chat",
    is_correct=False,
    response_time_ms=5200,
    hint_used=True
)

# Submit
result = await tracker.submit()
print(f"Score: {result['score']*100:.0f}%")
print(f"Stars: {result['stars_earned']}")
print(f"Feedback: {result['feedback']}")

# Get analytics
analytics = await tracker.get_user_analytics()
print(f"Overall accuracy: {analytics['overall_accuracy']*100:.0f}%")
print(f"Total stars: {analytics['total_stars_earned']}")
```

---

## 📈 Analytics Use Cases

### 1. Student Dashboard

```typescript
async function loadStudentDashboard() {
  const analytics = await fetch('/v1/path/analytics/user', {
    headers: { 'Authorization': `Bearer ${apiKey}` }
  }).then(r => r.json());
  
  return {
    progress: `${analytics.nodes_completed}/${analytics.nodes_attempted} nodes`,
    accuracy: `${(analytics.overall_accuracy * 100).toFixed(0)}%`,
    timeSpent: `${analytics.total_time_minutes} minutes`,
    streak: `${analytics.current_streak_days} days`,
    stars: analytics.total_stars_earned,
    strengths: analytics.strongest_task_types.slice(0, 3),
    improvements: analytics.weakest_task_types.slice(0, 3)
  };
}
```

### 2. Teacher/Admin Dashboard

```python
async def analyze_node_difficulty(node_id: str) -> Dict:
    """Analyze if a node needs adjustment"""
    analytics = await get_node_analytics(node_id)
    
    issues = []
    
    if analytics['success_rate'] < 0.5:
        issues.append(f"Low success rate: {analytics['success_rate']*100:.0f}%")
    
    if analytics['completion_rate'] < 0.7:
        issues.append(f"Many users quit: {analytics['completion_rate']*100:.0f}% complete")
    
    if analytics['avg_duration_seconds'] > 900:  # 15 min
        issues.append(f"Takes too long: {analytics['avg_duration_seconds']/60:.0f} minutes")
    
    # Check if regeneration needed
    regen_check = await check_regeneration(node_id)
    
    return {
        "node_id": node_id,
        "difficulty": analytics['difficulty_rating'],
        "issues": issues,
        "should_regenerate": regen_check['should_regenerate'],
        "recommendations": generate_recommendations(analytics, issues)
    }
```

### 3. Adaptive Learning Flow

```typescript
async function getNextRecommendedNode(userId: string, currentLevel: string) {
  // Get adaptive recommendations
  const recommendations = await fetch(
    `/v1/path/adaptive/recommendations?level=${currentLevel}`,
    { headers: { 'Authorization': `Bearer ${apiKey}` } }
  ).then(r => r.json());
  
  // Get difficulty adjustment
  const difficulty = await fetch(
    `/v1/path/adaptive/difficulty?level=${currentLevel}`,
    { headers: { 'Authorization': `Bearer ${apiKey}` } }
  ).then(r => r.json());
  
  // Generate next unit with adjusted difficulty
  const blueprint = await fetch('/v1/path/unit/generate_blueprint', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      user_profile: {
        level: currentLevel,
        interests: recommendations.recommended_topics,
        mastery_score: difficulty.current_mastery_score,
        target_lang: "French",
        native_lang: "English"
      },
      context: `Adaptive: ${difficulty.reasoning}`
    })
  }).then(r => r.json());
  
  return blueprint;
}
```

---

## 🔧 Configuration & Best Practices

### Performance Recommendations

1. **Batch Submissions**: Submit after node completion, not per-task
2. **Session IDs**: Use unique client-generated IDs for deduplication
3. **Timestamps**: Always use ISO 8601 format with timezone
4. **Metadata**: Include device/browser info for debugging

### Privacy Considerations

- User IDs are stored but display names are optional
- Individual answers are stored for analytics but can be anonymized
- Leaderboards don't expose personal information by default
- GDPR compliance: users can request data export/deletion

### Monitoring

```sql
-- Check recent submission rate
SELECT 
  DATE(completed_at) as date,
  COUNT(*) as submissions,
  AVG(score) as avg_score
FROM node_attempts
WHERE completed_at >= DATE('now', '-7 days')
GROUP BY DATE(completed_at);

-- Identify problematic nodes
SELECT
  node_id,
  COUNT(*) as attempts,
  AVG(score) as avg_score,
  SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as success_rate
FROM node_attempts
GROUP BY node_id
HAVING attempts >= 10 AND success_rate < 0.5
ORDER BY success_rate ASC;
```

---

## 📊 Metrics Dashboard

Recommended metrics to track:

| Metric | Query | Alert Threshold |
|--------|-------|-----------------|
| Daily Active Users | `SELECT COUNT(DISTINCT user_id) FROM node_attempts WHERE DATE(started_at) = DATE('now')` | < 100 |
| Avg Completion Rate | `SELECT AVG(CASE WHEN completed_at IS NOT NULL THEN 1.0 ELSE 0.0 END) FROM node_attempts` | < 0.8 |
| Success Rate | `SELECT AVG(success) FROM node_attempts` | < 0.6 |
| Avg Response Time | `SELECT AVG(response_time_ms) FROM task_attempts` | > 8000ms |
| Nodes Needing Regen | Count from `should_regenerate_node` | > 5 |

---

## ✅ Testing

```bash
# Run all analytics tests
pytest test_path_analytics.py -v

# Run specific test category
pytest test_path_analytics.py::TestAnalyticsCalculations -v

# Check database schema
python check_schema.py
python check_analytics.py
```

---

## 🚀 Next Features

1. **Real-time Progress** - WebSocket updates during node completion
2. **Achievements System** - Badges for milestones
3. **Social Features** - Friend leaderboards, challenges
4. **Export Analytics** - CSV/JSON export for external analysis
5. **A/B Testing** - Test different node configurations
6. **Predictive Analytics** - ML models for success prediction

---

**Questions?** Check [LEARNING_PATH_API.md](LEARNING_PATH_API.md) for complete API documentation.
