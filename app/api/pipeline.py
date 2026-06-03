"""
Pipeline API - HTTP endpoints для AI конвейеров с SSE стримингом

Endpoints:
- POST /v1/pipeline/lesson/generate - Генерация урока через pipeline
- POST /v1/pipeline/diagnostic/generate - Генерация диагностики через pipeline
"""

import json
import logging
from typing import AsyncGenerator
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import authenticate
from app.dependencies import get_db
from app.infrastructure.db.sqlite import DB
from app.models.api import DiagnosticBlueprint
from app.services.pipeline.pipeline.runners import run_lesson_generation_pipeline, run_diagnostic_generation_pipeline
from app.services.pipeline.pipeline.core import PipelineEvent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])


# ============================================================================
# REQUEST MODELS
# ============================================================================

class LessonPipelineRequest(BaseModel):
    """Запрос на генерацию урока через pipeline"""
    target_lang: str = Field(..., alias="targetLang", min_length=2, max_length=50)
    native_lang: str = Field(..., alias="nativeLang", min_length=2, max_length=50)
    cefr_level: str = Field(..., alias="cefrLevel", pattern="^(A1|A2|B1|B2|C1|C2)$")
    topic: str = Field(..., min_length=3, max_length=200)
    focus: str = Field(default="grammar", pattern="^(grammar|vocabulary|conversation)$")
    
    model_config = ConfigDict(populate_by_name=True)


class DiagnosticPipelineRequest(BaseModel):
    """Запрос на генерацию диагностики через pipeline"""
    target_lang: str = Field(..., alias="targetLang", min_length=2, max_length=50)
    native_lang: str = Field(..., alias="nativeLang", min_length=2, max_length=50)
    blueprint: list[DiagnosticBlueprint]
    
    model_config = ConfigDict(populate_by_name=True)


# ============================================================================
# SSE HELPERS
# ============================================================================

def _sse_encode(event: PipelineEvent) -> str:
    """Кодировать PipelineEvent в SSE формат"""
    data = {
        "step": event.step_name,
        "status": event.status,
        "agent": event.agent,
        "message": event.message,
        "timestamp": event.timestamp
    }
    
    if event.data:
        data["data"] = event.data
    
    if event.icon:
        data["icon"] = event.icon
    
    return f"event: {event.status}\ndata: {json.dumps(data)}\n\n"


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/lesson/generate", summary="Generate Lesson Pipeline")
async def generate_lesson_pipeline(
    req: LessonPipelineRequest,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    Генерировать урок через AI Pipeline с real-time стримингом
    
    Возвращает SSE поток с прогрессом:
    - started: Шаг начался
    - working: Шаг выполняется
    - completed: Шаг завершен
    - progress: Общий прогресс конвейера
    - error: Ошибка
    
    Пример использования в JS:
    ```javascript
    const source = new EventSource('/v1/pipeline/lesson/generate');
    
    source.addEventListener('working', (e) => {
        const data = JSON.parse(e.data);
        console.log(`${data.icon} ${data.agent}: ${data.message}`);
        // 🧠 Architect: Creating lesson structure...
        // ✍️ ContentCreator: Writing dialogues...
        // 🛡️ QA Reviewer: Validating quality...
    });
    
    source.addEventListener('completed', (e) => {
        const data = JSON.parse(e.data);
        if (data.step === 'orchestrator') {
            // Конвейер завершен!
            const lesson = data.data;
        }
    });
    ```
    """
    ctx_auth = authenticate(request, db)
    
    async def event_stream() -> AsyncGenerator[str, None]:
        """SSE stream генератор"""
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def event_callback(event: PipelineEvent):
            await queue.put(_sse_encode(event))

        async def run_pipeline():
            try:
                result_ctx = await run_lesson_generation_pipeline(
                    target_lang=req.target_lang,
                    native_lang=req.native_lang,
                    cefr_level=req.cefr_level,
                    topic=req.topic,
                    focus=req.focus,
                    user_id=ctx_auth.user_id,
                    event_callback=event_callback
                )

                # Финальное событие с данными
                final_data = {
                    "lesson_plan": result_ctx.get("lesson_plan"),
                    "lesson_content": result_ctx.get("lesson_content"),
                    "validation": result_ctx.get("validation_result"),
                    "metadata": {
                        "duration": result_ctx.get_duration(),
                        "steps_completed": result_ctx.metadata["steps_completed"],
                        "pipeline_id": result_ctx.metadata["pipeline_id"]
                    }
                }
                final_event = PipelineEvent(
                    step_name="orchestrator",
                    status="final",
                    agent="System",
                    message="Lesson generation complete",
                    data=final_data,
                    icon="🎉"
                )
                await queue.put(_sse_encode(final_event))
            except Exception as e:
                logger.error(f"[PipelineAPI] Lesson generation failed: {e}", exc_info=True)
                error_event = PipelineEvent(
                    step_name="orchestrator",
                    status="error",
                    agent="System",
                    message=str(e),
                    icon="❌"
                )
                await queue.put(_sse_encode(error_event))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/diagnostic/generate", summary="Generate Diagnostic Pipeline")
async def generate_diagnostic_pipeline(
    req: DiagnosticPipelineRequest,
    request: Request,
    db: DB = Depends(get_db)
):
    """
    Генерировать диагностику через AI Pipeline с real-time стримингом
    
    Аналогично lesson/generate, но для диагностических тестов
    """
    ctx_auth = authenticate(request, db)
    
    async def event_stream() -> AsyncGenerator[str, None]:
        """SSE stream генератор"""
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def event_callback(event: PipelineEvent):
            await queue.put(_sse_encode(event))

        async def run_pipeline():
            try:
                result_ctx = await run_diagnostic_generation_pipeline(
                    target_lang=req.target_lang,
                    native_lang=req.native_lang,
                    blueprint=[bp.dict() for bp in req.blueprint],
                    user_id=ctx_auth.user_id,
                    event_callback=event_callback
                )
                final_data = {
                    "diagnostic_items": result_ctx.get("diagnostic_items"),
                    "metadata": {
                        "duration": result_ctx.get_duration(),
                        "items_generated": len(result_ctx.get("diagnostic_items", [])),
                        "pipeline_id": result_ctx.metadata["pipeline_id"]
                    }
                }
                final_event = PipelineEvent(
                    step_name="orchestrator",
                    status="final",
                    agent="System",
                    message="Diagnostic generation complete",
                    data=final_data,
                    icon="🎉"
                )
                await queue.put(_sse_encode(final_event))
            except Exception as e:
                logger.error(f"[PipelineAPI] Diagnostic generation failed: {e}", exc_info=True)
                error_event = PipelineEvent(
                    step_name="orchestrator",
                    status="error",
                    agent="System",
                    message=str(e),
                    icon="❌"
                )
                await queue.put(_sse_encode(error_event))
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



