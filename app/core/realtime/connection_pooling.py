"""
Connection pooling для DB и Redis - оптимизация для производства.

Обеспечивает:
- Переиспользование соединений с БД
- Переиспользование Redis соединений
- Управление жизненным циклом соединений
- Мониторинг пула соединений
- Graceful shutdown
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class PoolStatus(Enum):
    """Статус пула соединений."""
    IDLE = "idle"
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    CLOSED = "closed"


@dataclass
class ConnectionPoolConfig:
    """Конфигурация пула соединений."""
    # DB соединения
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_timeout: int = 30
    db_recycle: int = 3600  # Перезапуск соединения через час
    
    # Redis соединения
    redis_pool_size: int = 50
    redis_max_connections: int = 100
    redis_timeout: int = 10
    
    # Мониторинг
    health_check_interval: int = 60
    stale_connection_timeout: int = 300
    
    # Поведение
    auto_reconnect: bool = True
    wait_timeout: int = 5


@dataclass
class ConnectionMetrics:
    """Метрики пула соединений."""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    failed_connections: int = 0
    reused_connections: int = 0
    new_connections: int = 0
    
    # Времени
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_health_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Усреднено
    avg_connection_time_ms: float = 0.0
    avg_wait_time_ms: float = 0.0
    pool_utilization: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        return {
            "total_connections": self.total_connections,
            "active_connections": self.active_connections,
            "idle_connections": self.idle_connections,
            "failed_connections": self.failed_connections,
            "reused_connections": self.reused_connections,
            "new_connections": self.new_connections,
            "avg_connection_time_ms": self.avg_connection_time_ms,
            "avg_wait_time_ms": self.avg_wait_time_ms,
            "pool_utilization": self.pool_utilization,
            "last_health_check": self.last_health_check.isoformat()
        }


class DatabaseConnectionPool:
    """Пул соединений с БД."""
    
    def __init__(self, config: ConnectionPoolConfig):
        """Инициализация пула."""
        self.config = config
        self.metrics = ConnectionMetrics()
        self.pool = []
        self.available = asyncio.Queue()
        self.in_use = set()
        self.status = PoolStatus.IDLE
        self._lock = asyncio.Lock()
        
    async def initialize(self):
        """Инициализировать пул соединений."""
        logger.info(f"Инициализация DB пула: размер={self.config.db_pool_size}")
        
        for _ in range(self.config.db_pool_size):
            try:
                # Здесь должна быть реальная логика подключения к БД
                conn = await self._create_connection()
                await self.available.put(conn)
                self.pool.append(conn)
                self.metrics.total_connections += 1
                self.metrics.new_connections += 1
            except Exception as e:
                logger.error(f"Ошибка создания соединения: {e}")
                self.metrics.failed_connections += 1
        
        self.status = PoolStatus.ACTIVE
        logger.info(f"DB пул инициализирован: {self.metrics.total_connections} соединений")
    
    async def _create_connection(self):
        """Создать новое соединение."""
        # Симуляция создания соединения
        return {
            "id": id({}),
            "created_at": datetime.now(timezone.utc),
            "used_count": 0
        }
    
    async def acquire(self, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Получить соединение из пула."""
        timeout = timeout or self.config.db_timeout
        
        try:
            # Попытка получить существующее соединение
            conn = await asyncio.wait_for(
                self.available.get(),
                timeout=timeout
            )
            
            async with self._lock:
                self.in_use.add(conn["id"])
                self.metrics.active_connections = len(self.in_use)
                self.metrics.idle_connections = self.available.qsize()
                self.metrics.reused_connections += 1
            
            logger.debug(f"Соединение получено: {conn['id']}")
            return conn
            
        except asyncio.TimeoutError:
            # Если пул исчерпан, попытка создать новое
            if len(self.in_use) < self.config.db_pool_size + self.config.db_max_overflow:
                try:
                    conn = await self._create_connection()
                    async with self._lock:
                        self.in_use.add(conn["id"])
                        self.metrics.total_connections += 1
                        self.metrics.new_connections += 1
                    logger.info(f"Создано новое соединение: {conn['id']}")
                    return conn
                except Exception as e:
                    logger.error(f"Ошибка создания нового соединения: {e}")
                    self.metrics.failed_connections += 1
                    self.status = PoolStatus.EXHAUSTED
                    raise
            else:
                logger.error("Пул соединений исчерпан")
                self.status = PoolStatus.EXHAUSTED
                raise RuntimeError("Connection pool exhausted")
    
    async def release(self, conn: Dict[str, Any]):
        """Вернуть соединение в пул."""
        try:
            async with self._lock:
                if conn["id"] in self.in_use:
                    self.in_use.remove(conn["id"])
                conn["used_count"] += 1
                self.metrics.active_connections = len(self.in_use)
                self.metrics.idle_connections = self.available.qsize()
            
            # Проверить возраст соединения
            age_seconds = (datetime.now(timezone.utc) - conn["created_at"]).total_seconds()
            if age_seconds > self.config.db_recycle:
                logger.debug(f"Соединение {conn['id']} выработало ресурс, удаление")
                self.pool.remove(conn)
                self.metrics.total_connections -= 1
            else:
                await self.available.put(conn)
                
        except Exception as e:
            logger.error(f"Ошибка возврата соединения: {e}")
    
    async def health_check(self):
        """Проверка здоровья пула."""
        logger.debug("Проверка здоровья DB пула")
        self.metrics.last_health_check = datetime.now(timezone.utc)
        
        # Проверить все соединения
        for conn in self.pool:
            try:
                # Здесь должна быть реальная проверка соединения
                age = (datetime.now(timezone.utc) - conn["created_at"]).total_seconds()
                if age > self.config.stale_connection_timeout:
                    logger.warning(f"Соединение {conn['id']} устарело")
                    self.pool.remove(conn)
                    self.metrics.total_connections -= 1
            except Exception as e:
                logger.error(f"Ошибка проверки соединения: {e}")
        
        # Пересчитать утилизацию
        if self.metrics.total_connections > 0:
            self.metrics.pool_utilization = (
                self.metrics.active_connections / self.metrics.total_connections
            )
    
    async def close_all(self):
        """Закрыть все соединения."""
        logger.info("Закрытие всех DB соединений")
        
        # Дождаться, пока все соединения вернутся
        while not self.available.empty() or self.in_use:
            await asyncio.sleep(0.1)
        
        self.pool.clear()
        self.status = PoolStatus.CLOSED
        logger.info("Все DB соединения закрыты")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Получить метрики пула."""
        return self.metrics.to_dict()


class RedisConnectionPool:
    """Пул соединений с Redis."""
    
    def __init__(self, config: ConnectionPoolConfig):
        """Инициализация пула Redis."""
        self.config = config
        self.metrics = ConnectionMetrics()
        self.pool = []
        self.available = asyncio.Queue()
        self.in_use = set()
        self.status = PoolStatus.IDLE
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Инициализировать Redis пул."""
        logger.info(f"Инициализация Redis пула: размер={self.config.redis_pool_size}")
        
        for _ in range(self.config.redis_pool_size):
            try:
                conn = await self._create_connection()
                await self.available.put(conn)
                self.pool.append(conn)
                self.metrics.total_connections += 1
                self.metrics.new_connections += 1
            except Exception as e:
                logger.error(f"Ошибка создания Redis соединения: {e}")
                self.metrics.failed_connections += 1
        
        self.status = PoolStatus.ACTIVE
        logger.info(f"Redis пул инициализирован: {self.metrics.total_connections} соединений")
    
    async def _create_connection(self):
        """Создать новое Redis соединение."""
        return {
            "id": id({}),
            "created_at": datetime.now(timezone.utc),
            "used_count": 0,
            "bytes_sent": 0,
            "bytes_received": 0
        }
    
    async def acquire(self, timeout: Optional[int] = None):
        """Получить Redis соединение."""
        timeout = timeout or self.config.redis_timeout
        
        try:
            conn = await asyncio.wait_for(
                self.available.get(),
                timeout=timeout
            )
            
            async with self._lock:
                self.in_use.add(conn["id"])
                self.metrics.active_connections = len(self.in_use)
                self.metrics.idle_connections = self.available.qsize()
                self.metrics.reused_connections += 1
            
            return conn
            
        except asyncio.TimeoutError:
            if len(self.in_use) < self.config.redis_max_connections:
                conn = await self._create_connection()
                async with self._lock:
                    self.in_use.add(conn["id"])
                    self.metrics.total_connections += 1
                    self.metrics.new_connections += 1
                return conn
            else:
                self.status = PoolStatus.EXHAUSTED
                raise RuntimeError("Redis connection pool exhausted")
    
    async def release(self, conn: Dict[str, Any]):
        """Вернуть Redis соединение."""
        async with self._lock:
            if conn["id"] in self.in_use:
                self.in_use.remove(conn["id"])
            self.metrics.active_connections = len(self.in_use)
            self.metrics.idle_connections = self.available.qsize()
        
        await self.available.put(conn)
    
    async def close_all(self):
        """Закрыть все Redis соединения."""
        logger.info("Закрытие всех Redis соединений")
        
        while not self.available.empty() or self.in_use:
            await asyncio.sleep(0.1)
        
        self.pool.clear()
        self.status = PoolStatus.CLOSED


class ConnectionPoolManager:
    """Менеджер пулов соединений."""
    
    _instance: Optional['ConnectionPoolManager'] = None
    
    def __init__(self, config: ConnectionPoolConfig = None):
        """Инициализация менеджера."""
        self.config = config or ConnectionPoolConfig()
        self.db_pool = DatabaseConnectionPool(self.config)
        self.redis_pool = RedisConnectionPool(self.config)
    
    @classmethod
    def get_instance(cls, config: ConnectionPoolConfig = None) -> 'ConnectionPoolManager':
        """Получить единственный экземпляр (Singleton)."""
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance
    
    async def initialize(self):
        """Инициализировать все пулы."""
        logger.info("Инициализация всех пулов соединений")
        await asyncio.gather(
            self.db_pool.initialize(),
            self.redis_pool.initialize()
        )
        logger.info("Все пулы инициализированы")
    
    async def shutdown(self):
        """Завершить работу всех пулов."""
        logger.info("Завершение работы пулов соединений")
        await asyncio.gather(
            self.db_pool.close_all(),
            self.redis_pool.close_all()
        )
        logger.info("Все пулы закрыты")
    
    async def health_check_loop(self):
        """Цикл проверки здоровья."""
        while True:
            try:
                await asyncio.gather(
                    self.db_pool.health_check(),
                    self.redis_pool.health_check()
                )
                await asyncio.sleep(self.config.health_check_interval)
            except Exception as e:
                logger.error(f"Ошибка в цикле проверки здоровья: {e}")
                await asyncio.sleep(5)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Получить метрики всех пулов."""
        return {
            "db_pool": self.db_pool.get_metrics(),
            "redis_pool": self.redis_pool.get_metrics(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Глобальный экземпляр
_pool_manager: Optional[ConnectionPoolManager] = None


def get_pool_manager() -> ConnectionPoolManager:
    """Получить менеджер пулов."""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager.get_instance()
    return _pool_manager


def init_pools(config: ConnectionPoolConfig = None) -> ConnectionPoolManager:
    """Инициализировать пулы соединений."""
    global _pool_manager
    _pool_manager = ConnectionPoolManager.get_instance(config)
    return _pool_manager
