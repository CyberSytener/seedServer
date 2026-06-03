"""
Learning Path API - Blueprint Pattern Implementation

Phase A: Generate Unit Blueprint (structure only, no content)
Phase B: Generate Node Content (when user starts a node)

This implements the anti-hallucination pattern by separating
curriculum design from content creation.
"""

import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.auth import AuthContext, authenticate, require_admin_key
from app.dependencies import get_db, get_hub
from app.infrastructure.db.sqlite import DB
from app.infrastructure.llm.client import AsyncLLMClient, get_llm_client
from app.models.path import (
    GenerateBlueprintRequest,
    GenerateBlueprintResponse,
    StartNodeRequest,
    StartNodeResponse,
    UnitBlueprint,
    NodePreset,
    SeedConstants,
    PromptTemplates,
    UnitStatus,
    NodeStatus,
)
from app.services.path.analytics import (
    NodeAttemptSubmit,
    NodeAttemptResponse,
    TaskAttemptSubmit,
    UserLearningAnalytics,
    NodePerformance,
    NodeAnalyticsSummary,
    LeaderboardResponse,
    LeaderboardEntry,
    DifficultyAdjustment,
    AdaptiveRecommendation,
)
from app.services.path.adaptive import (
    calculate_mastery_score,
    suggest_difficulty_adjustment,
    recommend_next_topics,
    should_regenerate_node,
)
from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.redis.sse import RedisEventBroker


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/path", tags=["learning-path"])


# ==================== Phase A: Blueprint Generation ====================

@router.post("/unit/generate_blueprint", response_model=GenerateBlueprintResponse)
async def generate_unit_blueprint(
    req: GenerateBlueprintRequest,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    **Phase A: Generate Unit Blueprint**
    
    Creates a Unit with 10-12 Nodes. Each Node contains only metadata (preset_json),
    not actual lesson content. This prevents hallucinations and keeps DB lean.
    
    **Uses:**
    - Gemini 2.0 Flash with temperature=0.2 (strict, logical)
    - Seed Constants for anti-hallucination guardrails
    - Async LLM client with connection pooling
    
    **Process:**
    1. Build system prompt with available topics/grammar
    2. Call Gemini to generate blueprint JSON
    3. Validate structure with Pydantic
    4. Store Unit + Nodes in DB
    
    **Example Request:**
    ```json
    {
      "user_profile": {
        "level": "A2",
        "interests": ["Business", "Travel"],
        "mastery_score": 0.72,
        "target_lang": "French",
        "native_lang": "English"
      },
      "context": "After completing placement test"
    }
    ```
    
    **Returns:**
    - `unit_id`: Use to query unit details
    - `nodes_created`: Number of nodes generated (10-12)
    """
    ctx: AuthContext = authenticate(request, db)
    
    user_id = ctx.user_id
    profile = req.user_profile
    
    # Generate unit ID
    unit_id = str(uuid.uuid4())
    
    # Build Phase A system prompt
    system_prompt = PromptTemplates.phase_a_blueprint(profile)
    user_prompt = f"Generate a Unit blueprint for {profile.level} level learner interested in {', '.join(profile.interests) if profile.interests else 'general topics'}."
    
    if req.context:
        user_prompt += f"\n\nContext: {req.context}"
    
    logger.info(f"Generating blueprint for user={user_id}, level={profile.level}, unit_id={unit_id}")
    
    # Call Gemini with strict JSON mode
    try:
        async with get_llm_client() as client:
            response = await client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider="gemini",
                model="gemini-2.0-flash-exp",
                temperature=0.2,  # Low temperature for strict structure
                max_tokens=6000,
                timeout_sec=30
            )
        
        # Parse and validate blueprint
        blueprint_data = json.loads(response.text)
        blueprint = UnitBlueprint(**blueprint_data)
        
    except json.JSONDecodeError as e:
        logger.error(f"Blueprint JSON parse error: {e}\nResponse: {response.text[:500]}")
        raise HTTPException(status_code=500, detail=f"Invalid JSON from LLM: {str(e)}")
    
    except Exception as e:
        logger.error(f"Blueprint generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Blueprint generation failed: {str(e)}")
    
    # Validate topics/grammar against seed constants
    level = profile.level
    for node_def in blueprint.nodes:
        preset = node_def.preset
        
        if not SeedConstants.validate_topic(preset.topic, level):
            logger.warning(f"Invalid topic '{preset.topic}' for level {level}, correcting...")
            # Fallback to first valid topic
            preset.topic = SeedConstants.get_topics_for_level(level)[0]
        
        if preset.grammar_focus and not SeedConstants.validate_grammar(preset.grammar_focus, level):
            logger.warning(f"Invalid grammar '{preset.grammar_focus}' for level {level}, correcting...")
            preset.grammar_focus = SeedConstants.get_grammar_for_level(level)[0]
    
    # Persist Unit
    try:
        db.execute(
            """
            INSERT INTO units (id, user_id, title, level_tag, status, order_index)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (unit_id, user_id, blueprint.title, blueprint.level_tag, UnitStatus.available.value, 0)
        )
        
        # Persist Nodes
        for idx, node_def in enumerate(blueprint.nodes):
            node_id = str(uuid.uuid4())
            preset_json = node_def.preset.model_dump_json()
            
            # First node is available, rest are locked
            node_status = NodeStatus.available.value if idx == 0 else NodeStatus.locked.value
            
            db.execute(
                """
                INSERT INTO nodes (id, unit_id, type, preset_json, status, stars, order_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    unit_id,
                    node_def.type.value,
                    preset_json,
                    node_status,
                    0,
                    idx
                )
            )
        
        logger.info(f"Blueprint persisted: unit_id={unit_id}, nodes={len(blueprint.nodes)}")
        
    except Exception as e:
        logger.error(f"DB persist error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to persist blueprint: {str(e)}")
    
    return GenerateBlueprintResponse(
        unit_id=unit_id,
        title=blueprint.title,
        level_tag=blueprint.level_tag,
        nodes_created=len(blueprint.nodes),
        status=UnitStatus.available
    )


# ==================== Phase B: Content Generation ====================

@router.post("/node/start", response_model=StartNodeResponse)
async def start_node(
    req: StartNodeRequest,
    request: Request,
    db: DB = Depends(get_db),
    queue_hub: RedisQueueHub = Depends(get_hub)
):
    """
    **Phase B: Start Node and Generate Content**
    
    Submits a background job to generate 7-10 tasks for a node.
    Uses the preset_json "recipe" stored in the DB.
    
    **Uses:**
    - Gemini 2.0 Flash with temperature=0.75 (creative, varied)
    - Job queue for async processing
    - SSE streaming for progress updates
    
    **Process:**
    1. Fetch node preset_json from DB
    2. Submit job to queue
    3. Return job_id for status polling/streaming
    4. Worker generates content asynchronously
    
    **Example Request:**
    ```json
    {
      "node_id": "abc123"
    }
    ```
    
    **Returns:**
    - `job_id`: Use to poll or stream status
    - `status_url`: Direct link to job status endpoint
    
    **Client Usage:**
    ```javascript
    // Submit node start
    const { job_id } = await fetch('/v1/path/node/start', {
      method: 'POST',
      body: JSON.stringify({ node_id: 'abc123' })
    }).then(r => r.json());
    
    // Stream progress (recommended)
    const es = new EventSource(`/v1/jobs/status/${job_id}/stream`);
    es.addEventListener('complete', (e) => {
      const { result } = JSON.parse(e.data);
      displayTasks(result.tasks);
    });
    ```
    """
    ctx: AuthContext = authenticate(request, db)
    
    user_id = ctx.user_id
    node_id = req.node_id
    
    # Fetch node and validate ownership
    row = db.fetchone(
        """
        SELECT n.id, n.unit_id, n.type, n.preset_json, n.status, u.user_id, u.level_tag
        FROM nodes n
        JOIN units u ON n.unit_id = u.id
        WHERE n.id = ?
        """,
        (node_id,)
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
    
    if row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if row["status"] == NodeStatus.completed.value:
        raise HTTPException(status_code=400, detail="Node already completed")
    
    # Parse preset
    try:
        preset_json = json.loads(row["preset_json"])
        preset = NodePreset(**preset_json)
    except Exception as e:
        logger.error(f"Invalid preset_json for node {node_id}: {e}")
        raise HTTPException(status_code=500, detail="Invalid node preset")
    
    # Get user profile from learning_profiles table (if exists)
    profile_row = db.fetchone(
        "SELECT profile_json FROM learning_profiles WHERE user_id = ?",
        (user_id,)
    )
    
    target_lang = "French"  # Default
    native_lang = "English"  # Default
    
    if profile_row:
        try:
            profile_data = json.loads(profile_row["profile_json"])
            target_lang = profile_data.get("target_lang", target_lang)
            native_lang = profile_data.get("native_lang", native_lang)
        except Exception:
            logger.warning("Failed to parse learning profile JSON", exc_info=True)
    
    # Create job
    job_id = str(uuid.uuid4())
    
    try:
        # Store job in DB
        db.execute(
            """
            INSERT INTO jobs (id, user_id, action, mode, status, queue_name, priority, provider, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                user_id,
                "path_node_generate",
                "fast",
                "queued",
                "q_fast",
                10,  # High priority
                "gemini",
                "gemini-2.0-flash-exp"
            )
        )
        
        # Store job params in job_events for worker
        job_params = {
            "node_id": node_id,
            "preset": preset.model_dump(),
            "target_lang": target_lang,
            "native_lang": native_lang
        }
        
        db.execute(
            "INSERT INTO job_events (job_id, event, data_json) VALUES (?, ?, ?)",
            (job_id, "params", json.dumps(job_params))
        )
        
        # Enqueue in Redis
        await queue_hub.enqueue(
            queue_name="q_fast",
            job_id=job_id,
            priority=10
        )
        
        # Update node status
        db.execute(
            "UPDATE nodes SET status = ? WHERE id = ?",
            (NodeStatus.in_progress.value, node_id)
        )
        
        logger.info(f"Node generation job submitted: job_id={job_id}, node_id={node_id}")
        
    except Exception as e:
        logger.error(f"Job submission error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")
    
    return StartNodeResponse(
        job_id=job_id,
        node_id=node_id,
        status="queued",
        status_url=f"/v1/jobs/status/{job_id}"
    )


# ==================== Query Endpoints ====================

@router.get("/units")
async def list_units(
    request: Request,
    status: Optional[str] = None,
    db: DB = Depends(get_db)
):
    """
    List all units for authenticated user.
    
    **Query Params:**
    - `status`: Filter by status (locked, available, in_progress, completed)
    
    **Returns:** Array of units with node counts
    """
    ctx: AuthContext = authenticate(request, db)
    
    query = "SELECT * FROM units WHERE user_id = ?"
    params = [ctx.user_id]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY order_index ASC"
    
    rows = db.fetchall(query, tuple(params))
    
    units = []
    for row in rows:
        # Count nodes
        node_count = db.fetchone(
            "SELECT COUNT(*) as cnt FROM nodes WHERE unit_id = ?",
            (row["id"],)
        )["cnt"]
        
        units.append({
            "id": row["id"],
            "title": row["title"],
            "level_tag": row["level_tag"],
            "status": row["status"],
            "order_index": row["order_index"],
            "node_count": node_count,
            "created_at": row["created_at"],
            "completed_at": row["completed_at"]
        })
    
    return {"units": units}


@router.get("/units/{unit_id}/nodes")
async def list_nodes(
    unit_id: str,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    List all nodes for a unit.
    
    **Returns:** Array of nodes with status and progress
    """
    ctx: AuthContext = authenticate(request, db)
    
    # Verify ownership
    unit = db.fetchone(
        "SELECT user_id FROM units WHERE id = ?",
        (unit_id,)
    )
    
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    
    if unit["user_id"] != ctx.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Fetch nodes
    rows = db.fetchall(
        """
        SELECT id, unit_id, type, status, stars, order_index, created_at, completed_at
        FROM nodes
        WHERE unit_id = ?
        ORDER BY order_index ASC
        """,
        (unit_id,)
    )
    
    nodes = [dict(row) for row in rows]
    
    return {"unit_id": unit_id, "nodes": nodes}


@router.get("/nodes/{node_id}")
async def get_node_details(
    node_id: str,
    request: Request,
    include_preset: bool = False,
    db: DB = Depends(get_db)
):
    """
    Get node details.
    
    **Query Params:**
    - `include_preset`: Include preset_json (recipe) in response
    
    **Returns:** Node details with optional preset
    """
    ctx: AuthContext = authenticate(request, db)
    
    # Fetch with ownership check
    row = db.fetchone(
        """
        SELECT n.*, u.user_id
        FROM nodes n
        JOIN units u ON n.unit_id = u.id
        WHERE n.id = ?
        """,
        (node_id,)
    )
    
    if not row:
        raise HTTPException(status_code=404, detail="Node not found")
    
    if row["user_id"] != ctx.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    node = dict(row)
    
    if not include_preset:
        node.pop("preset_json", None)
    
    return node


# ==================== Analytics & Progress Tracking ====================

@router.post("/node/submit", response_model=NodeAttemptResponse)
async def submit_node_attempt(
    req: NodeAttemptSubmit,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    Submit node completion results and get feedback.
    
    Records all task attempts, calculates score, awards stars,
    and unlocks next node if successful.
    
    **Request Body:**
    ```json
    {
      "node_id": "node-123",
      "session_id": "session-abc",
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
          "hint_used": false
        },
        ...
      ],
      "metadata": {}
    }
    ```
    
    **Returns:**
    - Score and success status
    - Stars earned (0-3)
    - Next node ID if unlocked
    - Personalized feedback
    """
    ctx: AuthContext = authenticate(request, db)
    
    user_id = ctx.user_id
    node_id = req.node_id
    
    # Verify node ownership
    node_row = db.fetchone(
        """
        SELECT n.id, n.unit_id, n.type, u.user_id
        FROM nodes n
        JOIN units u ON n.unit_id = u.id
        WHERE n.id = ?
        """,
        (node_id,)
    )
    
    if not node_row:
        raise HTTPException(status_code=404, detail="Node not found")
    
    if node_row["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Calculate metrics
    duration = req.duration_seconds
    tasks_total = len(req.task_attempts)
    tasks_correct = req.tasks_correct
    tasks_incorrect = req.tasks_incorrect
    score = req.score
    success = req.is_success
    
    # Award stars based on score
    if score >= 0.95:
        stars = 3
    elif score >= 0.85:
        stars = 2
    elif score >= 0.70:
        stars = 1
    else:
        stars = 0
    
    # Insert node attempt
    try:
        cursor = db._conn.execute(
            """
            INSERT INTO node_attempts (
                node_id, user_id, session_id, started_at, completed_at,
                duration_seconds, tasks_total, tasks_correct, tasks_incorrect,
                score, success, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, user_id, req.session_id, req.started_at, req.completed_at,
                duration, tasks_total, tasks_correct, tasks_incorrect,
                score, 1 if success else 0, json.dumps(req.metadata)
            )
        )
        
        attempt_id = cursor.lastrowid
        
        # Insert individual task attempts
        for task in req.task_attempts:
            db.execute(
                """
                INSERT INTO task_attempts (
                    node_attempt_id, task_id, task_type, user_answer, correct_answer,
                    is_correct, response_time_ms, hint_used, attempts_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id, task.task_id, task.task_type, task.user_answer,
                    task.correct_answer, 1 if task.is_correct else 0,
                    task.response_time_ms, 1 if task.hint_used else 0,
                    task.attempts_count
                )
            )
        
        db._conn.commit()
        
    except Exception as e:
        logger.error(f"Failed to save attempt: {e}")
        raise HTTPException(status_code=500, detail="Failed to save attempt")
    
    # Update node status and stars
    if success:
        # Update node if better performance
        current = db.fetchone("SELECT stars FROM nodes WHERE id = ?", (node_id,))
        if current and stars > current["stars"]:
            db.execute(
                "UPDATE nodes SET stars = ?, completed_at = datetime('now'), status = ? WHERE id = ?",
                (stars, NodeStatus.completed.value, node_id)
            )
        elif not current or current["stars"] == 0:
            db.execute(
                "UPDATE nodes SET stars = ?, completed_at = datetime('now'), status = ? WHERE id = ?",
                (stars, NodeStatus.completed.value, node_id)
            )
    
    # Unlock next node
    next_node_id = None
    if success:
        from app.services.path.worker import unlock_next_node
        unlock_next_node(db, node_id)
        
        # Find next available node
        next_node = db.fetchone(
            """
            SELECT id FROM nodes
            WHERE unit_id = ? AND order_index > (SELECT order_index FROM nodes WHERE id = ?)
            AND status = ?
            ORDER BY order_index ASC
            LIMIT 1
            """,
            (node_row["unit_id"], node_id, NodeStatus.available.value)
        )
        
        if next_node:
            next_node_id = next_node["id"]
    
    # Generate feedback
    if score >= 0.9:
        feedback = f"Excellent work! You scored {score*100:.0f}% and earned {stars} stars. Keep up the great progress!"
    elif score >= 0.7:
        feedback = f"Good job! You scored {score*100:.0f}% and earned {stars} stars. You're making solid progress."
    else:
        feedback = f"You scored {score*100:.0f}%. Don't worry - practice makes perfect! Review the material and try again."
    
    logger.info(f"Node attempt recorded: user={user_id}, node={node_id}, score={score:.2f}, stars={stars}")
    
    return NodeAttemptResponse(
        attempt_id=attempt_id,
        node_id=node_id,
        score=score,
        success=success,
        stars_earned=stars,
        next_node_unlocked=next_node_id,
        feedback=feedback
    )


@router.get("/analytics/user", response_model=UserLearningAnalytics)
async def get_user_analytics(
    request: Request,
    db: DB = Depends(get_db)
):
    """
    Get comprehensive analytics for authenticated user.
    
    Returns:
    - Overall progress (units/nodes completed)
    - Task accuracy stats
    - Time spent learning
    - Strongest/weakest task types
    - Current streak
    """
    ctx: AuthContext = authenticate(request, db)
    
    user_id = ctx.user_id
    
    # Units stats
    units_stats = db.fetchone(
        """
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
        FROM units WHERE user_id = ?
        """,
        (user_id,)
    )
    
    # Nodes stats
    nodes_stats = db.fetchone(
        """
        SELECT
            COUNT(DISTINCT na.node_id) as attempted,
            COUNT(DISTINCT CASE WHEN na.success = 1 THEN na.node_id END) as completed
        FROM node_attempts na
        WHERE na.user_id = ?
        """,
        (user_id,)
    )
    
    # Task stats
    task_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total_attempts,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_attempts,
            SUM(duration_seconds) as total_seconds,
            COUNT(DISTINCT session_id) as session_count
        FROM node_attempts na
        JOIN task_attempts ta ON na.id = ta.node_attempt_id
        WHERE na.user_id = ?
        """,
        (user_id,)
    )
    
    total_tasks = task_stats["total_attempts"] or 0
    correct_tasks = task_stats["correct_attempts"] or 0
    overall_accuracy = correct_tasks / total_tasks if total_tasks > 0 else 0.0
    
    total_minutes = (task_stats["total_seconds"] or 0) // 60
    session_count = task_stats["session_count"] or 1
    avg_session_minutes = total_minutes / session_count
    
    # Strongest/weakest task types
    type_stats = db.fetchall(
        """
        SELECT
            ta.task_type,
            COUNT(*) as attempts,
            SUM(CASE WHEN ta.is_correct = 1 THEN 1 ELSE 0 END) as correct,
            CAST(SUM(CASE WHEN ta.is_correct = 1 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) as accuracy
        FROM task_attempts ta
        JOIN node_attempts na ON ta.node_attempt_id = na.id
        WHERE na.user_id = ?
        GROUP BY ta.task_type
        HAVING COUNT(*) >= 3
        ORDER BY accuracy DESC
        """,
        (user_id,)
    )
    
    strongest = [t["task_type"] for t in type_stats[:3]]
    weakest = [t["task_type"] for t in reversed(type_stats[-3:])]
    
    # Stars earned
    total_stars = db.fetchone(
        "SELECT SUM(stars) as total FROM nodes WHERE id IN (SELECT DISTINCT node_id FROM node_attempts WHERE user_id = ? AND success = 1)",
        (user_id,)
    )["total"] or 0
    
    # Streak (simplified - days with at least one completion)
    streak = db.fetchone(
        """
        SELECT COUNT(DISTINCT DATE(completed_at)) as days
        FROM node_attempts
        WHERE user_id = ? AND success = 1
        AND completed_at >= DATE('now', '-7 days')
        """,
        (user_id,)
    )["days"] or 0
    
    return UserLearningAnalytics(
        user_id=user_id,
        units_started=units_stats["total"] or 0,
        units_completed=units_stats["completed"] or 0,
        nodes_attempted=nodes_stats["attempted"] or 0,
        nodes_completed=nodes_stats["completed"] or 0,
        total_tasks_attempted=total_tasks,
        total_tasks_correct=correct_tasks,
        overall_accuracy=overall_accuracy,
        total_time_minutes=total_minutes,
        avg_session_duration_minutes=avg_session_minutes,
        strongest_task_types=strongest,
        weakest_task_types=weakest,
        current_streak_days=streak,
        total_stars_earned=total_stars
    )


@router.get("/analytics/node/{node_id}", response_model=NodeAnalyticsSummary)
async def get_node_analytics(
    node_id: str,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    Get detailed analytics for a specific node.
    
    Useful for:
    - Identifying difficult nodes
    - Finding common error patterns
    - Adjusting difficulty
    """
    ctx: AuthContext = authenticate(request, db)
    
    # Verify node exists and get basic info
    node = db.fetchone(
        """
        SELECT n.id, n.unit_id, n.type
        FROM nodes n
        JOIN units u ON n.unit_id = u.id
        WHERE n.id = ? AND u.user_id = ?
        """,
        (node_id, ctx.user_id)
    )
    
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    
    # Attempt stats
    attempt_stats = db.fetchone(
        """
        SELECT
            COUNT(*) as total_attempts,
            COUNT(DISTINCT user_id) as unique_users,
            AVG(score) as avg_score,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as success_rate,
            AVG(duration_seconds) as avg_duration,
            SUM(CASE WHEN completed_at IS NOT NULL THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as completion_rate
        FROM node_attempts
        WHERE node_id = ?
        """,
        (node_id,)
    )
    
    # Task type breakdown
    task_type_stats = db.fetchall(
        """
        SELECT
            ta.task_type,
            COUNT(*) as total,
            SUM(CASE WHEN ta.is_correct = 1 THEN 1 ELSE 0 END) as correct,
            AVG(ta.response_time_ms) as avg_time
        FROM task_attempts ta
        JOIN node_attempts na ON ta.node_attempt_id = na.id
        WHERE na.node_id = ?
        GROUP BY ta.task_type
        """,
        (node_id,)
    )
    
    task_breakdown = [
        {
            "task_type": row["task_type"],
            "total_attempts": row["total"],
            "correct_attempts": row["correct"],
            "accuracy": row["correct"] / row["total"] if row["total"] > 0 else 0.0,
            "avg_response_time_ms": row["avg_time"]
        }
        for row in task_type_stats
    ]
    
    # Common errors (top 5)
    common_errors = db.fetchall(
        """
        SELECT
            ta.task_id,
            ta.user_answer,
            ta.correct_answer,
            COUNT(*) as frequency
        FROM task_attempts ta
        JOIN node_attempts na ON ta.node_attempt_id = na.id
        WHERE na.node_id = ? AND ta.is_correct = 0
        GROUP BY ta.task_id, ta.user_answer, ta.correct_answer
        ORDER BY frequency DESC
        LIMIT 5
        """,
        (node_id,)
    )
    
    # Difficulty rating based on success rate
    success_rate = attempt_stats["success_rate"] or 0.0
    if success_rate >= 0.8:
        difficulty = "easy"
    elif success_rate >= 0.6:
        difficulty = "medium"
    else:
        difficulty = "hard"
    
    return NodeAnalyticsSummary(
        node_id=node_id,
        unit_id=node["unit_id"],
        node_type=node["type"],
        total_attempts=attempt_stats["total_attempts"] or 0,
        unique_users=attempt_stats["unique_users"] or 0,
        avg_score=attempt_stats["avg_score"] or 0.0,
        success_rate=success_rate,
        avg_duration_seconds=attempt_stats["avg_duration"] or 0.0,
        completion_rate=attempt_stats["completion_rate"] or 0.0,
        task_type_breakdown=task_breakdown,
        common_errors=[dict(e) for e in common_errors],
        difficulty_rating=difficulty
    )


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    request: Request,
    period: str = "all_time",
    limit: int = 100,
    db: DB = Depends(get_db)
):
    """
    Get leaderboard rankings.
    
    **Query Params:**
    - `period`: "daily", "weekly", "all_time"
    - `limit`: Number of entries (default: 100)
    """
    ctx: AuthContext = authenticate(request, db)
    
    # Date filter based on period
    date_filter = ""
    if period == "daily":
        date_filter = "AND na.completed_at >= DATE('now')"
    elif period == "weekly":
        date_filter = "AND na.completed_at >= DATE('now', '-7 days')"
    
    # Get leaderboard
    leaderboard_data = db.fetchall(
        f"""
        SELECT
            na.user_id,
            SUM(n.stars) as total_stars,
            COUNT(DISTINCT na.node_id) as nodes_completed,
            AVG(na.score) as avg_score,
            SUM(na.duration_seconds) / 60 as total_minutes
        FROM node_attempts na
        JOIN nodes n ON na.node_id = n.id
        WHERE na.success = 1 {date_filter}
        GROUP BY na.user_id
        ORDER BY total_stars DESC, nodes_completed DESC, avg_score DESC
        LIMIT ?
        """,
        (limit,)
    )
    
    entries = []
    user_rank = None
    
    for rank, row in enumerate(leaderboard_data, 1):
        entry = LeaderboardEntry(
            rank=rank,
            user_id=row["user_id"],
            display_name=None,  # Could fetch from users table
            total_stars=row["total_stars"] or 0,
            nodes_completed=row["nodes_completed"] or 0,
            avg_score=row["avg_score"] or 0.0,
            total_time_minutes=int(row["total_minutes"] or 0)
        )
        entries.append(entry)
        
        if row["user_id"] == ctx.user_id:
            user_rank = rank
    
    total_users = db.fetchone(
        f"SELECT COUNT(DISTINCT user_id) as cnt FROM node_attempts WHERE success = 1 {date_filter}"
    )["cnt"] or 0
    
    return LeaderboardResponse(
        period=period,
        entries=entries,
        user_rank=user_rank,
        total_users=total_users
    )


# ==================== Adaptive Difficulty ====================

@router.get("/adaptive/difficulty", response_model=DifficultyAdjustment)
async def get_adaptive_difficulty(
    request: Request,
    level: str = "A2",
    db: DB = Depends(get_db)
):
    """
    Get personalized difficulty adjustment based on recent performance.
    
    Returns:
    - Current mastery score
    - Suggested difficulty delta for next nodes
    - Reasoning
    
    **Example:**
    ```bash
    GET /v1/path/adaptive/difficulty?level=A2
    ```
    """
    ctx: AuthContext = authenticate(request, db)
    
    adjustment = suggest_difficulty_adjustment(db, ctx.user_id, level)
    
    return adjustment


@router.get("/adaptive/recommendations", response_model=AdaptiveRecommendation)
async def get_adaptive_recommendations(
    request: Request,
    level: str = "A2",
    db: DB = Depends(get_db)
):
    """
    Get personalized learning recommendations.
    
    Analyzes user's:
    - Completed topics
    - Weak areas needing reinforcement
    - Strong areas ready for advancement
    
    Returns recommended next steps.
    """
    ctx: AuthContext = authenticate(request, db)
    
    recommendations = recommend_next_topics(db, ctx.user_id, level)
    
    return recommendations


@router.get("/admin/node/{node_id}/should_regenerate")
async def check_node_regeneration(
    node_id: str,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    Check if a node should be regenerated due to poor performance.
    
    Admin endpoint for quality control.
    """
    require_admin_key(request)
    
    should_regen, reason = should_regenerate_node(db, node_id)
    
    return {
        "node_id": node_id,
        "should_regenerate": should_regen,
        "reason": reason
    }




