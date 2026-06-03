"""
Redis-backed pending action store for confirmation tray.

Stores pending confirmations so clients can list them later.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class RedisPendingActionStore:
    """Persist pending actions in Redis for later retrieval."""

    def __init__(self, redis_client, namespace: str = "pending_actions"):
        self.redis = redis_client
        self.namespace = namespace

    def _action_key(self, action_id: str) -> str:
        return f"{self.namespace}:action:{action_id}"

    def _user_key(self, user_id: str) -> str:
        return f"{self.namespace}:user:{user_id}"

    async def store_pending(
        self,
        action_id: str,
        user_id: str,
        session_id: str,
        action_name: str,
        params: Dict[str, Any],
        human_readable: str,
        expires_at: datetime,
    ) -> None:
        payload = {
            "action_id": action_id,
            "user_id": user_id,
            "session_id": session_id,
            "action_name": action_name,
            "params": params,
            "human_readable": human_readable,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        key = self._action_key(action_id)
        ttl_seconds = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        await self.redis.set(key, json.dumps(payload), ex=ttl_seconds)
        await self.redis.zadd(self._user_key(user_id), {action_id: expires_at.timestamp()})

    async def mark_status(
        self,
        action_id: str,
        user_id: str,
        status: str,
        reason: Optional[str] = None,
    ) -> None:
        key = self._action_key(action_id)
        raw = await self.redis.get(key)
        if raw:
            data = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
        else:
            data = {
                "action_id": action_id,
                "user_id": user_id,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        data["status"] = status
        if reason:
            data["reason"] = reason
        await self.redis.set(key, json.dumps(data))
        if status not in ("pending", "pending_user"):
            await self.redis.zrem(self._user_key(user_id), action_id)

    async def get_pending(self, action_id: str) -> Optional[Dict[str, Any]]:
        key = self._action_key(action_id)
        raw = await self.redis.get(key)
        if not raw:
            return None
        return json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)

    async def list_pending_for_user(self, user_id: str, limit: int = 50) -> list[Dict[str, Any]]:
        ids = await self.redis.zrevrange(self._user_key(user_id), 0, limit - 1)
        results = []
        for action_id in ids:
            key = self._action_key(action_id.decode() if isinstance(action_id, (bytes, bytearray)) else action_id)
            raw = await self.redis.get(key)
            if raw:
                results.append(json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw))
        return results
