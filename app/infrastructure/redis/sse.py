from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import redis.asyncio as redis

from .redisutil import ns_key


def _sse_pack(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    return (f"event: {event}\n" f"data: {payload}\n\n").encode('utf-8')


@dataclass
class RedisSubscriber:
    user_id: str
    channel: str
    pubsub: 'redis.client.PubSub'


class RedisEventBroker:
    def __init__(self, *, r: redis.Redis, namespace: str) -> None:
        self.r = r
        self.ns = namespace

    def _chan(self, user_id: str) -> str:
        return ns_key(self.ns, 'events', user_id)

    async def publish(self, user_id: str, event: str, data: Any) -> None:
        msg = json.dumps({'event': event, 'data': data}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        await self.r.publish(self._chan(user_id), msg)

    async def subscribe(self, user_id: str) -> RedisSubscriber:
        channel = self._chan(user_id)
        ps = self.r.pubsub()
        await ps.subscribe(channel)
        return RedisSubscriber(user_id=user_id, channel=channel, pubsub=ps)

    async def unsubscribe(self, sub: RedisSubscriber) -> None:
        try:
            await sub.pubsub.unsubscribe(sub.channel)
        finally:
            await sub.pubsub.close()


async def stream_redis_events(sub: RedisSubscriber) -> AsyncIterator[bytes]:
    # initial hello
    yield _sse_pack('hello', {'user_id': sub.user_id})

    keepalive_sec = 25
    while True:
        msg = await sub.pubsub.get_message(ignore_subscribe_messages=True, timeout=keepalive_sec)
        if msg is None:
            yield b": keep-alive\n\n"
            continue
        if msg.get('type') != 'message':
            continue
        raw = msg.get('data')
        if raw is None:
            continue
        try:
            obj = json.loads(raw)
            yield _sse_pack(obj.get('event', 'message'), obj.get('data', {}))
        except Exception:
            continue
