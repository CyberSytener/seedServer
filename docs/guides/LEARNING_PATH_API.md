# Learning Path API - Blueprint Pattern

## 📖 Overview

The Learning Path API implements a two-phase generation pattern to create personalized language learning curricula:

- **Phase A (Blueprint):** Generate curriculum structure (10-12 nodes) with metadata only
- **Phase B (Content):** Generate actual tasks when user starts a node

This separation prevents AI hallucinations, reduces database size, and enables dynamic difficulty adjustment.

---

## 🏗️ Architecture

```
User completes Placement Test
         ↓
    Phase A: Blueprint Generation (Gemini 2.0 Flash, temp=0.2)
         ↓
    Unit + 10-12 Nodes created (only metadata stored)
         ↓
    User clicks "Start Node"
         ↓
    Phase B: Content Generation (Gemini 2.0 Flash, temp=0.75)
         ↓
    7-10 Tasks generated and returned
         ↓
    Node marked complete → Next node unlocked
```

---

## 🔑 Key Features

### Anti-Hallucination Guardrails
- **Seed Constants:** Predefined topics and grammar for each CEFR level
- **JSON Schema Validation:** Strict Pydantic models prevent invalid data
- **Progressive Difficulty:** Automatic validation of difficulty progression

### Performance Optimizations
- **Async LLM Client:** HTTP/2 connection pooling
- **Job Queue:** Background processing with SSE streaming
- **Lazy Loading:** Content generated only when needed

### Adaptability
- **Dynamic Adjustment:** Update preset_json if user struggles
- **Personalization:** Based on interests, level, weak areas
- **Flexible Curriculum:** Add/remove nodes without content regeneration

---

## 📡 API Endpoints

### Phase A: Generate Blueprint

**`POST /v1/path/unit/generate_blueprint`**

Creates a learning unit with 10-12 nodes (structure only).

**Request:**
```json
{
  "user_profile": {
    "level": "A2",
    "interests": ["Business", "Travel"],
    "mastery_score": 0.72,
    "weak_areas": ["Past Tense", "Articles"],
    "target_lang": "French",
    "native_lang": "English"
  },
  "context": "After completing placement test"
}
```

**Response:**
```json
{
  "unit_id": "abc-123-def",
  "title": "Business French Fundamentals",
  "level_tag": "A2",
  "nodes_created": 12,
  "status": "available"
}
```

**Characteristics:**
- ⚡ Fast: 2-5 seconds
- 🧠 Uses: Gemini 2.0 Flash (temp=0.2)
- 💾 Storage: ~5KB per unit
- ✅ Validates: Topics/grammar against seed constants

---

### Phase B: Generate Content

**`POST /v1/path/node/start`**

Submits job to generate 7-10 tasks for a node.

**Request:**
```json
{
  "node_id": "node-xyz-789"
}
```

**Response:**
```json
{
  "job_id": "job-456-abc",
  "node_id": "node-xyz-789",
  "status": "queued",
  "status_url": "/v1/jobs/status/job-456-abc"
}
```

**Characteristics:**
- 🔄 Async: Returns immediately with job_id
- 🎨 Uses: Gemini 2.0 Flash (temp=0.75)
- 📊 Streaming: Real-time progress via SSE
- ⏱️ Duration: 5-15 seconds

---

### Query Endpoints

**`GET /v1/path/units`** - List user's units

**Query Parameters:**
- `status`: Filter by status (locked, available, in_progress, completed)

**Response:**
```json
{
  "units": [
    {
      "id": "unit-123",
      "title": "Business French Fundamentals",
      "level_tag": "A2",
      "status": "available",
      "order_index": 0,
      "node_count": 12,
      "created_at": "2026-01-12T10:00:00Z",
      "completed_at": null
    }
  ]
}
```

---

**`GET /v1/path/units/{unit_id}/nodes`** - List nodes in unit

**Response:**
```json
{
  "unit_id": "unit-123",
  "nodes": [
    {
      "id": "node-1",
      "unit_id": "unit-123",
      "type": "lesson",
      "status": "available",
      "stars": 0,
      "order_index": 0,
      "created_at": "2026-01-12T10:00:00Z",
      "completed_at": null
    },
    {
      "id": "node-2",
      "type": "lesson",
      "status": "locked",
      "stars": 0,
      "order_index": 1
    }
  ]
}
```

---

**`GET /v1/path/nodes/{node_id}`** - Get node details

**Query Parameters:**
- `include_preset`: Include preset_json (default: false)

**Response:**
```json
{
  "id": "node-1",
  "unit_id": "unit-123",
  "type": "lesson",
  "status": "available",
  "stars": 0,
  "order_index": 0,
  "preset_json": "{\"topic\":\"Shopping\",\"grammar_focus\":\"Present Simple\",...}"
}
```

---

## 💻 Client Examples

### JavaScript/TypeScript

```typescript
// Phase A: Generate Blueprint
async function generateLearningPath(userProfile: UserProfile) {
  const response = await fetch('/v1/path/unit/generate_blueprint', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer YOUR_API_KEY',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ user_profile: userProfile })
  });
  
  const { unit_id, title, nodes_created } = await response.json();
  console.log(`Created unit: ${title} with ${nodes_created} nodes`);
  
  return unit_id;
}

// Phase B: Start Node with SSE Streaming
function startNode(nodeId: string) {
  return new Promise(async (resolve, reject) => {
    // Submit job
    const submitRes = await fetch('/v1/path/node/start', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer YOUR_API_KEY',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ node_id: nodeId })
    });
    
    const { job_id } = await submitRes.json();
    
    // Stream status
    const eventSource = new EventSource(
      `/v1/jobs/status/${job_id}/stream`,
      {
        headers: { 'Authorization': 'Bearer YOUR_API_KEY' }
      }
    );
    
    eventSource.addEventListener('status', (e) => {
      const data = JSON.parse(e.data);
      console.log('Status:', data.status);
    });
    
    eventSource.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data);
      console.log('Progress:', data.bytes_received, 'bytes');
    });
    
    eventSource.addEventListener('complete', (e) => {
      const data = JSON.parse(e.data);
      eventSource.close();
      resolve(data.result);
    });
    
    eventSource.addEventListener('error', (e) => {
      const data = JSON.parse(e.data);
      eventSource.close();
      reject(new Error(data.error));
    });
  });
}

// Usage
const unitId = await generateLearningPath({
  level: 'A2',
  interests: ['Business'],
  mastery_score: 0.72,
  target_lang: 'French',
  native_lang: 'English'
});

const nodes = await fetch(`/v1/path/units/${unitId}/nodes`)
  .then(r => r.json());

const firstNode = nodes.nodes.find(n => n.status === 'available');
const tasks = await startNode(firstNode.id);

console.log('Tasks ready:', tasks);
```

### Python

```python
import httpx
import json

class LearningPathClient:
    def __init__(self, api_key: str, base_url: str = "http://localhost:8000"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    async def generate_blueprint(self, user_profile: dict) -> dict:
        """Phase A: Generate unit blueprint"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/path/unit/generate_blueprint",
                headers=self.headers,
                json={"user_profile": user_profile}
            )
            response.raise_for_status()
            return response.json()
    
    async def start_node(self, node_id: str) -> str:
        """Phase B: Submit node content generation job"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/v1/path/node/start",
                headers=self.headers,
                json={"node_id": node_id}
            )
            response.raise_for_status()
            return response.json()["job_id"]
    
    async def poll_job_status(self, job_id: str, interval: float = 2.0):
        """Poll job status until complete"""
        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(
                    f"{self.base_url}/v1/jobs/status/{job_id}",
                    headers=self.headers
                )
                data = response.json()
                
                if data["status"] == "done":
                    return data["result"]
                elif data["status"] == "failed":
                    raise Exception(data.get("error", "Job failed"))
                
                await asyncio.sleep(interval)
    
    async def get_units(self, status: str = None) -> list:
        """List user's units"""
        params = {"status": status} if status else {}
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/v1/path/units",
                headers=self.headers,
                params=params
            )
            return response.json()["units"]

# Usage
client = LearningPathClient("sk_test_your_key")

# Generate blueprint
unit = await client.generate_blueprint({
    "level": "A2",
    "interests": ["Business", "Travel"],
    "mastery_score": 0.72,
    "target_lang": "French",
    "native_lang": "English"
})

print(f"Unit created: {unit['title']}")

# Start first node
job_id = await client.start_node(first_node_id)
tasks = await client.poll_job_status(job_id)

print(f"Generated {len(tasks['tasks'])} tasks")
```

---

## 📊 Database Schema

### `units` Table
```sql
CREATE TABLE units (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  level_tag TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'locked',
  order_index INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### `nodes` Table
```sql
CREATE TABLE nodes (
  id TEXT PRIMARY KEY,
  unit_id TEXT NOT NULL,
  type TEXT NOT NULL,
  preset_json TEXT NOT NULL,  -- The "recipe" for Phase B
  status TEXT NOT NULL DEFAULT 'locked',
  stars INTEGER NOT NULL DEFAULT 0,
  order_index INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE CASCADE
);
```

### Preset JSON Example
```json
{
  "type": "lesson",
  "topic": "Shopping",
  "grammar_focus": "Present Simple",
  "difficulty_delta": 0.05,
  "vocabulary_level": "basic",
  "task_count": 7,
  "context": "At a clothing store"
}
```

---

## 🎯 Seed Constants

### Topics by Level

**A1:** Greetings, Family, Food, Colors, Numbers, Animals  
**A2:** Shopping, Travel, Weather, Hobbies, Daily Routine, Health  
**B1:** Work, Education, Technology, Environment, Culture, Media  
**B2:** Business, Politics, Science, Arts, Economics, Society  
**C1:** Philosophy, Psychology, Literature, Global Issues, Innovation  
**C2:** Advanced Discourse, Specialized Domains, Nuanced Expression

### Grammar by Level

**A1:** Present Simple, Present Continuous, Articles, Plurals, Basic Pronouns  
**A2:** Past Simple, Future (going to), Comparatives, Modal Verbs, Prepositions  
**B1:** Present Perfect, Past Continuous, Conditionals (1st/2nd), Passive Voice  
**B2:** Present Perfect Continuous, Past Perfect, Conditionals (3rd), Reported Speech  
**C1:** Advanced Tenses, Inversion, Subjunctive, Cleft Sentences  
**C2:** Subtle Modality, Complex Syntax, Stylistic Variation

---

## 🔧 Configuration

### Environment Variables

```bash
# LLM Provider
GEMINI_API_KEY=your_key_here

# Database
SEED_DB_PATH=./seed.db

# Redis (for job queue)
SEED_REDIS_URL=redis://localhost:6379/0
SEED_REDIS_NAMESPACE=seed

# Worker
SEED_WORKER_QUEUE=q_fast
```

### Model Configuration

```python
# Phase A: Blueprint (Strict)
PHASE_A_MODEL = "gemini-2.0-flash-exp"
PHASE_A_TEMPERATURE = 0.2
PHASE_A_MAX_TOKENS = 2000

# Phase B: Content (Creative)
PHASE_B_MODEL = "gemini-2.0-flash-exp"
PHASE_B_TEMPERATURE = 0.75
PHASE_B_MAX_TOKENS = 3000
```

---

## 🧪 Testing

```bash
# Unit tests
pytest test_path_models.py -v

# Integration tests
pytest test_path_integration.py -v

# Run server
python run.py

# Start worker
python run_worker.py
```

---

## 📈 Performance Metrics

| Metric | Phase A (Blueprint) | Phase B (Content) |
|--------|-------------------|------------------|
| Latency | 2-5 seconds | 5-15 seconds |
| LLM Cost | ~$0.001 | ~$0.003 |
| Storage | ~5KB | ~50KB |
| Cache Hit | 0% (always fresh) | Possible (future) |
| Parallelization | Single call | 1 per node |

---

## 🚀 Deployment

### Start Services

```bash
# Start Redis
docker run -d -p 6379:6379 redis:alpine

# Start API server
python run.py

# Start worker (separate terminal)
python run_worker.py
```

### Docker Compose

```yaml
version: '3.8'
services:
  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
  
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - SEED_REDIS_URL=redis://redis:6379/0
      - GEMINI_API_KEY=${GEMINI_API_KEY}
  
  worker:
    build: .
    command: python run_worker.py
    environment:
      - SEED_REDIS_URL=redis://redis:6379/0
      - GEMINI_API_KEY=${GEMINI_API_KEY}
```

---

## ❓ FAQ

**Q: Why separate Phase A and Phase B?**  
A: Prevents hallucinations, enables dynamic adjustment, reduces storage, and improves performance.

**Q: Can I regenerate node content?**  
A: Yes, just call `/v1/path/node/start` again with the same node_id. Old content is overwritten.

**Q: How is difficulty calculated?**  
A: `difficulty_delta` adjusts from user's mastery_score. Progressive validation ensures increasing difficulty.

**Q: What if LLM returns invalid JSON?**  
A: Pydantic validation catches errors. Job fails with detailed error message. Worker can retry.

**Q: Can I add custom topics/grammar?**  
A: Yes, edit `SeedConstants` in `path_models.py`. Restart server/worker.

---

## 📝 Next Steps

1. ✅ **Done:** Core implementation
2. 📊 **Next:** Add analytics (time per node, success rate)
3. 🎨 **Next:** Add more node types (games, conversations)
4. 🔄 **Next:** Implement adaptive difficulty (adjust based on performance)
5. 💾 **Next:** Add content caching for common paths
6. 🌐 **Next:** Multi-language support beyond French

---

**Questions?** Check `/docs` for interactive API documentation or contact the team.
