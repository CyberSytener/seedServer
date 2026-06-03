from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional

import asyncpg

from app.core.interfaces.database import AsyncDatabaseProtocol


_SHARED_POOLS: dict[str, asyncpg.Pool] = {}
_SHARED_LOCK = asyncio.Lock()


class AsyncPGDatabase(AsyncDatabaseProtocol):
    """Async database wrapper using asyncpg pool."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    @classmethod
    async def create(
        cls,
        dsn: str,
        *,
        min_size: int = 5,
        max_size: int = 20,
        command_timeout: int = 30,
    ) -> "AsyncPGDatabase":
        pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=command_timeout,
        )
        return cls(pool)

    @classmethod
    async def get_shared(
        cls,
        dsn: str,
        *,
        min_size: int = 5,
        max_size: int = 20,
        command_timeout: int = 30,
    ) -> "AsyncPGDatabase":
        async with _SHARED_LOCK:
            pool = _SHARED_POOLS.get(dsn)
            if pool is None:
                pool = await asyncpg.create_pool(
                    dsn,
                    min_size=min_size,
                    max_size=max_size,
                    command_timeout=command_timeout,
                )
                _SHARED_POOLS[dsn] = pool
        return cls(pool)

    @classmethod
    async def close_shared(cls) -> None:
        async with _SHARED_LOCK:
            pools = list(_SHARED_POOLS.values())
            _SHARED_POOLS.clear()
        for pool in pools:
            await pool.close()

    async def fetchrow(self, query: str, *args: Any):
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetch(self, query: str, *args: Any):
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchval(self, query: str, *args: Any):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any):
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    @asynccontextmanager
    async def transaction(self):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def close(self) -> None:
        await self._pool.close()
