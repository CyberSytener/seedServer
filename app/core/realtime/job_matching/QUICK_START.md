# Job Search Saga - Quick Start Guide

## рџљЂ Quick Integration (5 Minutes)

### Step 1: Import the Orchestrator

```python
# In your app/main.py or app/realtime/action_router.py
from app.core.realtime.job_matching.job_orchestrator import JobSearchOrchestrator
from app.core.realtime.job_matching.job_search_actions import (
    InitiateJobSearchInput,
    SubmitEnrichedJobInput,
)
```

### Step 2: Initialize at Startup

```python
# Initialize once at application startup
job_search_orchestrator = JobSearchOrchestrator(
    db_connection_string=None,  # Optional: settings.DATABASE_URL for persistence
    job_board_adapter=None,     # Optional: your job board API client
    llm_client=None,            # Optional: your LLM service
    saga_update_handler=None,   # Optional: WebSocket update function
)
```

### Step 3: Add Action Endpoints

```python
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/job-search", tags=["job-search"])

@router.post("/initiate")
async def initiate_job_search(input: InitiateJobSearchInput):
    """Start job search saga - returns job list immediately"""
    saga_id = await job_search_orchestrator.start_job_search_saga(
        user_id=input.user_id,
        search_params=input.dict(),
    )
    
    # Get discovered jobs
    jobs = job_search_orchestrator.get_discovered_jobs(saga_id)
    
    return {
        "saga_id": saga_id,
        "status": "awaiting_selection",
        "jobs": jobs,
    }

@router.post("/submit-enriched")
async def submit_enriched_job(input: SubmitEnrichedJobInput):
    """Resume saga with client-scraped content"""
    result = await job_search_orchestrator.resume_with_enriched_job(
        saga_id=input.saga_id,
        job_id=input.job_id,
        enriched_data=input.dict(exclude={"saga_id", "job_id", "user_id"}),
    )
    
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    
    # Wait for scoring to complete
    import asyncio
    await asyncio.sleep(0.5)
    
    # Return scoring results
    scoring = job_search_orchestrator.get_scoring_result(input.saga_id)
    
    return {
        "saga_id": input.saga_id,
        "job_id": input.job_id,
        "scoring": scoring,
        "status": "completed",
    }

@router.get("/saga/{saga_id}")
async def get_saga_status(saga_id: str):
    """Query saga status"""
    saga = job_search_orchestrator.get_saga(saga_id)
    
    if not saga:
        raise HTTPException(status_code=404, detail="Saga not found")
    
    return {
        "saga_id": saga["saga_id"],
        "state": saga["state"],
        "discovered_jobs_count": len(saga["discovered_jobs"]),
        "selected_job_id": saga["selected_job_id"],
        "has_scoring_result": saga["scoring_result"] is not None,
        "created_at": saga["created_at"],
        "updated_at": saga["updated_at"],
    }
```

### Step 4: Test the Flow

```bash
# Terminal 1: Start server
python -m uvicorn app.main:app --reload

# Terminal 2: Test API
curl -X POST http://localhost:8000/api/job-search/initiate \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Python Engineer",
    "location": "Remote",
    "user_id": "user_123",
    "user_skills": ["Python", "FastAPI"],
    "max_results": 10
  }'

# Response:
# {
#   "saga_id": "saga_abc123",
#   "status": "awaiting_selection",
#   "jobs": [
#     {
#       "job_id": "job_001",
#       "title": "Senior Python Engineer",
#       "company": "TechCorp",
#       "link": "https://example.com/job/1"
#     }
#   ]
# }

# Step 5: Submit enriched job
curl -X POST http://localhost:8000/api/job-search/submit-enriched \
  -H "Content-Type: application/json" \
  -d '{
    "saga_id": "saga_abc123",
    "job_id": "job_001",
    "user_id": "user_123",
    "full_description": "We are seeking a Senior Python Engineer...",
    "requirements": ["5+ years Python", "FastAPI experience"],
    "tech_stack": ["Python", "FastAPI", "PostgreSQL"]
  }'

# Response:
# {
#   "saga_id": "saga_abc123",
#   "job_id": "job_001",
#   "scoring": {
#     "match_score": 0.85,
#     "recommendation": "strong_fit",
#     "key_matches": ["Python expertise", "FastAPI knowledge"]
#   },
#   "status": "completed"
# }
```

## рџЋЇ Client Integration

### Basic JavaScript Client

```javascript
// Step 1: Initiate job search
async function searchJobs(query, location) {
  const response = await fetch('/api/job-search/initiate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: query,
      location: location,
      user_id: getCurrentUserId(),
      user_skills: getUserSkills(),
      max_results: 20,
    }),
  });
  
  const data = await response.json();
  
  // Display jobs to user
  displayJobList(data.jobs);
  
  return data.saga_id;
}

// Step 2: User selects a job, client scrapes content
async function onJobSelected(sagaId, job) {
  // Scrape full content (if using browser extension)
  const enrichedData = await scrapeJobPage(job.link);
  
  // Submit to server for AI analysis
  const response = await fetch('/api/job-search/submit-enriched', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      saga_id: sagaId,
      job_id: job.job_id,
      user_id: getCurrentUserId(),
      full_description: enrichedData.description,
      requirements: enrichedData.requirements,
      tech_stack: enrichedData.techStack,
    }),
  });
  
  const result = await response.json();
  
  // Display AI scoring results
  displayScoringResults(result.scoring);
}

// Step 3: Simple scraper (if no extension)
async function scrapeJobPage(url) {
  // Option A: Use browser extension (recommended)
  // Option B: Proxy through server (fallback)
  // Option C: Manual input (last resort)
  
  return {
    description: "Full job description...",
    requirements: ["5+ years experience", "Python expertise"],
    techStack: ["Python", "FastAPI", "PostgreSQL"],
  };
}
```

### React Component Example

```tsx
import React, { useState } from 'react';

export function JobSearchWidget() {
  const [jobs, setJobs] = useState([]);
  const [sagaId, setSagaId] = useState(null);
  const [scoring, setScoring] = useState(null);
  
  async function handleSearch(query, location) {
    const response = await fetch('/api/job-search/initiate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        location,
        user_id: userId,
        user_skills: userSkills,
      }),
    });
    
    const data = await response.json();
    setJobs(data.jobs);
    setSagaId(data.saga_id);
  }
  
  async function handleJobClick(job) {
    // Scrape job content
    const enrichedData = await scrapeJobPage(job.link);
    
    // Submit for analysis
    const response = await fetch('/api/job-search/submit-enriched', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        saga_id: sagaId,
        job_id: job.job_id,
        user_id: userId,
        ...enrichedData,
      }),
    });
    
    const result = await response.json();
    setScoring(result.scoring);
  }
  
  return (
    <div>
      <SearchBar onSearch={handleSearch} />
      
      {jobs.length > 0 && (
        <JobList jobs={jobs} onJobClick={handleJobClick} />
      )}
      
      {scoring && (
        <ScoringResults
          matchScore={scoring.match_score}
          recommendation={scoring.recommendation}
          keyMatches={scoring.key_matches}
          concerns={scoring.concerns}
        />
      )}
    </div>
  );
}
```

## рџ”Њ WebSocket Integration (Optional)

```python
# In your WebSocket handler
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Initialize orchestrator with WebSocket updates
    async def send_update(payload):
        await websocket.send_json(payload)
    
    orchestrator = JobSearchOrchestrator(
        saga_update_handler=send_update,
    )
    
    # Handle messages
    async for message in websocket.iter_json():
        if message["type"] == "job_search.initiate":
            saga_id = await orchestrator.start_job_search_saga(
                user_id=message["user_id"],
                search_params=message["params"],
            )
            # Orchestrator automatically sends job list via WebSocket
        
        elif message["type"] == "job_search.submit_enriched":
            await orchestrator.resume_with_enriched_job(
                saga_id=message["saga_id"],
                job_id=message["job_id"],
                enriched_data=message["data"],
            )
            # Orchestrator automatically sends scoring results via WebSocket
```

## рџ“ќ Development Workflow

1. **Start server**: `python -m uvicorn app.main:app --reload`
2. **Run example**: `python app/core/realtime/job_matching/integration_example.py`
3. **Test API**: Use curl or Postman
4. **Build client**: Integrate frontend with API
5. **Add browser extension**: Create scraping extension

## вљ™пёЏ Configuration

### With Database Persistence

```python
job_search_orchestrator = JobSearchOrchestrator(
    db_connection_string=settings.DATABASE_URL,
)
```

### With Job Board API

```python
from app.integrations.linkedin_api import LinkedInJobBoard

job_board = LinkedInJobBoard(api_key=settings.LINKEDIN_API_KEY)

job_search_orchestrator = JobSearchOrchestrator(
    job_board_adapter=job_board,
)
```

### With LLM Service

```python
from app.infrastructure.llm.client import get_llm_client

llm_client = await get_llm_client()

job_search_orchestrator = JobSearchOrchestrator(
    llm_client=llm_client,
)
```

## рџђ› Troubleshooting

### Issue: Jobs not appearing

**Solution**: Check orchestrator initialization and mock data:
```python
jobs = orchestrator.get_discovered_jobs(saga_id)
print(f"Found {len(jobs)} jobs")
```

### Issue: Saga stuck in awaiting_selection

**Solution**: Verify client is calling submit_enriched endpoint:
```python
state = orchestrator.get_saga_state(saga_id)
print(f"Current state: {state}")  # Should be "awaiting_client_selection"
```

### Issue: Scoring not working

**Solution**: Check if LLM client is configured:
```python
# Orchestrator falls back to mock scoring if llm_client is None
scoring = orchestrator.get_scoring_result(saga_id)
print(f"Scoring: {scoring}")
```

## рџ“љ Next Steps

- [x] Read full documentation: [README.md](README.md)
- [ ] Review integration example: [integration_example.py](integration_example.py)
- [ ] Study action contracts: [job_search_actions.py](job_search_actions.py)
- [ ] Understand orchestrator: [job_orchestrator.py](job_orchestrator.py)
- [ ] Test the flow: Run `python integration_example.py`
- [ ] Add to your API: Follow Step 3 above
- [ ] Build client: Use React/Vue/vanilla JS examples

## рџЋ‰ You're Ready!

The hybrid parsing strategy is now integrated. Start with mock data, then gradually add:
1. Real job board APIs
2. LLM scoring service
3. Database persistence
4. Browser extension
5. WebSocket updates

Happy job searching! рџљЂ


