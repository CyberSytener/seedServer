"""
Rate limiting for API endpoints to prevent abuse.

.. deprecated:: Phase 3
    Use :func:`app.core.rate_limit.check_rate_limits` (async / Redis-backed)
    instead.  This sync SQLite implementation is retained only for backward
    compatibility of existing tests and will be removed in a future release.
"""
import logging
import time
import warnings
from datetime import datetime, timezone
from typing import Dict, Optional
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.core.interfaces.database import DatabaseProtocol


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""
    max_requests: int
    window_seconds: int
    burst_allowance: int = 0


# Default rate limits per endpoint category
DEFAULT_LIMITS = {
    "diagnostic_generation": RateLimitConfig(max_requests=10, window_seconds=60, burst_allowance=2),
    "lesson_generation": RateLimitConfig(max_requests=5, window_seconds=60, burst_allowance=1),
    "standard_api": RateLimitConfig(max_requests=100, window_seconds=60, burst_allowance=10),
    "admin_api": RateLimitConfig(max_requests=1000, window_seconds=60, burst_allowance=50),
}


class RateLimiter:
    """Token bucket rate limiter with database persistence."""
    
    def __init__(self, db: DatabaseProtocol):
        self.db = db
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create rate limit tracking table."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                user_id TEXT NOT NULL,
                endpoint_category TEXT NOT NULL,
                window_start INTEGER NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                last_request_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, endpoint_category, window_start)
            )
        """)
        
        # Create index for efficient cleanup
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_window 
            ON rate_limits(window_start)
        """)
    
    def check_rate_limit(
        self,
        user_id: str,
        endpoint_category: str,
        config: Optional[RateLimitConfig] = None
    ) -> bool:
        """
        Check if request is within rate limit.
        
        Args:
            user_id: User identifier
            endpoint_category: Category of endpoint (diagnostic_generation, etc.)
            config: Optional custom rate limit config
            
        Returns:
            True if allowed, False if rate limited
            
        Raises:
            HTTPException(429) if rate limit exceeded
        """
        if config is None:
            config = DEFAULT_LIMITS.get(endpoint_category, DEFAULT_LIMITS["standard_api"])
        
        now = int(time.time())
        window_start = now - (now % config.window_seconds)
        
        # Get current window stats
        row = self.db.fetchone("""
            SELECT request_count, last_request_at
            FROM rate_limits
            WHERE user_id = ? AND endpoint_category = ? AND window_start = ?
        """, (user_id, endpoint_category, window_start))
        
        if row:
            current_count = row["request_count"]
            last_request = row["last_request_at"]
            
            # Check if limit exceeded
            max_allowed = config.max_requests + config.burst_allowance
            if current_count >= max_allowed:
                # Calculate retry after
                time_in_window = now - window_start
                retry_after = config.window_seconds - time_in_window
                
                logging.warning(
                    "Rate limit exceeded",
                    extra={
                        "user_id": user_id,
                        "endpoint_category": endpoint_category,
                        "current_count": current_count,
                        "max_allowed": max_allowed,
                        "retry_after": retry_after
                    }
                )
                
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)}
                )
            
            # Update count
            self.db.execute("""
                UPDATE rate_limits
                SET request_count = request_count + 1, last_request_at = ?
                WHERE user_id = ? AND endpoint_category = ? AND window_start = ?
            """, (now, user_id, endpoint_category, window_start))
        else:
            # First request in this window
            self.db.execute("""
                INSERT INTO rate_limits (user_id, endpoint_category, window_start, request_count, last_request_at)
                VALUES (?, ?, ?, 1, ?)
            """, (user_id, endpoint_category, window_start, now))
        
        return True
    
    def cleanup_old_windows(self, older_than_seconds: int = 3600):
        """
        Clean up old rate limit windows.
        
        Args:
            older_than_seconds: Delete windows older than this (default: 1 hour)
        """
        cutoff = int(time.time()) - older_than_seconds
        before = self.db.fetchone(
            "SELECT COUNT(*) AS count FROM rate_limits WHERE window_start < ?",
            (cutoff,),
        )
        self.db.execute(
            "DELETE FROM rate_limits WHERE window_start < ?",
            (cutoff,),
        )
        count = before["count"] if before else 0
        if count > 0:
            logging.info("Cleaned up %s old rate limit windows", count)
    
    def get_user_limits(self, user_id: str) -> Dict[str, Dict]:
        """
        Get current rate limit status for a user.
        
        Returns dict with endpoint categories and their current usage.
        """
        now = int(time.time())
        rows = self.db.fetchall("""
            SELECT endpoint_category, request_count, window_start
            FROM rate_limits
            WHERE user_id = ? AND window_start >= ?
            ORDER BY endpoint_category, window_start DESC
        """, (user_id, now - 3600))  # Last hour
        
        result = {}
        for row in rows:
            category = row["endpoint_category"]
            config = DEFAULT_LIMITS.get(category, DEFAULT_LIMITS["standard_api"])
            window_start = row["window_start"]
            
            if category not in result:
                result[category] = {
                    "current_count": row["request_count"],
                    "max_requests": config.max_requests,
                    "window_seconds": config.window_seconds,
                    "window_start": datetime.fromtimestamp(window_start, tz=timezone.utc).isoformat(),
                    "remaining": max(0, config.max_requests - row["request_count"])
                }
        
        return result
    
    def reset_user_limits(self, user_id: str, endpoint_category: Optional[str] = None):
        """
        Reset rate limits for a user (admin function).
        
        Args:
            user_id: User to reset
            endpoint_category: Optional specific category to reset, or None for all
        """
        if endpoint_category:
            self.db.execute("""
                DELETE FROM rate_limits
                WHERE user_id = ? AND endpoint_category = ?
            """, (user_id, endpoint_category))
            logging.info(f"Reset rate limits for user {user_id}, category {endpoint_category}")
        else:
            self.db.execute("""
                DELETE FROM rate_limits WHERE user_id = ?
            """, (user_id,))
            logging.info(f"Reset all rate limits for user {user_id}")


def rate_limit_middleware(
    request: Request,
    user_id: str,
    endpoint_category: str,
    db: DatabaseProtocol,
    config: Optional[RateLimitConfig] = None
):
    """
    Convenience function to check rate limits in endpoints.
    
    Usage:
        rate_limit_middleware(request, ctx.user_id, "diagnostic_generation", db)
    """
    limiter = RateLimiter(db)
    limiter.check_rate_limit(user_id, endpoint_category, config)


