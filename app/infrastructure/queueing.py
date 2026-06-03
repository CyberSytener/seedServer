from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class QueueItem:
    priority: int
    created_ts: float
    job_id: str


class QueueHub:
    def __init__(self) -> None:
        self.queues: Dict[str, asyncio.PriorityQueue[Tuple[int, float, str]]] = {
            "q_fast": asyncio.PriorityQueue(),
            "q_batch": asyncio.PriorityQueue(),
            "q_low": asyncio.PriorityQueue(),
        }

    async def enqueue(self, queue_name: str, job_id: str, priority: int, created_ts: float | None = None) -> None:
        q = self.queues.get(queue_name)
        if q is None:
            q = self.queues.setdefault(queue_name, asyncio.PriorityQueue())
        ts = created_ts if created_ts is not None else time.time()
        # PriorityQueue sorts ascending; we want higher priority first => negate
        await q.put((-priority, ts, job_id))

    async def get(self, queue_name: str) -> str:
        q = self.queues[queue_name]
        _neg_p, _ts, job_id = await q.get()
        return job_id
