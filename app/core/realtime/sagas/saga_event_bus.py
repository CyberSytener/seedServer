"""
Saga Event Bus

Provides durable saga start delivery via Redis Streams (preferred)
with a fallback to an in-memory queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)


SagaStartHandler = Callable[[Dict[str, Any]], Awaitable[None]]


class SagaEventBus:
    """Durable event bus for saga start commands."""

    def __init__(
        self,
        *,
        redis_url: Optional[str] = None,
        stream_name: str = "saga.start",
        consumer_group: str = "saga-orchestrator",
        consumer_name: Optional[str] = None,
    ) -> None:
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name or f"consumer-{uuid.uuid4().hex[:8]}"
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=10000)
        self._stop_event = asyncio.Event()
        self._redis = None

        if redis_url and redis:
            try:
                self._redis = redis.from_url(redis_url, decode_responses=True)
            except Exception as exc:
                logger.warning(f"SagaEventBus Redis init failed, using in-memory queue: {exc}")

    async def init(self) -> None:
        if not self._redis:
            return
        try:
            await self._redis.ping()
            try:
                await self._redis.xgroup_create(
                    name=self.stream_name,
                    groupname=self.consumer_group,
                    id="0",
                    mkstream=True,
                )
            except Exception:
                # Group may already exist
                pass
            logger.info("SagaEventBus Redis stream ready")
        except Exception as exc:
            logger.warning(f"SagaEventBus Redis ping failed, using in-memory queue: {exc}")
            self._redis = None

    async def publish_start(self, payload: Dict[str, Any]) -> str:
        """Publish a saga start command."""
        if self._redis:
            message_id = await self._redis.xadd(
                self.stream_name,
                {"payload": json.dumps(payload)},
            )
            return str(message_id)

        await self._queue.put(payload)
        return "local"

    async def start_consumer(
        self,
        handler: SagaStartHandler,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        """Start consuming saga start commands."""
        await self.init()

        while not self._stop_event.is_set():
            if self._redis:
                messages = await self._redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: ">"},
                    count=10,
                    block=int(poll_interval * 1000),
                )
                if not messages:
                    continue

                for _, entries in messages:
                    for message_id, data in entries:
                        try:
                            payload = json.loads(data.get("payload", "{}"))
                            await handler(payload)
                            await self._redis.xack(self.stream_name, self.consumer_group, message_id)
                        except Exception as exc:
                            logger.warning(f"SagaEventBus handler failed: {exc}")
            else:
                try:
                    payload = await asyncio.wait_for(self._queue.get(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    continue

                try:
                    await handler(payload)
                except Exception as exc:
                    logger.warning(f"SagaEventBus handler failed: {exc}")

    async def close(self) -> None:
        self._stop_event.set()
        if self._redis:
            await self._redis.close()
