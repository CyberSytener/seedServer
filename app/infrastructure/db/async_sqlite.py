"""Async wrapper around the synchronous SQLite DB class.

Delegates every blocking call to ``asyncio.get_event_loop().run_in_executor()``
so that ``async def`` handlers never block the event loop on I/O.

Usage:
    from app.infrastructure.db.async_sqlite import AsyncSqliteDB, get_async_db

    adb = get_async_db()            # same singleton; async-safe
    row = await adb.fetchone(...)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Iterable

from .sqlite import DB, get_db


class AsyncSqliteDB:
    """Thin async facade over :class:`DB` using ``run_in_executor``."""

    def __init__(self, db: DB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Async wrappers
    # ------------------------------------------------------------------

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._db.execute, sql, params)

    async def executemany(self, sql: str, seq: Iterable[tuple[Any, ...]]) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._db.executemany, sql, seq)

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Any | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._db.fetchone, sql, params)

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._db.fetchall, sql, params)

    @asynccontextmanager
    async def transaction(self):
        """Yield the underlying connection inside a sync transaction on the executor."""
        loop = asyncio.get_running_loop()

        def _begin():
            self._db._lock.acquire()
            self._db._conn.execute("BEGIN")

        def _commit():
            self._db._conn.commit()
            self._db._lock.release()

        def _rollback():
            self._db._conn.rollback()
            self._db._lock.release()

        await loop.run_in_executor(None, _begin)
        try:
            yield self._db._conn
            await loop.run_in_executor(None, _commit)
        except Exception:
            await loop.run_in_executor(None, _rollback)
            raise

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._db.close)

    # Expose the underlying sync DB for startup / migration code that
    # runs outside the event loop.
    @property
    def sync(self) -> DB:
        return self._db


# -----------------------------------------------------------------------
# Singleton
# -----------------------------------------------------------------------

_ASYNC_SINGLETON: AsyncSqliteDB | None = None


def get_async_db() -> AsyncSqliteDB:
    """Return a process-wide ``AsyncSqliteDB`` wrapping the sync singleton."""
    global _ASYNC_SINGLETON
    if _ASYNC_SINGLETON is None:
        _ASYNC_SINGLETON = AsyncSqliteDB(get_db())
    return _ASYNC_SINGLETON
