"""
Rate Limiting for Saga Orchestrator.

Protects against DDoS and resource exhaustion using sliding window algorithm.
"""

import time
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


# =========================================================================
# Rate Limiting Policies
# =========================================================================

@dataclass
class RateLimitPolicy:
    """Rate limiting configuration."""
    
    # Request window (seconds)
    window_size_seconds: int = 60
    
    # Max requests in window
    max_requests: int = 1000
    
    # Per-user/client limit (additional)
    per_client_limit: int = 100
    
    # Burst allowance (for traffic spikes)
    burst_multiplier: float = 1.5  # Allow 1.5x for short bursts
    
    # Cleanup old entries (seconds)
    cleanup_interval: int = 300


class RateLimiter:
    """
    Sliding window rate limiter with per-client tracking.
    
    Uses in-memory storage suitable for single instance.
    For distributed systems, use Redis-backed limiter.
    """
    
    def __init__(self, policy: RateLimitPolicy = RateLimitPolicy()):
        self.policy = policy
        
        # Global request window (sliding window)
        self.global_requests: deque = deque()
        
        # Per-client windows
        self.client_requests: Dict[str, deque] = {}
        self.client_last_cleanup: Dict[str, float] = {}
        
        # Stats
        self.total_rejections = 0
        self.rejected_by_global = 0
        self.rejected_by_client = 0
        
        logger.info(f"🚦 Rate limiter initialized")
        logger.info(f"   Global: {policy.max_requests} requests/{policy.window_size_seconds}s")
        logger.info(f"   Per-client: {policy.per_client_limit} requests/{policy.window_size_seconds}s")
    
    # =====================================================================
    # Main Rate Limiting
    # =====================================================================
    
    def check_rate_limit(self, client_id: str, flow_name: str = "default") -> Tuple[bool, Optional[str]]:
        """
        Check if request should be allowed.
        
        Args:
            client_id: Unique client/user identifier
            flow_name: Name of the saga flow being requested
        
        Returns:
            (allowed: bool, reason: str or None)
        """
        current_time = time.time()
        
        # Check global limit
        self._cleanup_global_window(current_time)
        if len(self.global_requests) >= self.policy.max_requests:
            self.total_rejections += 1
            self.rejected_by_global += 1
            reason = f"Global rate limit exceeded ({self.policy.max_requests}/{self.policy.window_size_seconds}s)"
            logger.warning(f"⚠️  {reason} (client: {client_id})")
            return False, reason
        
        # Check per-client limit
        self._cleanup_client_window(client_id, current_time)
        client_window = self.client_requests.get(client_id, deque())
        
        if len(client_window) >= self.policy.per_client_limit:
            self.total_rejections += 1
            self.rejected_by_client += 1
            reason = f"Client rate limit exceeded ({self.policy.per_client_limit}/{self.policy.window_size_seconds}s)"
            logger.warning(f"⚠️  {reason} (client: {client_id})")
            return False, reason
        
        # Check burst allowance
        burst_limit = int(self.policy.per_client_limit * self.policy.burst_multiplier)
        if len(client_window) >= burst_limit:
            logger.info(f"📊 Burst allowance triggered for {client_id} ({len(client_window)}/{burst_limit})")
        
        # Allow the request
        self.global_requests.append(current_time)
        
        if client_id not in self.client_requests:
            self.client_requests[client_id] = deque()
        
        self.client_requests[client_id].append(current_time)
        
        return True, None
    
    # =====================================================================
    # Window Cleanup
    # =====================================================================
    
    def _cleanup_global_window(self, current_time: float):
        """Remove expired entries from global window."""
        window_start = current_time - self.policy.window_size_seconds
        
        while self.global_requests and self.global_requests[0] < window_start:
            self.global_requests.popleft()
    
    def _cleanup_client_window(self, client_id: str, current_time: float):
        """Remove expired entries from client window."""
        window_start = current_time - self.policy.window_size_seconds
        
        if client_id not in self.client_requests:
            return
        
        window = self.client_requests[client_id]
        
        while window and window[0] < window_start:
            window.popleft()
        
        # Remove client if window is empty and cleanup interval passed
        if not window:
            last_cleanup = self.client_last_cleanup.get(client_id, 0)
            if current_time - last_cleanup > self.policy.cleanup_interval:
                del self.client_requests[client_id]
                del self.client_last_cleanup[client_id]
    
    # =====================================================================
    # Statistics
    # =====================================================================
    
    def get_stats(self) -> Dict:
        """Get rate limiter statistics."""
        current_time = time.time()
        
        self._cleanup_global_window(current_time)
        
        return {
            "global_requests_in_window": len(self.global_requests),
            "global_limit": self.policy.max_requests,
            "global_utilization_percent": (len(self.global_requests) / self.policy.max_requests * 100),
            "tracked_clients": len(self.client_requests),
            "total_rejections": self.total_rejections,
            "rejected_by_global": self.rejected_by_global,
            "rejected_by_client": self.rejected_by_client,
        }
    
    def get_client_stats(self, client_id: str) -> Dict:
        """Get statistics for specific client."""
        current_time = time.time()
        self._cleanup_client_window(client_id, current_time)
        
        window = self.client_requests.get(client_id, deque())
        
        return {
            "client_id": client_id,
            "requests_in_window": len(window),
            "client_limit": self.policy.per_client_limit,
            "utilization_percent": (len(window) / self.policy.per_client_limit * 100),
        }
    
    def get_top_clients(self, limit: int = 10) -> list:
        """Get top clients by request count."""
        current_time = time.time()
        
        clients = []
        for client_id, window in self.client_requests.items():
            self._cleanup_client_window(client_id, current_time)
            clients.append({
                "client_id": client_id,
                "requests": len(window),
            })
        
        # Sort by request count descending
        clients_sorted = sorted(clients, key=lambda x: x["requests"], reverse=True)
        return clients_sorted[:limit]


# =========================================================================
# Redis-Backed Rate Limiter (for distributed deployments)
# =========================================================================

class RedisRateLimiter:
    """Redis-backed rate limiter for distributed systems."""
    
    def __init__(self, redis_client, policy: RateLimitPolicy = RateLimitPolicy()):
        """
        Initialize Redis rate limiter.
        
        Args:
            redis_client: Redis async client
            policy: Rate limiting policy
        """
        self.redis = redis_client
        self.policy = policy
        self.total_rejections = 0
        
        logger.info(f"🚦 Redis rate limiter initialized")
        logger.info(f"   Global: {policy.max_requests} requests/{policy.window_size_seconds}s")
        logger.info(f"   Per-client: {policy.per_client_limit} requests/{policy.window_size_seconds}s")
    
    async def check_rate_limit_async(self, client_id: str) -> Tuple[bool, Optional[str]]:
        """
        Check rate limit asynchronously using Redis.
        
        Args:
            client_id: Client identifier
        
        Returns:
            (allowed: bool, reason: str or None)
        """
        try:
            current_time = int(time.time())
            
            # Global limit check
            global_key = "ratelimit:global"
            global_count = await self.redis.incr(global_key)
            
            if global_count == 1:
                # First request in new window, set expiration
                await self.redis.expire(global_key, self.policy.window_size_seconds)
            
            if global_count > self.policy.max_requests:
                self.total_rejections += 1
                reason = f"Global rate limit exceeded"
                return False, reason
            
            # Per-client limit check
            client_key = f"ratelimit:client:{client_id}"
            client_count = await self.redis.incr(client_key)
            
            if client_count == 1:
                await self.redis.expire(client_key, self.policy.window_size_seconds)
            
            if client_count > self.policy.per_client_limit:
                self.total_rejections += 1
                reason = f"Client rate limit exceeded"
                return False, reason
            
            return True, None
        
        except Exception as e:
            logger.error(f"⚠️  Redis rate limit check failed: {e}")
            # Fail-open: allow request if Redis is down
            logger.warning(f"   Falling back to allow (fail-open mode)")
            return True, None
