from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Set


def _sse_pack(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    # SSE format
    return (f"event: {event}\n" f"data: {payload}\n\n").encode("utf-8")


@dataclass
class Subscriber:
    user_id: str
    queue: "asyncio.Queue[bytes]"


class EventBroker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # Each user can have multiple concurrent SSE connections.
        # Maintain a set of per-connection queues to avoid "one consumer steals events".
        self._subs: Dict[str, Set[asyncio.Queue[bytes]]] = {}

    async def subscribe(self, user_id: str) -> Subscriber:
        async with self._lock:
            qs = self._subs.get(user_id)
            if qs is None:
                qs = set()
                self._subs[user_id] = qs
            q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)
            qs.add(q)
            # initial hello
            try:
                q.put_nowait(_sse_pack("hello", {"user_id": user_id}))
            except asyncio.QueueFull:
                pass
            return Subscriber(user_id=user_id, queue=q)

    async def unsubscribe(self, sub: Subscriber) -> None:
        async with self._lock:
            qs = self._subs.get(sub.user_id)
            if not qs:
                return
            qs.discard(sub.queue)
            if not qs:
                self._subs.pop(sub.user_id, None)

    async def publish(self, user_id: str, event: str, data: Any) -> None:
        async with self._lock:
            qs = self._subs.get(user_id)
            # make a shallow copy to avoid holding lock during put_nowait
            targets = list(qs) if qs else []
        if not targets:
            return
        msg = _sse_pack(event, data)
        for q in targets:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # drop oldest-ish by draining a bit
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass


async def stream_events(sub: Subscriber) -> AsyncIterator[bytes]:
    # keepalive every 25s
    keepalive = 25
    while True:
        try:
            msg = await asyncio.wait_for(sub.queue.get(), timeout=keepalive)
            yield msg
        except asyncio.TimeoutError:
            yield b": keep-alive\n\n"
