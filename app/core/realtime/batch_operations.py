"""
Batch операции для множественных саг - оптимизация производительности.

Обеспечивает:
- Групповое выполнение операций
- Пакетная компенсация
- Массовые обновления статусов
- Оптимизированные запросы в БД
- Снижение round-trip времени
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class BatchOperationType(Enum):
    """Типы батч операций."""
    COMPENSATE = "compensate"
    UPDATE_STATUS = "update_status"
    COMPLETE = "complete"
    RETRY = "retry"
    SKIP = "skip"
    PAUSE = "pause"
    RESUME = "resume"
    DELETE = "delete"


@dataclass
class BatchOperation:
    """Описание батч операции."""
    saga_id: str
    operation_type: BatchOperationType
    data: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def __hash__(self):
        """Для использования в Set."""
        return hash((self.saga_id, self.operation_type.value))
    
    def __eq__(self, other):
        """Сравнение операций."""
        if not isinstance(other, BatchOperation):
            return False
        return (self.saga_id == other.saga_id and 
                self.operation_type == other.operation_type)


@dataclass
class BatchResult:
    """Результат батч операции."""
    operation_type: BatchOperationType
    total_sagas: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Процент успеха."""
        if self.total_sagas == 0:
            return 0.0
        return self.successful / self.total_sagas
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        return {
            "operation_type": self.operation_type.value,
            "total_sagas": self.total_sagas,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "success_rate": self.success_rate,
            "duration_seconds": self.duration_seconds,
            "errors_count": len(self.errors)
        }


class BatchOperationQueue:
    """Очередь батч операций."""
    
    def __init__(self, 
                 batch_size: int = 100,
                 batch_timeout: float = 5.0,
                 max_queue_size: int = 10000):
        """Инициализация очереди.
        
        Args:
            batch_size: Размер батча перед выполнением
            batch_timeout: Таймаут сбора батча (сек)
            max_queue_size: Максимальный размер очереди
        """
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.max_queue_size = max_queue_size
        
        self.queue: Dict[BatchOperationType, List[BatchOperation]] = {
            op_type: [] for op_type in BatchOperationType
        }
        self.pending_operations: Set[BatchOperation] = set()
        self.operation_locks: Dict[str, asyncio.Lock] = {}
        
        self._lock = asyncio.Lock()
        self._condition = asyncio.Condition(self._lock)
    
    async def add_operation(self, operation: BatchOperation) -> bool:
        """Добавить операцию в очередь.
        
        Args:
            operation: Операция для добавления
            
        Returns:
            True если добавлена, False если очередь переполнена
        """
        async with self._lock:
            # Проверить размер очереди
            total_ops = sum(len(ops) for ops in self.queue.values())
            if total_ops >= self.max_queue_size:
                logger.warning(f"Очередь батч операций переполнена ({total_ops})")
                return False
            
            # Добавить операцию
            self.queue[operation.operation_type].append(operation)
            self.pending_operations.add(operation)
            
            # Уведомить ожидающие потоки
            self._condition.notify()
            
            logger.debug(f"Операция добавлена: {operation.operation_type.value} для {operation.saga_id}")
            return True
    
    async def get_batch(self, operation_type: BatchOperationType) -> List[BatchOperation]:
        """Получить батч операций.
        
        Args:
            operation_type: Тип операций
            
        Returns:
            Список операций для выполнения
        """
        async with self._condition:
            # Ждать батч или таймаут
            while len(self.queue[operation_type]) < self.batch_size:
                try:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=self.batch_timeout
                    )
                except asyncio.TimeoutError:
                    break
            
            # Получить операции
            batch = self.queue[operation_type][:self.batch_size]
            self.queue[operation_type] = self.queue[operation_type][self.batch_size:]
            
            return batch
    
    async def mark_completed(self, operations: List[BatchOperation]):
        """Отметить операции как выполненные.
        
        Args:
            operations: Выполненные операции
        """
        async with self._lock:
            for op in operations:
                self.pending_operations.discard(op)
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Получить статистику очереди."""
        total_ops = sum(len(ops) for ops in self.queue.values())
        return {
            "total_pending": total_ops,
            "by_type": {
                op_type.value: len(ops)
                for op_type, ops in self.queue.items()
            }
        }


class BatchExecutor:
    """Исполнитель батч операций."""
    
    def __init__(self, queue: BatchOperationQueue):
        """Инициализация исполнителя.
        
        Args:
            queue: Очередь операций
        """
        self.queue = queue
        self.handlers: Dict[BatchOperationType, Callable] = {}
        self.results: List[BatchResult] = []
        self._running = False
    
    def register_handler(self, 
                        operation_type: BatchOperationType,
                        handler: Callable):
        """Зарегистрировать обработчик типа операции.
        
        Args:
            operation_type: Тип операции
            handler: Асинхронная функция обработчика
        """
        self.handlers[operation_type] = handler
        logger.info(f"Зарегистрирован обработчик: {operation_type.value}")
    
    async def execute_batch(self, 
                          operation_type: BatchOperationType,
                          batch: List[BatchOperation]) -> BatchResult:
        """Выполнить батч операций.
        
        Args:
            operation_type: Тип операций
            batch: Список операций
            
        Returns:
            Результат выполнения
        """
        if not batch:
            return BatchResult(operation_type=operation_type)
        
        start_time = datetime.now(timezone.utc)
        result = BatchResult(
            operation_type=operation_type,
            total_sagas=len(batch)
        )
        
        handler = self.handlers.get(operation_type)
        if not handler:
            logger.error(f"Обработчик не найден: {operation_type.value}")
            result.failed = len(batch)
            return result
        
        # Выполнить все операции в батче параллельно
        tasks = []
        for operation in batch:
            task = self._execute_single(handler, operation, result)
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обновить времени выполнения
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        result.duration_seconds = duration
        
        # Логировать результаты
        logger.info(
            f"Батч выполнен: {operation_type.value}, "
            f"успешно={result.successful}/{result.total_sagas}, "
            f"ошибок={len(result.errors)}, "
            f"время={duration:.2f}s"
        )
        
        self.results.append(result)
        return result
    
    async def _execute_single(self,
                            handler: Callable,
                            operation: BatchOperation,
                            result: BatchResult):
        """Выполнить одну операцию.
        
        Args:
            handler: Обработчик операции
            operation: Операция
            result: Объект результата (для обновления)
        """
        try:
            # Выполнить операцию
            await handler(operation)
            result.successful += 1
            logger.debug(f"Операция выполнена: {operation.saga_id}")
            
        except Exception as e:
            logger.error(f"Ошибка в операции {operation.saga_id}: {e}")
            result.failed += 1
            result.errors.append({
                "saga_id": operation.saga_id,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            # Попытка повторить при необходимости
            if operation.retry_count < operation.max_retries:
                operation.retry_count += 1
                logger.info(f"Повторная попытка {operation.saga_id} ({operation.retry_count}/{operation.max_retries})")
                await self.queue.add_operation(operation)
    
    async def run(self):
        """Запустить исполнитель батч операций."""
        self._running = True
        logger.info("Запуск исполнителя батч операций")
        
        try:
            while self._running:
                # Обработать каждый тип операции
                tasks = []
                for operation_type in BatchOperationType:
                    task = self._process_operation_type(operation_type)
                    tasks.append(task)
                
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"Ошибка в исполнителе батч операций: {e}")
        finally:
            logger.info("Исполнитель батч операций остановлен")
    
    async def _process_operation_type(self, operation_type: BatchOperationType):
        """Обработать один тип операций.
        
        Args:
            operation_type: Тип операций
        """
        try:
            batch = await self.queue.get_batch(operation_type)
            if batch:
                await self.execute_batch(operation_type, batch)
                await self.queue.mark_completed(batch)
        except Exception as e:
            logger.error(f"Ошибка обработки {operation_type.value}: {e}")
    
    def stop(self):
        """Остановить исполнитель."""
        self._running = False
        logger.info("Остановка исполнителя батч операций")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику выполнения.
        
        Returns:
            Статистика батч операций
        """
        total_operations = sum(r.total_sagas for r in self.results)
        total_successful = sum(r.successful for r in self.results)
        total_failed = sum(r.failed for r in self.results)
        
        return {
            "queue_stats": self.queue.get_queue_stats(),
            "total_operations": total_operations,
            "total_successful": total_successful,
            "total_failed": total_failed,
            "success_rate": (
                total_successful / total_operations 
                if total_operations > 0 else 0.0
            ),
            "by_type": {
                result.operation_type.value: result.to_dict()
                for result in self.results
            }
        }


# Глобальный экземпляр
_batch_executor: Optional[BatchExecutor] = None


def get_batch_executor() -> BatchExecutor:
    """Получить исполнитель батч операций."""
    global _batch_executor
    if _batch_executor is None:
        queue = BatchOperationQueue()
        _batch_executor = BatchExecutor(queue)
    return _batch_executor


def init_batch_executor(batch_size: int = 100,
                       batch_timeout: float = 5.0) -> BatchExecutor:
    """Инициализировать исполнитель батч операций.
    
    Args:
        batch_size: Размер батча
        batch_timeout: Таймаут сбора батча
        
    Returns:
        Инициализированный исполнитель
    """
    global _batch_executor
    queue = BatchOperationQueue(
        batch_size=batch_size,
        batch_timeout=batch_timeout
    )
    _batch_executor = BatchExecutor(queue)
    return _batch_executor
