from __future__ import annotations

import os
from typing import Optional

import redis.asyncio as redis

from app.core.util import ns_key


class RedisPool:
    def __init__(self, url: str):
        self.url = url
        self._client: Optional[redis.Redis] = None

    def client(self) -> redis.Redis:
        if self._client is None:
            # decode_responses=False -> bytes, more efficient
            self._client = redis.from_url(self.url, decode_responses=False)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
