"""
Core Pipeline Infrastructure - Базовые абстракции для AI конвейеров
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable, Awaitable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineEvent:
    """Событие конвейера для SSE трансляции"""
    step_name: str
    status: str  # "started", "working", "completed", "error"
    agent: str  # "Architect", "ContentCreator", "Reviewer"
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: float = field(default_factory=time.time)
    icon: Optional[str] = None  # "🧠", "✍️", "🛡️", etc.


class PipelineContext:
    """
    Context Bus - Шина контекста для передачи данных между шагами
    
    Пример:
        ctx = PipelineContext({"user_request": "Хочу курс по Python"})
        ctx.set("plan", plan_json)
        plan = ctx.get("plan")
    """
    
    def __init__(self, initial_data: Optional[Dict[str, Any]] = None):
        self.data: Dict[str, Any] = initial_data or {}
        self.history: List[Dict[str, Any]] = []
        self.events: List[PipelineEvent] = []
        self.start_time = time.time()
        self.metadata: Dict[str, Any] = {
            "pipeline_id": f"pipe_{int(time.time() * 1000)}",
            "steps_completed": 0,
            "errors": []
        }
    
    def set(self, key: str, value: Any) -> None:
        """Записать значение в контекст"""
        self.data[key] = value
        self.history.append({
            "action": "set",
            "key": key,
            "timestamp": time.time()
        })
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение из контекста"""
        return self.data.get(key, default)
    
    def has(self, key: str) -> bool:
        """Проверить наличие ключа"""
        return key in self.data
    
    def update(self, data: Dict[str, Any]) -> None:
        """Обновить несколько значений"""
        self.data.update(data)
    
    def emit_event(self, event: PipelineEvent) -> None:
        """Добавить событие в историю"""
        self.events.append(event)
    
    def get_duration(self) -> float:
        """Получить длительность работы конвейера в секундах"""
        return time.time() - self.start_time
    
    def increment_steps(self) -> None:
        """Увеличить счетчик завершенных шагов"""
        self.metadata["steps_completed"] += 1
    
    def add_error(self, error: str) -> None:
        """Добавить ошибку"""
        self.metadata["errors"].append({
            "error": error,
            "timestamp": time.time()
        })


class PipelineStep(ABC):
    """
    Абстрактный шаг конвейера
    
    Каждый шаг:
    - Читает данные из ctx
    - Вызывает LLM (или другую логику)
    - Записывает результат обратно в ctx
    """
    
    def __init__(self, name: Optional[str] = None, agent_name: Optional[str] = None, icon: Optional[str] = None):
        self.name = name or self.__class__.__name__
        self.agent_name = agent_name or "Agent"
        self.icon = icon or "⚙️"
    
    @abstractmethod
    async def execute(self, ctx: PipelineContext) -> None:
        """
        Выполнить шаг конвейера
        
        Args:
            ctx: Контекст конвейера с данными
        """
        pass
    
    async def _emit_start(self, ctx: PipelineContext, message: str) -> None:
        """Отправить событие начала шага"""
        event = PipelineEvent(
            step_name=self.name,
            status="started",
            agent=self.agent_name,
            message=message,
            icon=self.icon
        )
        ctx.emit_event(event)
        logger.info(f"[Pipeline] {self.name} started: {message}")
    
    async def _emit_working(self, ctx: PipelineContext, message: str, data: Optional[Dict] = None) -> None:
        """Отправить событие работы шага"""
        event = PipelineEvent(
            step_name=self.name,
            status="working",
            agent=self.agent_name,
            message=message,
            data=data,
            icon=self.icon
        )
        ctx.emit_event(event)
    
    async def _emit_complete(self, ctx: PipelineContext, message: str, data: Optional[Dict] = None) -> None:
        """Отправить событие завершения шага"""
        event = PipelineEvent(
            step_name=self.name,
            status="completed",
            agent=self.agent_name,
            message=message,
            data=data,
            icon=self.icon
        )
        ctx.emit_event(event)
        logger.info(f"[Pipeline] {self.name} completed: {message}")
    
    async def _emit_error(self, ctx: PipelineContext, error: str) -> None:
        """Отправить событие ошибки"""
        event = PipelineEvent(
            step_name=self.name,
            status="error",
            agent=self.agent_name,
            message=f"Error: {error}",
            icon="❌"
        )
        ctx.emit_event(event)
        logger.error(f"[Pipeline] {self.name} error: {error}")


class PipelineOrchestrator:
    """
    Orchestrator - Дирижёр конвейера
    
    Управляет последовательностью выполнения шагов и
    опционально транслирует события через callback
    """
    
    def __init__(
        self,
        steps: List[PipelineStep],
        event_callback: Optional[Callable[[PipelineEvent], Awaitable[None]]] = None
    ):
        self.steps = steps
        self.event_callback = event_callback
    
    async def run(self, ctx: PipelineContext) -> PipelineContext:
        """
        Запустить конвейер
        
        Args:
            ctx: Начальный контекст
            
        Returns:
            Обновленный контекст с результатами
        """
        total_steps = len(self.steps)
        
        logger.info(f"[Orchestrator] Starting pipeline with {total_steps} steps")
        
        for idx, step in enumerate(self.steps, 1):
            try:
                # Прогресс
                progress_event = PipelineEvent(
                    step_name="orchestrator",
                    status="progress",
                    agent="System",
                    message=f"Step {idx}/{total_steps}: {step.name}",
                    data={"current": idx, "total": total_steps, "step": step.name},
                    icon="📊"
                )
                ctx.emit_event(progress_event)
                
                if self.event_callback:
                    await self.event_callback(progress_event)
                
                # Выполнить шаг
                await step.execute(ctx)
                ctx.increment_steps()
                
                # Транслировать события этого шага через callback
                if self.event_callback and ctx.events:
                    # Отправляем только новые события (последние)
                    for event in ctx.events[-(len(ctx.events)):]:
                        if event.step_name == step.name:
                            await self.event_callback(event)
            
            except Exception as e:
                error_msg = f"Step {step.name} failed: {str(e)}"
                ctx.add_error(error_msg)
                
                error_event = PipelineEvent(
                    step_name=step.name,
                    status="error",
                    agent=step.agent_name,
                    message=error_msg,
                    icon="❌"
                )
                ctx.emit_event(error_event)
                
                if self.event_callback:
                    await self.event_callback(error_event)
                
                logger.error(f"[Orchestrator] {error_msg}", exc_info=True)
                
                # В зависимости от критичности можно продолжить или остановить
                # Сейчас останавливаем
                raise
        
        # Финальное событие
        final_event = PipelineEvent(
            step_name="orchestrator",
            status="completed",
            agent="System",
            message=f"Pipeline completed in {ctx.get_duration():.2f}s",
            data={
                "duration": ctx.get_duration(),
                "steps_completed": ctx.metadata["steps_completed"],
                "total_steps": total_steps
            },
            icon="✅"
        )
        ctx.emit_event(final_event)
        
        if self.event_callback:
            await self.event_callback(final_event)
        
        logger.info(f"[Orchestrator] Pipeline completed successfully")
        
        return ctx
