"""
Redis-backed session store for WebSocket connections.

Stores:
- session_id → user_id, connection metadata
- session_id:pending → queued messages (during reconnect)
- session_id:trace → current trace_id (for request correlation)

Gateway principle: Just store/retrieve, no business logic.
"""

import json
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
import redis
import asyncio


class RedisSessionStore:
    """Manage WebSocket sessions in Redis."""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        session_ttl_seconds: int = 3600,  # 1 hour default
    ):
        """
        Initialize session store.
        
        Args:
            redis_client: Redis connection (async or sync)
            session_ttl_seconds: Session expiration time
        """
        self.redis = redis_client
        self.session_ttl = session_ttl_seconds
    
    async def create_session(
        self,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create new session for user.
        
        Returns:
            session_id (UUID format)
        """
        session_id = str(uuid.uuid4())
        
        session_data = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_activity": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        
        key = f"session:{session_id}"
        await self.redis.setex(
            key,
            self.session_ttl,
            json.dumps(session_data),
        )
        
        return session_id
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data.
        
        Returns:
            Session dict or None if expired/not found
        """
        key = f"session:{session_id}"
        data = await self.redis.get(key)
        
        if not data:
            return None
        
        return json.loads(data)
    
    async def update_activity(self, session_id: str) -> None:
        """Update last_activity timestamp and refresh TTL."""
        key = f"session:{session_id}"
        
        session = await self.get_session(session_id)
        if not session:
            return
        
        session["last_activity"] = datetime.now(timezone.utc).isoformat()
        await self.redis.setex(
            key,
            self.session_ttl,
            json.dumps(session),
        )
    
    async def queue_message(
        self,
        session_id: str,
        message: Dict[str, Any],
    ) -> None:
        """
        Queue message for session (used during reconnect).
        
        Message is stored and delivered when client reconnects.
        """
        queue_key = f"session:{session_id}:pending"
        
        # Store message with expiry
        # Max 100 pending messages per session
        await self.redis.lpush(queue_key, json.dumps(message))
        await self.redis.ltrim(queue_key, 0, 99)  # Keep last 100
        await self.redis.expire(queue_key, self.session_ttl)
    
    async def get_pending_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all pending messages for session (clear queue after).
        
        Returns:
            List of messages in order
        """
        queue_key = f"session:{session_id}:pending"
        
        # Pop all messages (LRANGE + DEL)
        messages_raw = await self.redis.lrange(queue_key, 0, -1)
        
        if messages_raw:
            await self.redis.delete(queue_key)
        
        # Messages are stored newest-first (lpush), reverse for chronological order
        return [json.loads(msg) for msg in reversed(messages_raw)]
    
    async def set_trace_id(self, session_id: str, trace_id: str) -> None:
        """Store current trace_id for request correlation."""
        key = f"session:{session_id}:trace"
        await self.redis.setex(key, 300, trace_id)  # 5 min TTL for trace
    
    async def get_trace_id(self, session_id: str) -> Optional[str]:
        """Retrieve current trace_id."""
        key = f"session:{session_id}:trace"
        trace_id = await self.redis.get(key)
        return trace_id.decode() if trace_id else None
    
    async def invalidate_session(self, session_id: str) -> None:
        """Delete session and all associated data."""
        await self.redis.delete(
            f"session:{session_id}",
            f"session:{session_id}:pending",
            f"session:{session_id}:trace",
        )
    
    async def cleanup_expired(self) -> int:
        """
        Cleanup expired sessions (manual, for operational awareness).
        
        Redis auto-expires via TTL, but this counts cleaned up sessions.
        
        Returns:
            Number of expired sessions cleaned
        """
        # In practice, Redis auto-expires keys
        # This is informational; may be called by monitoring
        return 0


class SimpleRedisSessionStore:
    """Synchronous version for testing (uses redis-py)."""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        session_ttl_seconds: int = 3600,
    ):
        self.redis = redis_client
        self.session_ttl = session_ttl_seconds
    
    def create_session(
        self,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create new session for user."""
        session_id = str(uuid.uuid4())
        
        session_data = {
            "user_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_activity": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        
        key = f"session:{session_id}"
        self.redis.setex(
            key,
            self.session_ttl,
            json.dumps(session_data),
        )
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data."""
        key = f"session:{session_id}"
        data = self.redis.get(key)
        
        if not data:
            return None
        
        return json.loads(data)
    
    def update_activity(self, session_id: str) -> None:
        """Update last_activity timestamp and refresh TTL."""
        key = f"session:{session_id}"
        
        session = self.get_session(session_id)
        if not session:
            return
        
        session["last_activity"] = datetime.now(timezone.utc).isoformat()
        self.redis.setex(
            key,
            self.session_ttl,
            json.dumps(session),
        )
    
    def queue_message(
        self,
        session_id: str,
        message: Dict[str, Any],
    ) -> None:
        """Queue message for session."""
        queue_key = f"session:{session_id}:pending"
        self.redis.lpush(queue_key, json.dumps(message))
        self.redis.ltrim(queue_key, 0, 99)
        self.redis.expire(queue_key, self.session_ttl)
    
    def get_pending_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieve all pending messages for session."""
        queue_key = f"session:{session_id}:pending"
        messages_raw = self.redis.lrange(queue_key, 0, -1)
        
        if messages_raw:
            self.redis.delete(queue_key)
        
        return [json.loads(msg) for msg in reversed(messages_raw)]
    
    def set_trace_id(self, session_id: str, trace_id: str) -> None:
        """Store current trace_id."""
        key = f"session:{session_id}:trace"
        self.redis.setex(key, 300, trace_id)
    
    def get_trace_id(self, session_id: str) -> Optional[str]:
        """Retrieve current trace_id."""
        key = f"session:{session_id}:trace"
        trace_id = self.redis.get(key)
        return trace_id.decode() if trace_id else None
    
    def invalidate_session(self, session_id: str) -> None:
        """Delete session and all associated data."""
        self.redis.delete(
            f"session:{session_id}",
            f"session:{session_id}:pending",
            f"session:{session_id}:trace",
        )
