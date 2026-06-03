"""Database helpers for saga orchestration."""

from __future__ import annotations

from typing import Any


class AsyncPGPoolProxy:
    """Proxy that exposes fetch/execute methods on top of asyncpg pool."""

    def __init__(self, pool: Any):
        self._pool = pool

    async def acquire(self):
        return await self._pool.acquire()

    async def release(self, conn: Any):
        await self._pool.release(conn)

    async def close(self):
        await self._pool.close()

    async def fetchrow(self, query: str, *args: Any):
        conn = await self._pool.acquire()
        try:
            return await conn.fetchrow(query, *args)
        finally:
            await self._pool.release(conn)

    async def fetch(self, query: str, *args: Any):
        conn = await self._pool.acquire()
        try:
            return await conn.fetch(query, *args)
        finally:
            await self._pool.release(conn)

    async def fetchval(self, query: str, *args: Any):
        conn = await self._pool.acquire()
        try:
            return await conn.fetchval(query, *args)
        finally:
            await self._pool.release(conn)

    async def execute(self, query: str, *args: Any):
        conn = await self._pool.acquire()
        try:
            return await conn.execute(query, *args)
        finally:
            await self._pool.release(conn)
