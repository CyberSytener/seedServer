"""
Cache utilities for saga orchestration.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Optional


class TTLCache:
    """Thread-safe TTL cache with LRU eviction for idempotency tracking."""

    def __init__(self, ttl_seconds: int = 3600, max_size: int = 10000):
        self._lock = asyncio.Lock()
        self.cache = OrderedDict()
        self.timestamps = {}
        self.ttl = ttl_seconds
        self.max_size = max_size

    async def get(self, key: str) -> Optional[Any]:
        """Get value if not expired (async-safe)."""
        async with self._lock:
            if key not in self.cache:
                return None

            if time.time() - self.timestamps[key] >= self.ttl:
                del self.cache[key]
                del self.timestamps[key]
                return None

            self.cache.move_to_end(key)
            return self.cache[key]

    async def set(self, key: str, value: Any):
        """Set value with TTL (async-safe)."""
        async with self._lock:
            if len(self.cache) >= self.max_size and key not in self.cache:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                del self.timestamps[oldest_key]

            self.cache[key] = value
            self.timestamps[key] = time.time()
            self.cache.move_to_end(key)

    def __len__(self) -> int:
        return len(self.cache)
