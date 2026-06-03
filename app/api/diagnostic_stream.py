"""
Diagnostic Streaming API - Async streaming diagnostic generation

Provides real-time streaming for diagnostic test generation using Server-Sent Events.
"""

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.auth import AuthContext, authenticate
from app.infrastructure.db.sqlite import DB
from app.infrastructure.llm.client import get_llm_client
from app.models.api import DiagnosticGenerateRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/diagnostics", tags=["diagnostics"])


def _sse_encode(event: str, data: dict) -> str:
    """Encode data as Server-Sent Event"""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_diagnostic_generation(
    request: DiagnosticGenerateRequest,
    user_id: str,
    persona_id_override: str | None = None
) -> AsyncGenerator[str, None]:
    """
    Stream diagnostic item generation with progress updates.
    
    Yields SSE events:
    - started: Generation started
    - item_progress: Progress update for each item
    - item_complete: Individual item generated
    - complete: All items generated
    - error: Generation failed
    """
    from . import persona_prompts
    
    llm_client = get_llm_client()
    start_time = time.perf_counter()
    
    try:
        # Send started event
        yield _sse_encode("started", {
            "message": "Starting diagnostic generation",
            "total_items": len(request.blueprint),
            "timestamp": time.time()
        })
        
        # Get persona
        persona_id = persona_id_override
        fallback_reason = None
        
        if persona_id:
            persona = persona_prompts.get_persona_by_id(persona_id)
            if not persona:
                fallback_reason = "persona_not_found"
                persona = persona_prompts.get_default_diagnostic_persona()
        else:
            persona = persona_prompts.get_default_diagnostic_persona()
        
        persona_id_used = persona.id if persona else None
        
        # Generate items
        items = []
        
        for idx, blueprint_item in enumerate(request.blueprint):
            # Send progress event
            yield _sse_encode("item_progress", {
                "current": idx + 1,
                "total": len(request.blueprint),
                "blueprint": {
                    "skill": blueprint_item.skill,
                    "task_type": blueprint_item.task_type,
                    "cefr_band": blueprint_item.cefr_band
                }
            })
            
            # Build prompt for this item
            prompt = f"""Generate a diagnostic test item with the following specifications:

Target Language: {request.target_lang}
Native Language: {request.native_lang}
Skill: {blueprint_item.skill}
Subskill: {blueprint_item.subskill}
Topic: {blueprint_item.topic}
Difficulty: {blueprint_item.difficulty}
Task Type: {blueprint_item.task_type}
CEFR Band: {blueprint_item.cefr_band}

Return a JSON object with:
{{
  "prompt": "The test question or sentence",
  "choices": ["option1", "option2", "option3", "option4"],
  "answers": ["correct_answer"],
  "taskType": "{blueprint_item.task_type}",
  "cefrBand": "{blueprint_item.cefr_band}",
  "skill": "{blueprint_item.skill}",
  "subskill": "{blueprint_item.subskill}",
  "distractorReasons": {{"wrong_option": "why it's wrong"}}
}}

Make the item authentic, clear, and appropriate for the CEFR level.
"""
            
            # Generate using async LLM client
            try:
                response_text = await llm_client.generate(
                    prompt=prompt,
                    temperature=0.8,
                    max_tokens=2400,
                    system_prompt=persona.system_message if persona else None
                )
                
                # Parse JSON response
                # Try to extract JSON from response
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    item_data = json.loads(json_str)
                    items.append(item_data)
                    
                    # Send item complete event
                    yield _sse_encode("item_complete", {
                        "index": idx,
                        "item": item_data
                    })
                else:
                    raise ValueError("No JSON found in response")
            
            except Exception as e:
                logger.error(f"Failed to generate item {idx}: {e}")
                # Continue with other items
                yield _sse_encode("item_error", {
                    "index": idx,
                    "error": str(e)
                })
        
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        
        # Send complete event
        yield _sse_encode("complete", {
            "diagnosticSet": {
                "items": items,
                "nativeLang": request.native_lang,
                "targetLang": request.target_lang
            },
            "personaIdUsed": persona_id_used,
            "fallbackReason": fallback_reason,
            "duration_ms": duration_ms,
            "timestamp": time.time()
        })
        
        logger.info(
            "[DIAGNOSTIC_STREAM] Items generated",
            extra={
                "user_id": user_id,
                "item_count": len(items),
                "duration_ms": duration_ms,
                "persona_id_used": persona_id_used
            }
        )
    
    except Exception as e:
        logger.error(f"[DIAGNOSTIC_STREAM] Generation failed: {e}", exc_info=True)
        yield _sse_encode("error", {
            "error": str(e),
            "timestamp": time.time()
        })


@router.post("/generate/stream")
async def generate_diagnostic_stream(
    req: DiagnosticGenerateRequest,
    request: Request,
    db: DB = Depends(lambda req: req.app.state.seed.db)
):
    """
    Generate diagnostic items with real-time streaming progress.
    
    Returns Server-Sent Events (SSE) stream with progress updates.
    
    Events:
    - started: Generation started
    - item_progress: Progress for each item (X of Y)
    - item_complete: Individual item generated
    - complete: All items complete with full diagnostic set
    - error: Generation failed
    
    Example:
        ```
        const eventSource = new EventSource('/v1/diagnostics/generate/stream');
        eventSource.addEventListener('item_progress', (e) => {
            const data = JSON.parse(e.data);
            console.log(`Progress: ${data.current} of ${data.total}`);
        });
        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse(e.data);
            console.log('Items:', data.diagnosticSet.items);
        });
        ```
    """
    ctx = authenticate(request, db)
    
    return StreamingResponse(
        stream_diagnostic_generation(
            request=req,
            user_id=ctx.user_id,
            persona_id_override=req.persona_id
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )



