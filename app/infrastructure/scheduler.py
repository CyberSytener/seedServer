from __future__ import annotations

import asyncio
import time

from app.infrastructure.redis.queue import RedisQueueHub


async def scheduler_loop(*, queuehub: RedisQueueHub, poll_idle_sec: float = 0.25) -> None:
    """Move due scheduled jobs into their target queues."""
    while True:
        item = await queuehub.peek_next_schedule()
        if not item:
            await asyncio.sleep(poll_idle_sec)
            continue
        run_at, member = item
        now = time.time()
        if run_at > now:
            # sleep until due but cap so we can react to earlier inserts
            await asyncio.sleep(min(poll_idle_sec, max(0.0, run_at - now)))
            continue
        popped = await queuehub.pop_due_scheduled()
        if not popped:
            await asyncio.sleep(0.01)
            continue
        payload, _run_at = popped
        try:
            await queuehub.enqueue(
                payload.get("queue", "q_batch"),
                payload.get("job_id"),
                priority=int(payload.get("priority", 0)),
                created_ts=float(payload.get("created_ts", now)),
            )
        except Exception:
            # Avoid crashing the scheduler; drop on floor (job still in DB)
            await asyncio.sleep(0.01)
