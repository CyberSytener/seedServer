"""
Job Queue API for Async Background Processing

Provides endpoints for queueing long-running LLM operations.
Clients can submit jobs and poll/stream status updates.
"""

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import AuthContext, authenticate
from app.dependencies import get_db, get_hub, get_broker
from app.infrastructure.db.sqlite import DB
from app.models.api import LessonGenerateRequest, DiagnosticGenerateRequest
from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.redis.sse import RedisEventBroker


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

DEPRECATION_SUNSET = "Tue, 30 Jun 2026 00:00:00 GMT"
DEPRECATION_DOC = "/docs/jobs_api_contract.md"


def _mark_legacy_endpoint(response: Response, *, successor: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = DEPRECATION_SUNSET
    response.headers["Link"] = f'<{successor}>; rel="successor-version", <{DEPRECATION_DOC}>; rel="deprecation"'


class JobSubmitRequest(BaseModel):
    """Request to submit a background job"""
    job_type: str = Field(..., description="Job type: lesson_generate, diagnostic_generate")
    params: dict = Field(..., description="Job parameters (varies by type)")
    priority: int = Field(default=0, description="Job priority (higher = faster)")
    queue: str = Field(default="q_fast", description="Target queue: q_fast, q_batch, q_low")


class JobSubmitResponse(BaseModel):
    """Response after submitting job"""
    job_id: str
    status: str
    queue: str
    estimated_wait_sec: Optional[int] = None


class JobStatusResponse(BaseModel):
    """Job status information"""
    job_id: str
    status: str  # queued, running, done, failed
    progress: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    error_message: Optional[str] = None
    action: Optional[str] = None
    mode: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None


@router.post("/submit", response_model=JobSubmitResponse)
async def submit_job(
    req: JobSubmitRequest,
    request: Request,
    response: Response,
    db: DB = Depends(get_db),
    queue_hub: RedisQueueHub = Depends(get_hub),
):
    """
    Submit a background job for async processing.
    
    **Supported Job Types:**
    - `lesson_generate`: Generate a lesson (params = LessonGenerateRequest)
    - `diagnostic_generate`: Generate diagnostic items (params = DiagnosticGenerateRequest)
    
    **Queues:**
    - `q_fast`: High-priority queue (< 5s typical wait)
    - `q_batch`: Standard queue (< 30s typical wait)
    - `q_low`: Low-priority queue (< 2min typical wait)
    
    **Example:**
    ```json
    {
      "job_type": "lesson_generate",
      "params": {
        "mode": "vocabulary",
        "target_lang": "Spanish",
        "native_lang": "English",
        "level": "A2",
        "lesson_length": 5
      },
      "priority": 10,
      "queue": "q_fast"
    }
    ```
    
    **Returns:**
    - `job_id`: Use this to poll status or stream updates
    - `status`: Initial status (always "queued")
    - `estimated_wait_sec`: Rough estimate based on queue depth
    """
    _mark_legacy_endpoint(response, successor="/v1/actions")
    
    ctx = authenticate(request, db)
    
    # Validate job type
    if req.job_type not in ("lesson_generate", "diagnostic_generate"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid job_type: {req.job_type}"
        )
    
    # Validate queue
    if req.queue not in ("q_fast", "q_batch", "q_low"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid queue: {req.queue}"
        )
    
    # Generate job ID
    job_id = f"job_{int(time.time() * 1000)}_{ctx.user_id[:8]}"
    
    # Store job in database
    params_json = json.dumps(req.params)
    db.execute(
        """
        INSERT INTO jobs(
            id, user_id, action, input_text, options_json,
            mode, status, priority, queue_name, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            job_id,
            ctx.user_id,
            req.job_type,
            "",
            params_json,
            req.params.get("mode", "vocabulary"),
            "queued",
            req.priority,
            req.queue
        )
    )
    
    # Enqueue in Redis
    await queue_hub.enqueue(
        queue_name=req.queue,
        job_id=job_id,
        priority=req.priority
    )
    
    # Estimate wait time based on queue depth
    queue_depth = await queue_hub.queue_depth(req.queue)
    estimated_wait_sec = None
    if queue_depth > 0:
        # Rough estimate: 10s per job in queue
        estimated_wait_sec = queue_depth * 10
    
    logger.info(
        f"Job {job_id} queued in {req.queue} "
        f"(type={req.job_type}, priority={req.priority}, depth={queue_depth})"
    )
    
    return JobSubmitResponse(
        job_id=job_id,
        status="queued",
        queue=req.queue,
        estimated_wait_sec=estimated_wait_sec
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    request: Request,
    response: Response,
    db: DB = Depends(get_db),
):
    """
    Get current status of a job.
    
    **Polling Pattern:**
    ```javascript
    async function waitForJob(jobId) {
        while (true) {
            const status = await fetch(`/v1/jobs/status/${jobId}`).then(r => r.json());
            
            if (status.status === 'done') {
                return status.result;
            }
            if (status.status === 'failed') {
                throw new Error(status.error);
            }
            
            // Poll every 2 seconds
            await new Promise(r => setTimeout(r, 2000));
        }
    }
    ```
    
    **Better: Use streaming endpoint** `/jobs/status/{job_id}/stream` for real-time updates without polling.
    """
    _mark_legacy_endpoint(response, successor=f"/v1/jobs/{job_id}")
    
    ctx = authenticate(request, db)
    
    # Fetch job
    row = db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Verify ownership
    if row["user_id"] != ctx.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Parse result if done
    result = None
    if row["status"] == "done" and row["result_text"]:
        try:
            result = json.loads(row["result_text"])
        except json.JSONDecodeError:
            result = {"text": row["result_text"]}
    
    # Calculate duration if finished
    duration_ms = None
    if row["started_at"] and row["finished_at"]:
        from datetime import datetime
        started = datetime.fromisoformat(row["started_at"])
        finished = datetime.fromisoformat(row["finished_at"])
        duration_ms = int((finished - started).total_seconds() * 1000)
    
    return JobStatusResponse(
        job_id=job_id,
        status=row["status"],
        result=result,
        error=row.get("error_message"),
        error_message=row.get("error_message"),
        action=row.get("action"),
        mode=row.get("mode"),
        created_at=row.get("created_at"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        duration_ms=duration_ms
    )


@router.get("/status/{job_id}/stream")
async def stream_job_status(
    job_id: str,
    request: Request,
    response: Response,
    db: DB = Depends(get_db),
    broker: RedisEventBroker = Depends(get_broker),
):
    """
    Stream job status updates in real-time using SSE.
    
    **Events:**
    - `status`: Status update (queued -> running -> done/failed)
    - `progress`: Progress information (if available)
    - `complete`: Job finished with result
    - `error`: Job failed
    
    **Client Example:**
    ```javascript
    const eventSource = new EventSource(`/v1/jobs/status/${jobId}/stream`);
    
    eventSource.addEventListener('status', (e) => {
        const data = JSON.parse(e.data);
        console.log('Status:', data.status);
    });
    
    eventSource.addEventListener('complete', (e) => {
        const data = JSON.parse(e.data);
        console.log('Result:', data.result);
        eventSource.close();
    });
    ```
    
    This is more efficient than polling and provides instant updates.
    """
    _mark_legacy_endpoint(response, successor=f"/v1/jobs/{job_id}")
    
    ctx = authenticate(request, db)
    
    # Verify job exists and ownership
    row = db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["user_id"] != ctx.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    async def generate_events():
        """Generate SSE events for job status"""
        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"
        
        # Send initial status
        yield sse("status", {
            "job_id": job_id,
            "status": row["status"]
        })
        
        # If already complete, send result and exit
        if row["status"] in ("done", "failed"):
            if row["status"] == "done":
                result = None
                if row["result_text"]:
                    try:
                        result = json.loads(row["result_text"])
                    except json.JSONDecodeError:
                        result = {"text": row["result_text"]}
                
                yield sse("complete", {
                    "job_id": job_id,
                    "result": result
                })
            else:
                yield sse("error", {
                    "job_id": job_id,
                    "error": row.get("error_message", "Unknown error")
                })
            return
        
        # Subscribe to Redis events for real-time updates
        sub = await broker.subscribe(ctx.user_id)
        
        try:
            # Listen for job events
            timeout_sec = 300  # 5 minute timeout
            start_time = time.time()
            
            async for message in sub.pubsub.listen():
                if time.time() - start_time > timeout_sec:
                    yield sse("error", {
                        "job_id": job_id,
                        "error": "Timeout waiting for job completion"
                    })
                    break
                
                if message["type"] != "message":
                    continue
                
                try:
                    data = json.loads(message["data"])
                    event_type = data.get("event")
                    event_data = data.get("data", {})
                    
                    if event_data.get("job_id") == job_id:
                        if event_type == "job_done":
                            # Fetch final result
                            final_row = db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
                            result = None
                            if final_row and final_row["result_text"]:
                                try:
                                    result = json.loads(final_row["result_text"])
                                except json.JSONDecodeError:
                                    result = {"text": final_row["result_text"]}
                            
                            yield sse("complete", {
                                "job_id": job_id,
                                "result": result
                            })
                            break
                        
                        elif event_type == "job_failed":
                            yield sse("error", {
                                "job_id": job_id,
                                "error": event_data.get("error", "Job failed")
                            })
                            break
                        
                        else:
                            # Progress or status update
                            yield sse("status", {
                                "job_id": job_id,
                                "event": event_type,
                                "data": event_data
                            })
                
                except json.JSONDecodeError:
                    continue
        
        finally:
            await broker.unsubscribe(sub)
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/list")
async def list_jobs(
    request: Request,
    response: Response,
    db: DB = Depends(get_db),
    limit: int = Query(default=20, le=100),
    status: Optional[str] = Query(default=None)
):
    """
    List user's jobs with optional filtering.
    
    **Parameters:**
    - `limit`: Max results (default 20, max 100)
    - `status`: Filter by status (queued, running, done, failed)
    
    **Returns:**
    Array of job summaries with status and timestamps.
    """
    _mark_legacy_endpoint(response, successor="/v1/jobs/{job_id}")
    
    ctx = authenticate(request, db)
    
    query = "SELECT * FROM jobs WHERE user_id = ?"
    params = [ctx.user_id]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    rows = db.fetchall(query, tuple(params))
    
    jobs = []
    for row in rows:
        jobs.append({
            "job_id": row["id"],
            "job_type": row["action"],
            "status": row["status"],
            "created_at": row.get("created_at"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "error": row.get("error_message")
        })
    
    return {"jobs": jobs, "count": len(jobs)}



