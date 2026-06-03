from __future__ import annotations

from typing import Any

import redis.asyncio as redis

from app.core.interfaces.cache import AsyncCacheProtocol, AsyncPipelineProtocol


class RedisPipelineAdapter(AsyncPipelineProtocol):
    def __init__(self, pipeline: redis.client.Pipeline):
        self._pipeline = pipeline

    def incr(self, key: str) -> Any:
        return self._pipeline.incr(key)

    def ttl(self, key: str) -> Any:
        return self._pipeline.ttl(key)

    async def execute(self) -> list[Any]:
        return await self._pipeline.execute()


class RedisCacheAdapter(AsyncCacheProtocol):
    """Async Redis cache adapter implementing the core Cache protocol."""

    def __init__(self, client: redis.Redis):
        self._client = client

    async def get(self, key: str) -> Any:
        return await self._client.get(key)

    async def set(self, key: str, value: Any, *, ex: int | None = None, nx: bool | None = None) -> Any:
        return await self._client.set(key, value, ex=ex, nx=nx)

    async def setex(self, key: str, ttl: int, value: Any) -> Any:
        return await self._client.setex(key, ttl, value)

    async def delete(self, *keys: str) -> Any:
        return await self._client.delete(*keys)

    async def incr(self, key: str) -> Any:
        return await self._client.incr(key)

    async def ttl(self, key: str) -> Any:
        return await self._client.ttl(key)

    async def expire(self, key: str, ttl: int) -> Any:
        return await self._client.expire(key, ttl)

    def pipeline(self) -> AsyncPipelineProtocol:
        return RedisPipelineAdapter(self._client.pipeline())

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        return await self._client.eval(script, numkeys, *keys_and_args)
