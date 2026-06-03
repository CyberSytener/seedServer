from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple


class InMemoryPipeline:
    def __init__(self, redis_client: "InMemoryAsyncRedis") -> None:
        self._redis = redis_client
        self._ops: List[Tuple[str, tuple, dict]] = []

    def incr(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("incr", args, kwargs))

    def ttl(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("ttl", args, kwargs))

    def hget(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("hget", args, kwargs))

    def hincrby(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("hincrby", args, kwargs))

    def expire(self, *args: Any, **kwargs: Any) -> None:
        self._ops.append(("expire", args, kwargs))

    async def execute(self) -> List[Any]:
        out: List[Any] = []
        for name, args, kwargs in self._ops:
            method = getattr(self._redis, name)
            out.append(await method(*args, **kwargs))
        self._ops.clear()
        return out


class InMemoryPubSub:
    def __init__(self, redis_client: "InMemoryAsyncRedis") -> None:
        self._redis = redis_client
        self._queue: asyncio.Queue = asyncio.Queue()
        self._channels: set[str] = set()

    async def subscribe(self, channel: str) -> None:
        self._channels.add(channel)
        self._redis._register_subscriber(channel, self)

    async def unsubscribe(self, channel: str) -> None:
        self._channels.discard(channel)
        self._redis._unregister_subscriber(channel, self)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        try:
            item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return {"type": "message", "data": item}

    async def close(self) -> None:
        for channel in list(self._channels):
            self._redis._unregister_subscriber(channel, self)
        self._channels.clear()

    async def _push(self, payload: Any) -> None:
        await self._queue.put(payload)


class InMemoryAsyncRedis:
    def __init__(self) -> None:
        self._kv: Dict[str, int] = {}
        self._hash: Dict[str, Dict[str, Any]] = {}
        self._zsets: Dict[str, Dict[bytes, float]] = {}
        self._subscribers: Dict[str, List[InMemoryPubSub]] = {}

    def pipeline(self) -> InMemoryPipeline:
        return InMemoryPipeline(self)

    async def ping(self) -> bool:
        return True

    async def incr(self, key: str) -> int:
        self._kv[key] = int(self._kv.get(key, 0)) + 1
        return self._kv[key]

    async def ttl(self, key: str) -> int:
        return -1

    async def expire(self, key: str, ttl_sec: int) -> bool:
        return True

    async def hget(self, key: str, field: str) -> Any:
        return self._hash.get(key, {}).get(field)

    async def hincrby(self, key: str, field: str, amount: int) -> int:
        bucket = self._hash.setdefault(key, {})
        bucket[field] = int(bucket.get(field, 0)) + int(amount)
        return int(bucket[field])

    async def zadd(self, key: str, mapping: Dict[Any, float]) -> int:
        bucket = self._zsets.setdefault(key, {})
        for member, score in mapping.items():
            normalized = member if isinstance(member, bytes) else str(member).encode("utf-8")
            bucket[normalized] = float(score)
        return len(mapping)

    async def zcard(self, key: str) -> int:
        return len(self._zsets.get(key, {}))

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> List[Any]:
        bucket = self._zsets.get(key, {})
        ordered = sorted(bucket.items(), key=lambda item: (item[1], item[0]))
        if end == -1:
            subset = ordered[start:]
        else:
            subset = ordered[start : end + 1]
        if withscores:
            return [(member, score) for member, score in subset]
        return [member for member, _score in subset]

    async def zrem(self, key: str, member: Any) -> int:
        bucket = self._zsets.get(key, {})
        normalized = member if isinstance(member, bytes) else str(member).encode("utf-8")
        if normalized in bucket:
            del bucket[normalized]
            return 1
        return 0

    async def bzpopmin(self, key: str, timeout: int = 0) -> Optional[Tuple[str, bytes, float]]:
        bucket = self._zsets.get(key, {})
        if not bucket:
            if timeout > 0:
                await asyncio.sleep(min(timeout, 0.01))
            return None
        member, score = min(bucket.items(), key=lambda item: (item[1], item[0]))
        del bucket[member]
        return key, member, score

    async def publish(self, channel: str, payload: Any) -> int:
        subscribers = list(self._subscribers.get(channel, []))
        for subscriber in subscribers:
            await subscriber._push(payload)
        return len(subscribers)

    def pubsub(self) -> InMemoryPubSub:
        return InMemoryPubSub(self)

    def _register_subscriber(self, channel: str, subscriber: InMemoryPubSub) -> None:
        bucket = self._subscribers.setdefault(channel, [])
        if subscriber not in bucket:
            bucket.append(subscriber)

    def _unregister_subscriber(self, channel: str, subscriber: InMemoryPubSub) -> None:
        bucket = self._subscribers.get(channel)
        if not bucket:
            return
        if subscriber in bucket:
            bucket.remove(subscriber)
        if not bucket:
            self._subscribers.pop(channel, None)

    async def close(self) -> None:
        self._kv.clear()
        self._hash.clear()
        self._zsets.clear()
        self._subscribers.clear()
