"""
Pipeline Runners - Готовые конвейеры для разных задач
"""

import logging
from typing import Optional, Callable, Awaitable

from .core import PipelineContext, PipelineOrchestrator, PipelineEvent
from .steps import (
    LessonPlannerStep,
    LessonContentStep,
    LessonValidatorStep,
    DiagnosticPlannerStep,
    DiagnosticGeneratorStep
)

logger = logging.getLogger(__name__)


async def run_lesson_generation_pipeline(
    target_lang: str,
    native_lang: str,
    cefr_level: str,
    topic: str,
    focus: str = "grammar",
    user_id: Optional[str] = None,
    event_callback: Optional[Callable[[PipelineEvent], Awaitable[None]]] = None
) -> PipelineContext:
    """
    Запустить полный конвейер генерации урока
    
    Этапы:
    1. Architect (🧠) - Создает структуру урока
    2. ContentCreator (✍️) - Пишет живой контент
    3. QA Reviewer (🛡️) - Проверяет качество
    
    Args:
        target_lang: Целевой язык для изучения
        native_lang: Родной язык ученика
        cefr_level: CEFR уровень (A1, A2, B1, B2, C1, C2)
        topic: Тема урока
        focus: Фокус урока (grammar, vocabulary, conversation)
        user_id: ID пользователя (опционально)
        event_callback: Коллбэк для SSE событий
    
    Returns:
        PipelineContext с результатами в ctx.data
    """
    
    logger.info(f"[LessonPipeline] Starting for {target_lang}, level {cefr_level}, topic '{topic}'")
    
    # Создаем начальный контекст
    ctx = PipelineContext({
        "target_lang": target_lang,
        "native_lang": native_lang,
        "cefr_level": cefr_level,
        "topic": topic,
        "focus": focus,
        "user_id": user_id
    })
    
    # Определяем цепочку шагов
    steps = [
        LessonPlannerStep(),      # 🧠 Архитектор
        LessonContentStep(),      # ✍️ Креатор
        LessonValidatorStep()     # 🛡️ Валидатор
    ]
    
    # Создаем оркестратор
    orchestrator = PipelineOrchestrator(steps=steps, event_callback=event_callback)
    
    # Запускаем конвейер
    result_ctx = await orchestrator.run(ctx)
    
    logger.info(
        f"[LessonPipeline] Completed in {result_ctx.get_duration():.2f}s, "
        f"{result_ctx.metadata['steps_completed']} steps"
    )
    
    return result_ctx


async def run_diagnostic_generation_pipeline(
    target_lang: str,
    native_lang: str,
    blueprint: list,
    user_id: Optional[str] = None,
    event_callback: Optional[Callable[[PipelineEvent], Awaitable[None]]] = None
) -> PipelineContext:
    """
    Запустить конвейер генерации диагностики
    
    Этапы:
    1. Test Architect (🎯) - Оптимизирует план тестирования
    2. Item Writer (📝) - Генерирует задания
    
    Args:
        target_lang: Целевой язык
        native_lang: Родной язык
        blueprint: План диагностических заданий
        user_id: ID пользователя
        event_callback: Коллбэк для SSE
    
    Returns:
        PipelineContext с результатами
    """
    
    logger.info(f"[DiagnosticPipeline] Starting for {target_lang}, {len(blueprint)} items")
    
    ctx = PipelineContext({
        "target_lang": target_lang,
        "native_lang": native_lang,
        "blueprint": blueprint,
        "user_id": user_id
    })
    
    steps = [
        DiagnosticPlannerStep(),    # 🎯 Планировщик
        DiagnosticGeneratorStep()   # 📝 Генератор
    ]
    
    orchestrator = PipelineOrchestrator(steps=steps, event_callback=event_callback)
    
    result_ctx = await orchestrator.run(ctx)
    
    logger.info(
        f"[DiagnosticPipeline] Completed in {result_ctx.get_duration():.2f}s, "
        f"{len(result_ctx.get('diagnostic_items', []))} items generated"
    )
    
    return result_ctx
