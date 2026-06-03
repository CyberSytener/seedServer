"""
Idempotency Manager - Prevents duplicate action execution

Ensures that even if the same action is received multiple times,
it only executes once and returns consistent results.

Key Principle:
  action_id is the idempotency key
  execute once → cache result → return cached result on retry
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
import threading

from app.core.metrics import IDEMPOTENCY_HITS, IDEMPOTENCY_MISSES


@dataclass
class ExecutionRecord:
    """Record of a previous execution"""
    action_id: str
    executed_at: datetime
    result: Dict[str, Any]
    error: Optional[str] = None
    
    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """Check if record is too old (default 1 hour)"""
        age = (datetime.now(timezone.utc) - self.executed_at).total_seconds()
        return age > ttl_seconds


class IdempotencyManager:
    """
    Prevents duplicate executions by tracking action_id.
    
    Usage:
        manager = IdempotencyManager()
        
        # First call: executes
        result = manager.get_or_execute("act_123", lambda: expensive_operation())
        
        # Retry with same ID: returns cached result
        result = manager.get_or_execute("act_123", lambda: expensive_operation())
        
        # Both return same result without re-executing
    """
    
    def __init__(self, ttl_seconds: int = 3600):
        """
        Args:
            ttl_seconds: Time-to-live for execution records (default 1 hour)
        """
        self._cache: Dict[str, ExecutionRecord] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
    
    def get_or_execute(
        self, 
        action_id: str, 
        execute_fn,
        force_reexecute: bool = False
    ) -> Dict[str, Any]:
        """
        Execute function once per action_id.
        
        On retry with same action_id, return cached result.
        
        Args:
            action_id: Unique action identifier
            execute_fn: Callable that performs the action (should return dict)
            force_reexecute: If True, ignore cache and re-execute
            
        Returns:
            Result dict with status, data, and execution info
            
        Raises:
            Exception: Propagated from execute_fn
        """
        with self._lock:
            # Clean expired records
            self._cleanup_expired()
            
            # Check cache
            if not force_reexecute and action_id in self._cache:
                record = self._cache[action_id]
                if not record.is_expired(self._ttl_seconds):
                    IDEMPOTENCY_HITS.labels(store="memory").inc()
                    return {
                        "status": "cached",
                        "data": record.result,
                        "cached_at": record.executed_at.isoformat(),
                        "original_execution_at": record.executed_at.isoformat(),
                    }
            
            # Execute
            try:
                IDEMPOTENCY_MISSES.labels(store="memory").inc()
                result = execute_fn()
                
                # Cache result
                record = ExecutionRecord(
                    action_id=action_id,
                    executed_at=datetime.now(timezone.utc),
                    result=result if isinstance(result, dict) else {"result": result}
                )
                self._cache[action_id] = record
                
                return {
                    "status": "executed",
                    "data": record.result,
                    "executed_at": record.executed_at.isoformat(),
                }
            
            except Exception as e:
                # Cache error too (don't retry errors immediately)
                record = ExecutionRecord(
                    action_id=action_id,
                    executed_at=datetime.now(timezone.utc),
                    result={},
                    error=str(e)
                )
                self._cache[action_id] = record
                raise
    
    def get_cached(self, action_id: str) -> Optional[ExecutionRecord]:
        """Get cached record if exists and not expired"""
        with self._lock:
            self._cleanup_expired()
            record = self._cache.get(action_id)
            if record and not record.is_expired(self._ttl_seconds):
                return record
            return None
    
    def invalidate(self, action_id: str) -> bool:
        """
        Clear cache for specific action.
        Use carefully - only for correcting mistakes.
        """
        with self._lock:
            if action_id in self._cache:
                del self._cache[action_id]
                return True
            return False
    
    def clear_all(self) -> int:
        """Clear entire cache. Returns count of cleared records."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count
    
    def _cleanup_expired(self) -> int:
        """Remove expired records. Returns count removed."""
        expired = [
            aid for aid, record in self._cache.items()
            if record.is_expired(self._ttl_seconds)
        ]
        for aid in expired:
            del self._cache[aid]
        return len(expired)
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            self._cleanup_expired()
            return {
                "cached_actions": len(self._cache),
                "ttl_seconds": self._ttl_seconds,
                "cache_keys": list(self._cache.keys()),
            }
