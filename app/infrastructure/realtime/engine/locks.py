"""Distributed lock manager for saga orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from typing import Any, Dict, Optional


class DistributedLock:
    """Redis-based distributed lock for saga state transitions."""

    def __init__(
        self,
        redis_client: Optional[Any],
        db_connection: Optional[Any] = None,
        lock_timeout: int = 30,
        fail_open: bool = False,
        db_url: Optional[str] = None,
        async_mode: bool = True,
    ):
        self.redis = redis_client
        self.db = db_connection
        self.db_url = db_url
        self.async_mode = async_mode
        self.lock_timeout = lock_timeout
        self.fail_open = fail_open
        self.logger = logging.getLogger(__name__)
        self.db_locks_held = set()
        self._db_lock_conns: Dict[int, Any] = {}
        self._redis_tokens: Dict[str, str] = {}
        self._redis_refresh_tasks: Dict[str, asyncio.Task] = {}

    def _db_is_pool(self) -> bool:
        return bool(self.db) and hasattr(self.db, "acquire") and hasattr(self.db, "release")

    async def _db_try_advisory_lock(self, lock_id: int) -> bool:
        if not self.db:
            return False

        if self._db_is_pool():
            conn = await self.db.acquire()
            try:
                result = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_id)
                if result:
                    self._db_lock_conns[lock_id] = conn
                    return True
                await self.db.release(conn)
                return False
            except Exception:
                await self.db.release(conn)
                raise

        return await self.db.fetchval("SELECT pg_try_advisory_lock($1)", lock_id)

    async def _db_release_advisory_lock(self, lock_id: int) -> bool:
        if not self.db:
            return False

        if self._db_is_pool():
            conn = self._db_lock_conns.pop(lock_id, None)
            if not conn:
                return False
            try:
                await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
                return True
            finally:
                await self.db.release(conn)

        await self.db.execute("SELECT pg_advisory_unlock($1)", lock_id)
        return True

    def _compute_lock_id(self, lock_key: str) -> int:
        """Compute stable 32-bit lock id for advisory locks."""
        digest = hashlib.sha256(lock_key.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], byteorder="big", signed=False)

    async def _refresh_redis_lock(self, lock_key: str, token: str):
        """Refresh Redis lock TTL while held."""
        if not self.redis:
            return

        lua_extend = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('expire', KEYS[1], ARGV[2])
        else
            return 0
        end
        """

        while self._redis_tokens.get(lock_key) == token:
            try:
                await asyncio.sleep(max(1, self.lock_timeout // 2))
                await self.redis.eval(lua_extend, 1, lock_key, token, self.lock_timeout)
            except Exception as e:
                self.logger.warning("Failed to refresh Redis lock %s: %s", lock_key, e)
                return

    async def acquire(self, saga_id: str, operation: str) -> bool:
        """Acquire lock for saga operation."""
        lock_key = f"saga:lock:{saga_id}:{operation}"

        if self.redis:
            try:
                lock_value = str(uuid.uuid4())
                acquired = await self.redis.set(
                    lock_key,
                    lock_value,
                    nx=True,
                    ex=self.lock_timeout,
                )

                if acquired:
                    self._redis_tokens[lock_key] = lock_value
                    refresh_task = asyncio.create_task(self._refresh_redis_lock(lock_key, lock_value))
                    self._redis_refresh_tasks[lock_key] = refresh_task
                    self.logger.debug("Redis lock acquired: %s", lock_key)
                    return True
                self.logger.warning("Lock already held: %s", lock_key)
                return False
            except Exception as e:
                self.logger.warning("Redis lock failed, falling back to DB: %s", e)

        if self.db and self.async_mode:
            lock_id = self._compute_lock_id(lock_key)
            wait_time = 0.0
            backoff = 0.05

            while wait_time < self.lock_timeout:
                try:
                    result = await self._db_try_advisory_lock(lock_id)
                    if result:
                        self.db_locks_held.add(lock_id)
                        self.logger.debug("DB lock acquired: %s (id: %s)", lock_key, lock_id)
                        return True
                except Exception as e:
                    self.logger.error("Failed to acquire DB lock %s: %s", lock_key, e)
                    return False

                await asyncio.sleep(backoff)
                wait_time += backoff
                backoff = min(backoff * 2, 1.0)

            self.logger.warning("DB lock acquisition timeout: %s", lock_key)
            return False

        if self.fail_open:
            self.logger.warning("No locking mechanism available, allowing operation (fail-open mode)")
            return True

        self.logger.warning("No locking mechanism available (Redis and DB unavailable)")
        return False

    async def release(self, saga_id: str, operation: str):
        """Release lock for saga operation."""
        lock_key = f"saga:lock:{saga_id}:{operation}"

        if self.redis:
            try:
                token = self._redis_tokens.get(lock_key)
                if token:
                    lua_release = """
                    if redis.call('get', KEYS[1]) == ARGV[1] then
                        return redis.call('del', KEYS[1])
                    else
                        return 0
                    end
                    """
                    await self.redis.eval(lua_release, 1, lock_key, token)
                refresh_task = self._redis_refresh_tasks.pop(lock_key, None)
                if refresh_task:
                    refresh_task.cancel()
                self._redis_tokens.pop(lock_key, None)
                self.logger.debug("Redis lock released: %s", lock_key)
            except Exception as e:
                self.logger.warning("Failed to release Redis lock %s: %s", lock_key, e)

        if self.db and self.async_mode:
            try:
                lock_id = self._compute_lock_id(lock_key)
                if lock_id in self.db_locks_held:
                    released = await self._db_release_advisory_lock(lock_id)
                    if released:
                        self.db_locks_held.discard(lock_id)
                        self.logger.debug("DB lock released: %s", lock_key)
                    else:
                        self.logger.warning("DB lock release skipped (no connection): %s", lock_key)
            except Exception as e:
                self.logger.warning("Failed to release DB lock %s: %s", lock_key, e)
