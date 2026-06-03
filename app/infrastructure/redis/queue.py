from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import redis.asyncio as redis

from .redisutil import ns_key


@dataclass(frozen=True)
class DequeuedJob:
    job_id: str
    score: float


class RedisQueueHub:
    """Distributed priority queues + scheduler using Redis.

    Queues are implemented as sorted sets. Workers use BZPOPMIN to block.

    Highest priority should be popped first. We convert priority to score so that
    higher priority => smaller score.

    Scheduled jobs are stored in a separate sorted set with score=unix_ts.
    A scheduler process moves due jobs into their target queues.
    """

    def __init__(self, *, r: redis.Redis, namespace: str) -> None:
        self.r = r
        self.ns = namespace

    def _qkey(self, queue_name: str) -> str:
        return ns_key(self.ns, "q", queue_name)

    def _sched_key(self) -> str:
        return ns_key(self.ns, "scheduled")

    @staticmethod
    def _score(priority: int, created_ts: float) -> float:
        # smaller score pops first. Use a large bucket for priority.
        # Higher priority => more negative.
        return float(-priority * 1_000_000_000 + created_ts)

    async def enqueue(
        self,
        queue_name: str,
        job_id: str,
        *,
        priority: int = 0,
        created_ts: Optional[float] = None,
    ) -> None:
        ts = created_ts if created_ts is not None else time.time()
        score = self._score(priority, ts)
        await self.r.zadd(self._qkey(queue_name), {job_id.encode("utf-8"): score})

    async def schedule(
        self,
        *,
        queue_name: str,
        job_id: str,
        run_at_ts: float,
        priority: int = 0,
        created_ts: Optional[float] = None,
    ) -> None:
        ts = created_ts if created_ts is not None else time.time()
        payload = {
            "queue": queue_name,
            "job_id": job_id,
            "priority": int(priority),
            "created_ts": float(ts),
        }
        val = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        await self.r.zadd(self._sched_key(), {val: float(run_at_ts)})

    async def dequeue(self, queue_name: str, *, timeout_sec: int = 10) -> Optional[DequeuedJob]:
        # BZPOPMIN returns (key, member, score)
        res = await self.r.bzpopmin(self._qkey(queue_name), timeout=timeout_sec)
        if not res:
            return None
        _key, member, score = res
        try:
            job_id = member.decode("utf-8")
        except Exception:
            job_id = str(member)
        return DequeuedJob(job_id=job_id, score=float(score))

    async def queue_depth(self, queue_name: str) -> int:
        return int(await self.r.zcard(self._qkey(queue_name)))

    async def scheduled_depth(self) -> int:
        return int(await self.r.zcard(self._sched_key()))

    async def peek_next_schedule(self) -> Optional[Tuple[float, bytes]]:
        # returns (run_at_ts, payload_bytes)
        items = await self.r.zrange(self._sched_key(), 0, 0, withscores=True)
        if not items:
            return None
        member, score = items[0]
        return float(score), member

    async def pop_due_scheduled(self) -> Optional[Tuple[dict, float]]:
        # Atomically pop the earliest scheduled item if due.
        # Not blocking; scheduler loop handles sleep.
        now = time.time()
        # get earliest
        item = await self.peek_next_schedule()
        if not item:
            return None
        run_at, member = item
        if run_at > now:
            return None
        # remove specific member
        removed = await self.r.zrem(self._sched_key(), member)
        if not removed:
            return None
        try:
            payload = json.loads(member.decode("utf-8"))
        except Exception:
            return None
        return payload, run_at
