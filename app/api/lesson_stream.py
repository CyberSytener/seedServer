"""
Streaming Lesson Generation API

Provides progressive delivery of lessons using Server-Sent Events (SSE).
This dramatically improves perceived latency and UX.
"""

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.auth import AuthContext, authenticate
from app.dependencies import get_db
from app.infrastructure.db.sqlite import DB
from app.infrastructure.llm.client import get_llm_client
from app.models.api import LessonGenerateRequest
from . import persona_prompts
from app.settings import get_settings


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/lessons", tags=["lessons-streaming"])


def _sse_encode(event: str, data: dict) -> str:
    """Encode data as Server-Sent Event"""
    data_json = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data_json}\n\n"


async def stream_lesson_generation(
    req: LessonGenerateRequest,
    ctx: AuthContext,
    db: DB,
    persona_prompts_module
) -> AsyncIterator[str]:
    """
    Generate lesson progressively with streaming updates.
    
    Yields SSE events:
    - started: Generation has begun
    - progress: Partial content received
    - complete: Full lesson ready
    - error: Generation failed
    """
    lesson_id = f"lesson_{int(time.time() * 1000)}_{ctx.user_id[:8]}"
    settings = get_settings()
    
    try:
        # Send start event
        yield _sse_encode("started", {
            "lesson_id": lesson_id,
            "status": "generating"
        })
        
        # Resolve persona
        persona_result = persona_prompts_module.get_persona_prompt(req.persona_id)
        persona_prompt = persona_result.prompt_text
        persona_id_used = persona_result.persona_id_used
        
        # Build prompts
        system_prompt = f"""{persona_prompt}

---
LESSON GENERATION MODE:
You are generating a structured language learning lesson.

Output a valid JSON object with this structure:
{{
  "lessonId": "{lesson_id}",
  "mode": "{req.mode}",
  "targetLang": "{req.target_lang}",
  "nativeLang": "{req.native_lang}",
  "level": "{req.level}",
  "topic": "{req.topic or 'general'}",
  "title": "Lesson Title",
  "tasks": [
    {{
      "type": "mcq|translate|fill_blank|word_order",
      "prompt": "Task instruction in {req.native_lang}",
      "content": {{}},
      "grading": {{}},
      "difficulty": "easy|medium|hard"
    }}
  ]
}}

Create exactly {req.lesson_length} diverse, engaging tasks.
IMPORTANT: Return ONLY valid JSON, no markdown, no code blocks."""

        user_prompt = f"""Generate a {req.mode} lesson for learning {req.target_lang} (learner speaks {req.native_lang}).

Level: {req.level}
Topic: {req.topic or "general"}
Number of tasks: {req.lesson_length}

Create {req.lesson_length} tasks mixing different types (mcq, translate, fill_blank, word_order)."""

        # Stream from LLM
        client = await get_llm_client()
        
        accumulated_text = ""
        chunk_count = 0
        start_time = time.perf_counter()
        
        async for chunk in client.generate_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            provider=settings.default_provider_fast or "gemini",
            model=settings.gemini_model_fast or "gemini-2.0-flash-exp",
            max_tokens=12000,
            timeout_sec=90
        ):
            if chunk.text:
                accumulated_text += chunk.text
                chunk_count += 1
                
                # Send progress updates every 5 chunks
                if chunk_count % 5 == 0:
                    yield _sse_encode("progress", {
                        "lesson_id": lesson_id,
                        "bytes_received": len(accumulated_text),
                        "status": "streaming"
                    })
            
            if chunk.is_final:
                # Parse complete response
                try:
                    # Clean JSON from markdown
                    cleaned = accumulated_text.strip()
                    if cleaned.startswith("```"):
                        lines = cleaned.split("\n")
                        start_idx = 1 if lines[0].startswith("```") else 0
                        end_idx = len(lines)
                        for i in range(len(lines) - 1, -1, -1):
                            if lines[i].strip().startswith("```"):
                                end_idx = i
                                break
                        cleaned = "\n".join(lines[start_idx:end_idx])
                    
                    lesson_data = json.loads(cleaned)
                    
                    # Basic validation
                    if not lesson_data.get("tasks") or len(lesson_data["tasks"]) == 0:
                        raise ValueError("No tasks in lesson")
                    
                    # Store in database
                    lesson_json = json.dumps(lesson_data)
                    db.execute(
                        "INSERT INTO lessons(id, user_id, lesson_json, persona_id_used, created_at) VALUES(?,?,?,?,datetime('now'))",
                        (lesson_id, ctx.user_id, lesson_json, persona_id_used)
                    )
                    
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    
                    # Send completion event
                    yield _sse_encode("complete", {
                        "lesson_id": lesson_id,
                        "lesson": lesson_data,
                        "persona_id_used": persona_id_used,
                        "duration_ms": duration_ms,
                        "tokens_in": chunk.tokens_in,
                        "tokens_out": chunk.tokens_out
                    })
                    
                    logger.info(
                        f"Streamed lesson {lesson_id} in {duration_ms}ms "
                        f"({chunk_count} chunks, {len(accumulated_text)} bytes)"
                    )
                    
                except (json.JSONDecodeError, ValueError) as e:
                    yield _sse_encode("error", {
                        "lesson_id": lesson_id,
                        "error": f"Failed to parse lesson: {str(e)}",
                        "status": "failed"
                    })
                    logger.error(f"Failed to parse streamed lesson: {e}")
        
    except Exception as e:
        yield _sse_encode("error", {
            "lesson_id": lesson_id,
            "error": str(e),
            "status": "failed"
        })
        logger.error(f"Lesson streaming error: {e}", exc_info=True)


@router.post("/generate/stream")
async def generate_lesson_stream(
    req: LessonGenerateRequest,
    request: Request,
    db: DB = Depends(get_db),
):
    """
    Generate lesson with progressive streaming delivery.
    
    Returns Server-Sent Events (SSE) stream with real-time updates:
    
    **Events:**
    - `started`: Generation initiated
    - `progress`: Partial content received (periodic updates)
    - `complete`: Full lesson ready with all data
    - `error`: Generation failed
    
    **Benefits:**
    - 🚀 Immediate feedback (first byte < 1s)
    - 📊 Real-time progress tracking
    - ⚡ Perceived latency reduction
    - 🔄 Can show partial results
    
    **Client Usage:**
    ```javascript
    const eventSource = new EventSource('/v1/lessons/generate/stream', {
        headers: { 'Authorization': 'Bearer token' }
    });
    
    eventSource.addEventListener('started', (e) => {
        const data = JSON.parse(e.data);
        console.log('Started:', data.lesson_id);
    });
    
    eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        updateProgressBar(data.bytes_received);
    });
    
    eventSource.addEventListener('complete', (e) => {
        const data = JSON.parse(e.data);
        displayLesson(data.lesson);
        eventSource.close();
    });
    
    eventSource.addEventListener('error', (e) => {
        const data = JSON.parse(e.data);
        showError(data.error);
        eventSource.close();
    });
    ```
    """
    # Use global persona_prompts module
    from . import persona_prompts as persona_prompts_manager
    
    ctx = authenticate(request, db)
    
    return StreamingResponse(
        stream_lesson_generation(req, ctx, db, persona_prompts_manager),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )



