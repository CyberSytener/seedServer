"""
Learning Path Worker - Phase B Content Generation

This worker processes 'path_node_generate' jobs from the queue.
It generates actual lesson content based on node preset_json.

Uses:
- Gemini 2.0 Flash with temperature=0.75 (creative)
- Streaming for progress updates
- Redis SSE for real-time client notifications
"""

import asyncio
import json
import logging
from typing import Optional

from app.infrastructure.db.sqlite import DB
from app.infrastructure.llm.client import get_llm_client
from app.models.path import NodePreset, PromptTemplates, NodeContent, TaskDefinition, NodeStatus
from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.redis.sse import RedisEventBroker


logger = logging.getLogger(__name__)


async def process_path_node_generation(
    *,
    db: DB,
    broker: RedisEventBroker,
    job_id: str
) -> None:
    """
    Process Phase B: Generate content for a node.
    
    Steps:
    1. Fetch job params (node_id, preset, languages)
    2. Build Phase B system prompt
    3. Call Gemini with temperature=0.75
    4. Parse and validate task JSON
    5. Update node status
    6. Publish completion event
    """
    
    # Fetch job from DB
    job_row = db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not job_row:
        logger.error(f"Job {job_id} not found")
        return
    
    if job_row["status"] != "queued":
        logger.warning(f"Job {job_id} already processed (status={job_row['status']})")
        return
    
    user_id = job_row["user_id"]
    
    # Mark job as running
    try:
        db.execute(
            "UPDATE jobs SET status = 'running', started_at = datetime('now') WHERE id = ? AND status = 'queued'",
            (job_id,)
        )
    except Exception as e:
        logger.error(f"Failed to update job status: {e}")
        return
    
    # Publish 'running' event
    await broker.publish(
        channel=f"job:{job_id}",
        event="status",
        data={"job_id": job_id, "status": "running"}
    )
    
    try:
        # Fetch job params from job_events
        params_row = db.fetchone(
            "SELECT data_json FROM job_events WHERE job_id = ? AND event = 'params' ORDER BY id DESC LIMIT 1",
            (job_id,)
        )
        
        if not params_row:
            raise ValueError("Job params not found in job_events")
        
        params = json.loads(params_row["data_json"])
        node_id = params["node_id"]
        preset_data = params["preset"]
        target_lang = params.get("target_lang", "French")
        native_lang = params.get("native_lang", "English")
        
        # Parse preset
        preset = NodePreset(**preset_data)
        
        logger.info(f"Generating content for node={node_id}, topic={preset.topic}, job={job_id}")
        
        # Build Phase B system prompt
        system_prompt = PromptTemplates.phase_b_content(preset, target_lang, native_lang)
        user_prompt = f"Generate {preset.task_count} varied tasks for {preset.topic}."
        
        # Call Gemini with higher temperature for creativity
        start_time = asyncio.get_event_loop().time()
        
        async with get_llm_client() as client:
            # Use streaming if available
            try:
                response = await client.generate(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    provider="gemini",
                    model="gemini-2.0-flash-exp",
                    temperature=0.75,  # Higher temperature for creative content
                    max_tokens=9000,
                    timeout_sec=60
                )
                
                # Publish progress
                await broker.publish(
                    channel=f"job:{job_id}",
                    event="progress",
                    data={
                        "job_id": job_id,
                        "node_id": node_id,
                        "bytes_received": len(response.text)
                    }
                )
                
            except Exception as e:
                logger.error(f"LLM generation error: {e}")
                raise
        
        end_time = asyncio.get_event_loop().time()
        duration_ms = int((end_time - start_time) * 1000)
        
        # Parse and validate tasks
        try:
            tasks_data = json.loads(response.text)
            
            # Handle both {"tasks": [...]} and direct array formats
            if isinstance(tasks_data, dict) and "tasks" in tasks_data:
                tasks_array = tasks_data["tasks"]
            elif isinstance(tasks_data, list):
                tasks_array = tasks_data
            else:
                raise ValueError(f"Unexpected JSON structure: {type(tasks_data)}")
            
            # Validate each task
            validated_tasks = []
            for task_data in tasks_array:
                try:
                    task = TaskDefinition(**task_data)
                    validated_tasks.append(task.model_dump())
                except Exception as e:
                    logger.warning(f"Invalid task skipped: {e}")
                    continue
            
            if len(validated_tasks) < preset.task_count - 2:
                raise ValueError(f"Not enough valid tasks: {len(validated_tasks)}/{preset.task_count}")
            
            content = NodeContent(
                node_id=node_id,
                tasks=validated_tasks,
                estimated_duration_minutes=len(validated_tasks) * 2  # 2 min per task
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Task JSON parse error: {e}\nResponse: {response.text[:500]}")
            raise ValueError(f"Invalid JSON from LLM: {str(e)}")
        
        # Store generated content
        result_json = content.model_dump_json()
        
        db.execute(
            """
            UPDATE jobs
            SET status = 'done',
                result_text = ?,
                finished_at = datetime('now'),
                provider = ?,
                model = ?,
                tokens_in_actual = ?,
                tokens_out_actual = ?
            WHERE id = ?
            """,
            (
                result_json,
                response.provider,
                response.model,
                response.tokens_in,
                response.tokens_out,
                job_id
            )
        )
        
        # Update node status to completed
        db.execute(
            "UPDATE nodes SET status = ?, completed_at = datetime('now') WHERE id = ?",
            (NodeStatus.completed.value, node_id)
        )
        
        # Unlock next node in sequence
        unlock_next_node(db, node_id)
        
        logger.info(f"Node generation complete: node={node_id}, job={job_id}, tasks={len(validated_tasks)}, duration={duration_ms}ms")
        
        # Publish completion event
        await broker.publish(
            channel=f"job:{job_id}",
            event="complete",
            data={
                "job_id": job_id,
                "node_id": node_id,
                "status": "done",
                "result": content.model_dump(),
                "duration_ms": duration_ms,
                "task_count": len(validated_tasks)
            }
        )
        
    except Exception as e:
        logger.error(f"Node generation failed: {e}", exc_info=True)
        
        # Mark job as failed
        db.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                result_text = ?,
                finished_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps({"error": str(e)}), job_id)
        )
        
        # Revert node status to available (allow retry)
        params_row = db.fetchone(
            "SELECT data_json FROM job_events WHERE job_id = ? AND event = 'params'",
            (job_id,)
        )
        if params_row:
            params = json.loads(params_row["data_json"])
            node_id = params.get("node_id")
            if node_id:
                db.execute(
                    "UPDATE nodes SET status = ? WHERE id = ?",
                    (NodeStatus.available.value, node_id)
                )
        
        # Publish error event
        await broker.publish(
            channel=f"job:{job_id}",
            event="error",
            data={
                "job_id": job_id,
                "status": "failed",
                "error": str(e)
            }
        )


def unlock_next_node(db: DB, completed_node_id: str) -> None:
    """
    Unlock the next node in sequence after completing current node.
    """
    try:
        # Get current node info
        current = db.fetchone(
            "SELECT unit_id, order_index FROM nodes WHERE id = ?",
            (completed_node_id,)
        )
        
        if not current:
            return
        
        unit_id = current["unit_id"]
        current_order = current["order_index"]
        
        # Find next locked node
        next_node = db.fetchone(
            """
            SELECT id FROM nodes
            WHERE unit_id = ? AND order_index = ? AND status = ?
            """,
            (unit_id, current_order + 1, NodeStatus.locked.value)
        )
        
        if next_node:
            db.execute(
                "UPDATE nodes SET status = ? WHERE id = ?",
                (NodeStatus.available.value, next_node["id"])
            )
            logger.info(f"Unlocked next node: {next_node['id']}")
        
        # Check if unit is complete
        incomplete = db.fetchone(
            """
            SELECT COUNT(*) as cnt FROM nodes
            WHERE unit_id = ? AND status != ?
            """,
            (unit_id, NodeStatus.completed.value)
        )
        
        if incomplete["cnt"] == 0:
            db.execute(
                "UPDATE units SET status = ?, completed_at = datetime('now') WHERE id = ?",
                ("completed", unit_id)
            )
            logger.info(f"Unit completed: {unit_id}")
            
    except Exception as e:
        logger.error(f"Failed to unlock next node: {e}")


# ==================== Worker Integration ====================

async def handle_path_jobs(
    *,
    db: DB,
    broker: RedisEventBroker,
    queuehub: RedisQueueHub
) -> None:
    """
    Main worker loop for path-related jobs.
    
    This should be called from run_worker.py or integrated into
    the existing worker_redis.py process_job function.
    """
    logger.info("Path worker started, listening for 'path_node_generate' jobs...")
    
    while True:
        try:
            # Dequeue job from fast queue
            dequeued = await queuehub.dequeue("q_fast", timeout_sec=5)
            
            if not dequeued:
                continue  # Timeout, retry
            
            job_id = dequeued.job_id
            
            # Check if this is a path job
            job_row = db.fetchone(
                "SELECT action FROM jobs WHERE id = ?",
                (job_id,)
            )
            
            if not job_row:
                logger.warning(f"Job {job_id} not found in DB")
                continue
            
            action = job_row["action"]
            
            if action == "path_node_generate":
                await process_path_node_generation(
                    db=db,
                    broker=broker,
                    job_id=job_id
                )
            else:
                # Not a path job, skip (will be handled by other workers)
                logger.debug(f"Skipping non-path job: {job_id} (action={action})")
                # Re-enqueue for other workers
                await queuehub.enqueue("q_fast", job_id, priority=0)
            
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            await asyncio.sleep(1)  # Brief pause before retry


# Export for integration
__all__ = [
    "process_path_node_generation",
    "handle_path_jobs",
    "unlock_next_node"
]



