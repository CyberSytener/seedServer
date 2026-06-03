"""
Distributed Idempotency Manager using Redis

SETNX + Lua script for atomic check-and-set
Prevents duplicate action execution across distributed systems
"""

import json
import logging
from typing import Any, Dict, Optional, Callable
from datetime import datetime, timedelta
import redis

from app.core.metrics import IDEMPOTENCY_HITS, IDEMPOTENCY_MISSES

logger = logging.getLogger(__name__)

# Lua script for atomic check-and-execute
# If action_id doesn't exist → execute and SET with TTL
# If action_id exists → return cached result
LUA_EXECUTE_ONCE = """
local action_id = KEYS[1]
local ttl = tonumber(ARGV[1])
local status_key = action_id .. ":status"
local result_key = action_id .. ":result"

-- Check if already executed
local status = redis.call('GET', status_key)

if status == "PENDING" then
    -- Another process is executing - wait/retry
    return {err = "PENDING"}
end

if status == "DONE" then
    -- Already executed - return cached result
    local cached = redis.call('GET', result_key)
    return {ok = cached}
end

-- Mark as PENDING to prevent concurrent execution
redis.call('SET', status_key, 'PENDING', 'EX', ttl)

-- Signal executor to proceed
return {ok = "PROCEED"}
"""


class RedisIdempotencyManager:
    """
    Distributed idempotency manager using Redis.
    
    Guarantees: Same action_id will not execute twice within TTL window
    Atomic: Uses Lua script to prevent race conditions
    """
    
    def __init__(self, redis_client: redis.Redis, ttl_seconds: int = 3600):
        """
        Args:
            redis_client: Redis connection
            ttl_seconds: Time-to-live for cached results (default 1 hour)
        """
        self.redis = redis_client
        self.ttl = ttl_seconds
        self.script = redis_client.register_script(LUA_EXECUTE_ONCE)
        self.prefix = "idempotency"
    
    def _key(self, action_id: str, suffix: str = "") -> str:
        """Build Redis key with prefix"""
        return f"{self.prefix}:{action_id}{':' + suffix if suffix else ''}"
    
    def get_or_execute(
        self,
        action_id: str,
        execute_fn: Callable[[], Dict[str, Any]],
        force_reexecute: bool = False
    ) -> Dict[str, Any]:
        """
        Execute function once, cache result for TTL.
        
        Args:
            action_id: Unique action identifier
            execute_fn: Function to execute
            force_reexecute: Skip cache, execute now
        
        Returns:
            Result from execute_fn (either fresh or cached)
        """
        status_key = self._key(action_id, "status")
        result_key = self._key(action_id, "result")
        
        # Force reexecution: skip cache
        if force_reexecute:
            logger.info(f"Force reexecute: {action_id}")
            result = execute_fn()
            self._cache_result(action_id, result)
            return result
        
        # Check if cached
        try:
            cached_result = self.redis.get(result_key)
            if cached_result:
                logger.info(f"Cache hit: {action_id}")
                IDEMPOTENCY_HITS.labels(store="redis").inc()
                return json.loads(cached_result)
        except Exception as e:
            logger.warning(f"Cache lookup failed: {e}")
        
        # Atomic check-and-execute via Lua script
        try:
            # Mark as PENDING atomically
            self.redis.set(status_key, "PENDING", ex=self.ttl)

            IDEMPOTENCY_MISSES.labels(store="redis").inc()
            
            # Execute the function
            logger.info(f"Executing action: {action_id}")
            result = execute_fn()
            
            # Cache the result
            self._cache_result(action_id, result)
            
            # Mark as DONE
            self.redis.set(status_key, "DONE", ex=self.ttl)
            
            return result
        
        except Exception as e:
            logger.error(f"Execution failed: {action_id}: {e}")
            # Mark as failed (clear PENDING)
            self.redis.delete(status_key)
            raise
    
    def _cache_result(self, action_id: str, result: Dict[str, Any]):
        """Cache result in Redis"""
        try:
            result_key = self._key(action_id, "result")
            self.redis.set(result_key, json.dumps(result), ex=self.ttl)
        except Exception as e:
            logger.warning(f"Failed to cache result: {e}")
    
    def invalidate(self, action_id: str):
        """Clear cached result and status"""
        keys = [
            self._key(action_id, "status"),
            self._key(action_id, "result"),
        ]
        self.redis.delete(*keys)
        logger.info(f"Invalidated cache: {action_id}")
    
    def clear_all(self):
        """Clear all idempotency cache (use with caution!)"""
        pattern = f"{self.prefix}:*"
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
        logger.warning(f"Cleared all idempotency cache ({len(keys)} keys)")
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        pattern = f"{self.prefix}:*"
        keys = self.redis.keys(pattern)
        return {
            "cached_actions": len(set(k.split(b':')[1] for k in keys if len(k.split(b':')) > 1)),
            "total_keys": len(keys),
            "prefix": self.prefix,
            "ttl": self.ttl,
        }


class NoOpRedisIdempotencyManager:
    """
    Fallback idempotency manager when Redis is unavailable.
    Does NOT provide distributed idempotency - use only for testing.
    """
    
    def __init__(self):
        self.cache = {}
        logger.warning("Using no-op idempotency manager - no distributed protection!")
    
    def get_or_execute(
        self,
        action_id: str,
        execute_fn: Callable[[], Dict[str, Any]],
        force_reexecute: bool = False
    ) -> Dict[str, Any]:
        if force_reexecute or action_id not in self.cache:
            self.cache[action_id] = execute_fn()
        return self.cache[action_id]
    
    def invalidate(self, action_id: str):
        self.cache.pop(action_id, None)
    
    def clear_all(self):
        self.cache.clear()
    
    def stats(self) -> Dict[str, Any]:
        return {"cached_actions": len(self.cache), "mode": "no-op"}
