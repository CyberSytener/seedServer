from __future__ import annotations
import logging

import json
from typing import Any, Optional

import redis

from app.settings import get_settings
from .util import ns_key, RedisPool


class RedisUtil:
    """Small sync helper for simple JSON payload storage."""

    def __init__(self, url: Optional[str] = None):
        settings = get_settings()
        redis_url = url or settings.redis_url
        self._client = redis.from_url(redis_url, decode_responses=False)

    def set_dict(self, key: str, value: dict[str, Any], *, ttl_seconds: Optional[int] = None) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if ttl_seconds is not None:
            self._client.setex(key, int(ttl_seconds), payload)
            return
        self._client.set(key, payload)

    def get_dict(self, key: str) -> Optional[dict[str, Any]]:
        raw = self._client.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)