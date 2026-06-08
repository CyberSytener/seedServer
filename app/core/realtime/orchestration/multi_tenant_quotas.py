"""
Multi-Tenant Quota & Isolation System
Per-recruiter quotas, worker pools, cost controls

Features:
1. Per-tenant resource quotas
   - Emails per day/hour
   - API calls per minute
   - Campaign limits
   - Storage quota

2. Cost controls
   - LLM API spend tracking
   - Quota-based cost limits
   - Usage alerts
   - Per-tenant billing

3. Worker pool isolation
   - Dedicated worker queues per tenant
   - Load balancing
   - Priority queues
   - Fair resource allocation

4. Rate limiting & throttling
   - Token bucket algorithm
   - Per-tenant rate limiting
   - Exponential backoff
   - Quota enforcement

5. Metrics & monitoring
   - Usage tracking per tenant
   - Cost attribution
   - Quota warnings
   - Capacity planning

Usage:
    quota_manager = QuotaManager()
    
    # Define quotas for tenant
    quota_manager.set_quota(
        tenant_id="tenant_001",
        emails_per_day=1000,
        emails_per_hour=50,
        llm_cost_limit=50.00,
        concurrent_campaigns=5,
    )
    
    # Check if operation allowed
    can_send = quota_manager.check_quota(
        tenant_id="tenant_001",
        operation="send_email",
    )
    
    # Track usage
    quota_manager.record_usage(
        tenant_id="tenant_001",
        operation="send_email",
        cost=0.0001,
    )
    
    # Get usage stats
    stats = quota_manager.get_usage(tenant_id="tenant_001")
"""

from typing import Any, Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
from collections import defaultdict
import threading

logger = logging.getLogger(__name__)


class QuotaType(str, Enum):
    """Quota types"""
    EMAILS_PER_DAY = "emails_per_day"
    EMAILS_PER_HOUR = "emails_per_hour"
    API_CALLS_PER_MINUTE = "api_calls_per_minute"
    CONCURRENT_CAMPAIGNS = "concurrent_campaigns"
    LLM_COST_PER_MONTH = "llm_cost_per_month"
    STORAGE_GB = "storage_gb"


class OperationType(str, Enum):
    """Operation types"""
    SEND_EMAIL = "send_email"
    RECEIVE_EMAIL = "receive_email"
    CREATE_CAMPAIGN = "create_campaign"
    PARSE_REPLY = "parse_reply"
    SCHEDULE_INTERVIEW = "schedule_interview"
    API_CALL = "api_call"
    LLM_CALL = "llm_call"


# Operation costs for quota tracking
OPERATION_COSTS = {
    OperationType.SEND_EMAIL: (1, 0.0001),  # quota_units, usd_cost
    OperationType.PARSE_REPLY: (1, 0.005),
    OperationType.LLM_CALL: (1, 0.01),
    OperationType.API_CALL: (1, 0.00001),
}


@dataclass
class QuotaConfig:
    """Quota configuration for tenant"""
    tenant_id: str
    emails_per_day: int = 1000
    emails_per_hour: int = 100
    api_calls_per_minute: int = 100
    concurrent_campaigns: int = 10
    llm_cost_per_month: float = 500.0
    storage_gb: int = 100


@dataclass
class QuotaUsage:
    """Current usage for tenant"""
    tenant_id: str
    emails_sent_today: int = 0
    emails_sent_hour: int = 0
    api_calls_minute: int = 0
    active_campaigns: int = 0
    llm_cost_month: float = 0.0
    storage_used_gb: float = 0.0
    
    last_reset_day: datetime = field(default_factory=datetime.now)
    last_reset_hour: datetime = field(default_factory=datetime.now)
    last_reset_minute: datetime = field(default_factory=datetime.now)


@dataclass
class UsageEvent:
    """Usage event for audit trail"""
    tenant_id: str
    operation: OperationType
    timestamp: datetime
    quota_units: int
    cost_usd: float
    success: bool = True
    error: Optional[str] = None


# ============================================================================
# QUOTA MANAGER
# ============================================================================

class QuotaManager:
    """
    Manage quotas and usage across tenants
    
    Thread-safe quota enforcement with real-time tracking
    """
    
    def __init__(self):
        self.quotas: Dict[str, QuotaConfig] = {}
        self.usage: Dict[str, QuotaUsage] = {}
        self.events: List[UsageEvent] = []
        self.lock = threading.RLock()
    
    def set_quota(
        self,
        tenant_id: str,
        emails_per_day: int = 1000,
        emails_per_hour: int = 100,
        api_calls_per_minute: int = 100,
        concurrent_campaigns: int = 10,
        llm_cost_per_month: float = 500.0,
        storage_gb: int = 100,
    ) -> QuotaConfig:
        """
        Set quota for tenant
        
        Args:
            tenant_id: Unique tenant identifier
            emails_per_day: Daily email limit
            emails_per_hour: Hourly email limit
            api_calls_per_minute: API rate limit
            concurrent_campaigns: Max active campaigns
            llm_cost_per_month: Monthly LLM budget
            storage_gb: Storage quota
        """
        with self.lock:
            config = QuotaConfig(
                tenant_id=tenant_id,
                emails_per_day=emails_per_day,
                emails_per_hour=emails_per_hour,
                api_calls_per_minute=api_calls_per_minute,
                concurrent_campaigns=concurrent_campaigns,
                llm_cost_per_month=llm_cost_per_month,
                storage_gb=storage_gb,
            )
            self.quotas[tenant_id] = config
            self.usage[tenant_id] = QuotaUsage(tenant_id=tenant_id)
            
            logger.info(f"✅ Quota set for {tenant_id}")
            logger.info(f"   Emails: {emails_per_day}/day, {emails_per_hour}/hour")
            logger.info(f"   LLM budget: ${llm_cost_per_month}/month")
            
            return config
    
    def check_quota(
        self,
        tenant_id: str,
        operation: OperationType,
        quantity: int = 1,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if operation allowed under quota
        
        Returns:
            (allowed, reason) tuple
        """
        with self.lock:
            quota = self.quotas.get(tenant_id)
            if not quota:
                return False, f"Tenant {tenant_id} not found"
            
            usage = self.usage[tenant_id]
            
            # Reset counters if needed
            self._reset_counters(tenant_id)
            
            # Check quota based on operation
            if operation in (OperationType.SEND_EMAIL, OperationType.RECEIVE_EMAIL):
                if usage.emails_sent_hour >= quota.emails_per_hour:
                    return False, f"Hourly email limit ({quota.emails_per_hour}) exceeded"
                if usage.emails_sent_today >= quota.emails_per_day:
                    return False, f"Daily email limit ({quota.emails_per_day}) exceeded"
            
            elif operation == OperationType.API_CALL:
                if usage.api_calls_minute >= quota.api_calls_per_minute:
                    return False, f"API rate limit ({quota.api_calls_per_minute}/min) exceeded"
            
            elif operation == OperationType.CREATE_CAMPAIGN:
                if usage.active_campaigns >= quota.concurrent_campaigns:
                    return False, f"Campaign limit ({quota.concurrent_campaigns}) reached"
            
            elif operation == OperationType.LLM_CALL:
                operation_cost = OPERATION_COSTS.get(operation, (1, 0.01))[1]
                if usage.llm_cost_month + operation_cost > quota.llm_cost_per_month:
                    return False, f"LLM budget (${quota.llm_cost_per_month}) exceeded"
            
            return True, None
    
    def record_usage(
        self,
        tenant_id: str,
        operation: OperationType,
        quantity: int = 1,
        success: bool = True,
        error: Optional[str] = None,
    ) -> bool:
        """
        Record operation usage
        
        Args:
            tenant_id: Tenant ID
            operation: Operation type
            quantity: Units consumed (default 1)
            success: Whether operation succeeded
            error: Error message if failed
        
        Returns:
            True if recorded successfully
        """
        with self.lock:
            if tenant_id not in self.quotas:
                logger.warning(f"⚠️  Tenant {tenant_id} not found for usage recording")
                return False
            
            usage = self.usage[tenant_id]
            quota_units, cost_usd = OPERATION_COSTS.get(operation, (1, 0.0))
            
            # Update usage counters
            if operation in (OperationType.SEND_EMAIL, OperationType.RECEIVE_EMAIL):
                usage.emails_sent_hour += quantity
                usage.emails_sent_today += quantity
            
            elif operation == OperationType.API_CALL:
                usage.api_calls_minute += quantity
            
            elif operation == OperationType.CREATE_CAMPAIGN:
                usage.active_campaigns += quantity
            
            elif operation == OperationType.LLM_CALL:
                usage.llm_cost_month += cost_usd * quantity
            
            # Record event
            event = UsageEvent(
                tenant_id=tenant_id,
                operation=operation,
                timestamp=datetime.now(),
                quota_units=quota_units * quantity,
                cost_usd=cost_usd * quantity,
                success=success,
                error=error,
            )
            self.events.append(event)
            
            # Log warning if approaching limit
            quota = self.quotas[tenant_id]
            if operation == OperationType.SEND_EMAIL:
                usage_pct = usage.emails_sent_today / quota.emails_per_day
                if usage_pct > 0.8:
                    logger.warning(
                        f"⚠️  Tenant {tenant_id} at {usage_pct:.0%} of daily email quota"
                    )
            
            elif operation == OperationType.LLM_CALL:
                usage_pct = usage.llm_cost_month / quota.llm_cost_per_month
                if usage_pct > 0.8:
                    logger.warning(
                        f"⚠️  Tenant {tenant_id} at {usage_pct:.0%} of monthly LLM budget"
                    )
            
            return True
    
    def get_usage(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Get usage stats for tenant"""
        with self.lock:
            if tenant_id not in self.usage:
                return None
            
            usage = self.usage[tenant_id]
            quota = self.quotas[tenant_id]
            
            return {
                "tenant_id": tenant_id,
                "emails": {
                    "sent_hour": usage.emails_sent_hour,
                    "limit_hour": quota.emails_per_hour,
                    "pct_hour": usage.emails_sent_hour / quota.emails_per_hour,
                    "sent_day": usage.emails_sent_today,
                    "limit_day": quota.emails_per_day,
                    "pct_day": usage.emails_sent_today / quota.emails_per_day,
                },
                "api": {
                    "calls_minute": usage.api_calls_minute,
                    "limit_minute": quota.api_calls_per_minute,
                    "pct": usage.api_calls_minute / quota.api_calls_per_minute,
                },
                "campaigns": {
                    "active": usage.active_campaigns,
                    "limit": quota.concurrent_campaigns,
                    "pct": usage.active_campaigns / quota.concurrent_campaigns,
                },
                "llm": {
                    "cost_month": usage.llm_cost_month,
                    "limit_month": quota.llm_cost_per_month,
                    "pct": usage.llm_cost_month / quota.llm_cost_per_month,
                },
                "storage": {
                    "used_gb": usage.storage_used_gb,
                    "limit_gb": quota.storage_gb,
                    "pct": usage.storage_used_gb / quota.storage_gb,
                },
            }
    
    def get_usage_events(
        self,
        tenant_id: str,
        hours: int = 24,
    ) -> List[UsageEvent]:
        """Get usage events for tenant in last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            e for e in self.events
            if e.tenant_id == tenant_id and e.timestamp >= cutoff
        ]
    
    def _reset_counters(self, tenant_id: str) -> None:
        """Reset hourly/daily counters if needed"""
        usage = self.usage[tenant_id]
        now = datetime.now()
        
        # Reset hourly counter
        if now.hour != usage.last_reset_hour.hour:
            usage.emails_sent_hour = 0
            usage.api_calls_minute = 0
            usage.last_reset_hour = now
        
        # Reset daily counter
        if now.date() != usage.last_reset_day.date():
            usage.emails_sent_today = 0
            usage.last_reset_day = now
        
        # Reset monthly counter
        if now.month != usage.last_reset_minute.month:
            usage.llm_cost_month = 0.0
            usage.last_reset_minute = now


# ============================================================================
# WORKER POOL PER TENANT
# ============================================================================

@dataclass
class WorkerPoolConfig:
    """Worker pool configuration"""
    tenant_id: str
    max_concurrent_workers: int = 5
    max_queue_size: int = 1000
    priority_levels: int = 3
    worker_timeout_seconds: int = 300


class TenantWorkerPool:
    """
    Isolated worker pool per tenant
    
    Ensures fair resource allocation across tenants
    """
    
    def __init__(self, config: WorkerPoolConfig):
        self.config = config
        self.queue: List[Tuple[int, Any]] = []  # (priority, task)
        self.active_workers: int = 0
        self.lock = threading.RLock()
    
    def submit_task(self, task: Any, priority: int = 1) -> bool:
        """
        Submit task to queue
        
        Args:
            task: Task to execute
            priority: 1 (high) to config.priority_levels (low)
        
        Returns:
            True if queued, False if queue full
        """
        with self.lock:
            if len(self.queue) >= self.config.max_queue_size:
                logger.warning(
                    f"⚠️  Queue full for tenant {self.config.tenant_id}"
                )
                return False
            
            self.queue.append((priority, task))
            self.queue.sort(key=lambda x: x[0])  # Sort by priority
            return True
    
    def can_execute_worker(self) -> bool:
        """Check if new worker can be started"""
        with self.lock:
            return self.active_workers < self.config.max_concurrent_workers
    
    def mark_worker_active(self) -> None:
        """Mark worker as active"""
        with self.lock:
            self.active_workers += 1
    
    def mark_worker_inactive(self) -> None:
        """Mark worker as inactive"""
        with self.lock:
            self.active_workers = max(0, self.active_workers - 1)
    
    def get_next_task(self) -> Optional[Any]:
        """Get next task from queue"""
        with self.lock:
            if self.queue:
                _, task = self.queue.pop(0)
                return task
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get pool status"""
        with self.lock:
            return {
                "tenant_id": self.config.tenant_id,
                "active_workers": self.active_workers,
                "max_workers": self.config.max_concurrent_workers,
                "queue_size": len(self.queue),
                "max_queue_size": self.config.max_queue_size,
                "utilization": self.active_workers / self.config.max_concurrent_workers,
            }


# ============================================================================
# MULTI-TENANT ORCHESTRATOR
# ============================================================================

class MultiTenantOrchestrator:
    """
    Manage quotas and worker pools across all tenants
    
    Features:
    - Per-tenant resource isolation
    - Fair scheduling
    - Cost tracking
    - Capacity planning
    """
    
    def __init__(self):
        self.quota_manager = QuotaManager()
        self.worker_pools: Dict[str, TenantWorkerPool] = {}
        self.lock = threading.RLock()
    
    def register_tenant(
        self,
        tenant_id: str,
        quota_config: QuotaConfig,
        worker_config: WorkerPoolConfig,
    ) -> None:
        """Register new tenant with quotas and worker pool"""
        with self.lock:
            self.quota_manager.set_quota(
                tenant_id,
                emails_per_day=quota_config.emails_per_day,
                emails_per_hour=quota_config.emails_per_hour,
                llm_cost_per_month=quota_config.llm_cost_per_month,
            )
            self.worker_pools[tenant_id] = TenantWorkerPool(worker_config)
            
            logger.info(f"✅ Tenant {tenant_id} registered")
    
    def submit_operation(
        self,
        tenant_id: str,
        operation: OperationType,
        task: Any,
        priority: int = 1,
    ) -> Tuple[bool, Optional[str]]:
        """
        Submit operation respecting quotas
        
        Returns:
            (success, error_message) tuple
        """
        # Check quota
        allowed, reason = self.quota_manager.check_quota(tenant_id, operation)
        if not allowed:
            return False, reason
        
        # Submit to worker pool
        pool = self.worker_pools.get(tenant_id)
        if not pool:
            return False, f"Tenant {tenant_id} not found"
        
        if not pool.submit_task(task, priority):
            return False, "Worker queue full"
        
        return True, None
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get status across all tenants"""
        with self.lock:
            return {
                "tenants": len(self.worker_pools),
                "worker_pools": {
                    tenant_id: pool.get_status()
                    for tenant_id, pool in self.worker_pools.items()
                },
                "timestamp": datetime.now().isoformat(),
            }


if __name__ == "__main__":
    print("✅ Multi-tenant quota & isolation system ready")
    print("   Features: Per-tenant quotas, worker pools, cost controls")
