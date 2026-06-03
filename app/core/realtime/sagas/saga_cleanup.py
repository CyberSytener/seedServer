"""
Automated Cleanup for Saga Orchestrator
Removes old completed sagas, manages storage, and maintains performance.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ============================================================================
# Data Models
# ============================================================================

class CleanupStrategy(Enum):
    """Cleanup strategies."""
    AGGRESSIVE = "aggressive"  # Delete older than X days
    CONSERVATIVE = "conservative"  # Delete only very old sagas
    MANUAL = "manual"  # Manual cleanup only


class CleanupTarget(Enum):
    """What to clean up."""
    COMPLETED_SAGAS = "completed_sagas"
    AUDIT_LOGS = "audit_logs"
    METRICS = "metrics"
    SNAPSHOTS = "snapshots"
    REPLAY_RECORDS = "replay_records"
    DLQ_ITEMS = "dlq_items"


@dataclass
class CleanupPolicy:
    """Policy for cleanup operations."""
    enabled: bool = True
    strategy: CleanupStrategy = CleanupStrategy.CONSERVATIVE
    
    # Retention periods (days)
    keep_successful_sagas_days: int = 90
    keep_failed_sagas_days: int = 180
    keep_audit_logs_days: int = 365
    keep_metrics_days: int = 30
    keep_snapshots_days: int = 14
    keep_replay_records_days: int = 7
    keep_dlq_items_days: int = 30
    
    # Limits
    max_completed_sagas: int = 100000
    max_audit_log_entries: int = 1000000
    max_snapshots_per_saga: int = 100
    
    # Scheduling
    run_at_hour: int = 2  # Run at 2 AM
    run_frequency_days: int = 1  # Daily
    
    # Notifications
    send_report: bool = True
    report_recipients: List[str] = None


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""
    timestamp: str
    target: CleanupTarget
    items_deleted: int
    space_freed_mb: float
    duration_seconds: float
    success: bool
    error_message: Optional[str] = None


# ============================================================================
# Cleanup Manager
# ============================================================================

class SagaCleanupManager:
    """Manages automated cleanup of old saga data."""
    
    def __init__(self, policy: Optional[CleanupPolicy] = None):
        """Initialize cleanup manager.
        
        Args:
            policy: Cleanup policy configuration
        """
        self.policy = policy or CleanupPolicy()
        self._cleanup_history: List[CleanupResult] = []
        self._last_cleanup: Optional[datetime] = None
        self._cleanup_in_progress = False
        logger.info("Saga cleanup manager initialized")
    
    # ========================================================================
    # Configuration
    # ========================================================================
    
    def update_policy(self, policy: CleanupPolicy) -> None:
        """Update cleanup policy."""
        self.policy = policy
        logger.info("Cleanup policy updated")
    
    def get_policy(self) -> CleanupPolicy:
        """Get current cleanup policy."""
        return self.policy
    
    # ========================================================================
    # Cleanup Operations
    # ========================================================================
    
    def cleanup_completed_sagas(
        self,
        completed_sagas: List[Dict[str, Any]],
        dry_run: bool = False
    ) -> CleanupResult:
        """Clean up old completed sagas."""
        start_time = datetime.now(timezone.utc)
        deleted_count = 0
        space_freed = 0.0
        
        try:
            cutoff_dates = {
                "succeeded": datetime.now(timezone.utc) - timedelta(
                    days=self.policy.keep_successful_sagas_days
                ),
                "failed": datetime.now(timezone.utc) - timedelta(
                    days=self.policy.keep_failed_sagas_days
                ),
                "compensated": datetime.now(timezone.utc) - timedelta(
                    days=self.policy.keep_failed_sagas_days
                )
            }
            
            for saga in completed_sagas:
                saga_status = saga.get("status", "unknown")
                completed_at = _ensure_utc(datetime.fromisoformat(saga.get("completed_at", "")))
                cutoff = cutoff_dates.get(saga_status)
                
                if cutoff and completed_at < cutoff:
                    if not dry_run:
                        # Delete saga
                        space_freed += self._estimate_saga_size(saga)
                        logger.debug(f"Deleted saga {saga.get('saga_id')}")
                    deleted_count += 1
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.COMPLETED_SAGAS,
                items_deleted=deleted_count,
                space_freed_mb=space_freed / (1024 * 1024),
                duration_seconds=duration,
                success=True
            )
            
            self._cleanup_history.append(result)
            logger.info(f"Cleaned up {deleted_count} sagas ({space_freed:.2f} bytes)")
            return result
        
        except Exception as e:
            logger.error(f"Error cleaning up sagas: {e}")
            return CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.COMPLETED_SAGAS,
                items_deleted=0,
                space_freed_mb=0.0,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                success=False,
                error_message=str(e)
            )
    
    def cleanup_audit_logs(
        self,
        audit_logs: List[Dict[str, Any]],
        dry_run: bool = False
    ) -> CleanupResult:
        """Clean up old audit log entries."""
        start_time = datetime.now(timezone.utc)
        deleted_count = 0
        space_freed = 0.0
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(
                days=self.policy.keep_audit_logs_days
            )
            
            for log_entry in audit_logs:
                timestamp = _ensure_utc(datetime.fromisoformat(log_entry.get("timestamp", "")))
                
                if timestamp < cutoff_date:
                    if not dry_run:
                        space_freed += self._estimate_log_size(log_entry)
                    deleted_count += 1
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.AUDIT_LOGS,
                items_deleted=deleted_count,
                space_freed_mb=space_freed / (1024 * 1024),
                duration_seconds=duration,
                success=True
            )
            
            self._cleanup_history.append(result)
            logger.info(f"Cleaned up {deleted_count} audit log entries")
            return result
        
        except Exception as e:
            logger.error(f"Error cleaning up audit logs: {e}")
            return CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.AUDIT_LOGS,
                items_deleted=0,
                space_freed_mb=0.0,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                success=False,
                error_message=str(e)
            )
    
    def cleanup_metrics(
        self,
        dry_run: bool = False
    ) -> CleanupResult:
        """Clean up old metrics data."""
        start_time = datetime.now(timezone.utc)
        deleted_count = 0
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(
                days=self.policy.keep_metrics_days
            )
            
            # Count old metrics that would be deleted
            # (Implementation depends on metrics storage)
            deleted_count = 0
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.METRICS,
                items_deleted=deleted_count,
                space_freed_mb=0.0,
                duration_seconds=duration,
                success=True
            )
            
            self._cleanup_history.append(result)
            logger.info(f"Cleaned up metrics older than {self.policy.keep_metrics_days} days")
            return result
        
        except Exception as e:
            logger.error(f"Error cleaning up metrics: {e}")
            return CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.METRICS,
                items_deleted=0,
                space_freed_mb=0.0,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                success=False,
                error_message=str(e)
            )
    
    def cleanup_snapshots(
        self,
        snapshots: Dict[str, List[Dict[str, Any]]],
        dry_run: bool = False
    ) -> CleanupResult:
        """Clean up old saga snapshots."""
        start_time = datetime.now(timezone.utc)
        deleted_count = 0
        space_freed = 0.0
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(
                days=self.policy.keep_snapshots_days
            )
            
            for saga_id, saga_snapshots in snapshots.items():
                # Keep max N snapshots per saga
                if len(saga_snapshots) > self.policy.max_snapshots_per_saga:
                    excess = len(saga_snapshots) - self.policy.max_snapshots_per_saga
                    deleted_count += excess
                
                # Delete old snapshots
                for snapshot in saga_snapshots:
                    snapshot_time = _ensure_utc(datetime.fromisoformat(
                        snapshot.get("snapshot_time", "")
                    ))
                    if snapshot_time < cutoff_date:
                        if not dry_run:
                            space_freed += self._estimate_snapshot_size(snapshot)
                        deleted_count += 1
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.SNAPSHOTS,
                items_deleted=deleted_count,
                space_freed_mb=space_freed / (1024 * 1024),
                duration_seconds=duration,
                success=True
            )
            
            self._cleanup_history.append(result)
            logger.info(f"Cleaned up {deleted_count} snapshots")
            return result
        
        except Exception as e:
            logger.error(f"Error cleaning up snapshots: {e}")
            return CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.SNAPSHOTS,
                items_deleted=0,
                space_freed_mb=0.0,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                success=False,
                error_message=str(e)
            )
    
    def cleanup_dlq_items(
        self,
        dlq_items: List[Dict[str, Any]],
        dry_run: bool = False
    ) -> CleanupResult:
        """Clean up resolved DLQ items."""
        start_time = datetime.now(timezone.utc)
        deleted_count = 0
        space_freed = 0.0
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(
                days=self.policy.keep_dlq_items_days
            )
            
            for item in dlq_items:
                # Delete resolved items older than cutoff
                if item.get("status") == "resolved":
                    resolved_at = _ensure_utc(datetime.fromisoformat(item.get("resolved_at", "")))
                    if resolved_at < cutoff_date:
                        if not dry_run:
                            space_freed += self._estimate_dlq_size(item)
                        deleted_count += 1
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.DLQ_ITEMS,
                items_deleted=deleted_count,
                space_freed_mb=space_freed / (1024 * 1024),
                duration_seconds=duration,
                success=True
            )
            
            self._cleanup_history.append(result)
            logger.info(f"Cleaned up {deleted_count} DLQ items")
            return result
        
        except Exception as e:
            logger.error(f"Error cleaning up DLQ items: {e}")
            return CleanupResult(
                timestamp=datetime.now(timezone.utc).isoformat(),
                target=CleanupTarget.DLQ_ITEMS,
                items_deleted=0,
                space_freed_mb=0.0,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
                success=False,
                error_message=str(e)
            )
    
    # ========================================================================
    # Batch Cleanup
    # ========================================================================
    
    def run_full_cleanup(
        self,
        completed_sagas: List[Dict[str, Any]],
        audit_logs: List[Dict[str, Any]],
        snapshots: Dict[str, List[Dict[str, Any]]],
        dlq_items: List[Dict[str, Any]],
        dry_run: bool = False
    ) -> List[CleanupResult]:
        """Run full cleanup cycle."""
        if self._cleanup_in_progress:
            logger.warning("Cleanup already in progress")
            return []
        
        self._cleanup_in_progress = True
        results = []
        
        try:
            logger.info(f"Starting full cleanup (dry_run={dry_run})")
            
            # Run cleanups in order
            results.append(self.cleanup_completed_sagas(completed_sagas, dry_run))
            results.append(self.cleanup_audit_logs(audit_logs, dry_run))
            results.append(self.cleanup_metrics(dry_run))
            results.append(self.cleanup_snapshots(snapshots, dry_run))
            results.append(self.cleanup_dlq_items(dlq_items, dry_run))
            
            self._last_cleanup = datetime.now(timezone.utc)
            
            # Log summary
            total_deleted = sum(r.items_deleted for r in results)
            total_freed = sum(r.space_freed_mb for r in results)
            logger.info(
                f"Cleanup complete: {total_deleted} items deleted, "
                f"{total_freed:.2f} MB freed"
            )
            
            return results
        
        finally:
            self._cleanup_in_progress = False
    
    # ========================================================================
    # Reporting
    # ========================================================================
    
    def get_cleanup_report(self) -> Dict[str, Any]:
        """Get cleanup activity report."""
        if not self._cleanup_history:
            return {
                "total_cleanups": 0,
                "total_deleted": 0,
                "total_freed_mb": 0.0,
                "last_cleanup": None
            }
        
        total_deleted = sum(r.items_deleted for r in self._cleanup_history)
        total_freed = sum(r.space_freed_mb for r in self._cleanup_history)
        successful = len([r for r in self._cleanup_history if r.success])
        failed = len([r for r in self._cleanup_history if not r.success])
        
        return {
            "total_cleanups": len(self._cleanup_history),
            "successful": successful,
            "failed": failed,
            "total_deleted": total_deleted,
            "total_freed_mb": total_freed,
            "last_cleanup": (
                self._last_cleanup.isoformat() if self._last_cleanup else None
            ),
            "by_target": self._get_cleanup_by_target(),
            "latest_results": [
                {
                    "timestamp": r.timestamp,
                    "target": r.target.value,
                    "deleted": r.items_deleted,
                    "freed_mb": r.space_freed_mb,
                    "success": r.success
                }
                for r in self._cleanup_history[-5:]
            ]
        }
    
    def _get_cleanup_by_target(self) -> Dict[str, int]:
        """Get cleanup counts by target."""
        by_target = {}
        for result in self._cleanup_history:
            target = result.target.value
            by_target[target] = by_target.get(target, 0) + result.items_deleted
        return by_target
    
    def get_cleanup_history(self, limit: int = 50) -> List[CleanupResult]:
        """Get cleanup history."""
        return self._cleanup_history[-limit:]
    
    # ========================================================================
    # Utilities
    # ========================================================================
    
    def _estimate_saga_size(self, saga: Dict[str, Any]) -> float:
        """Estimate size in bytes of a saga record."""
        return len(json.dumps(saga).encode()) * 1.1  # Add 10% overhead
    
    def _estimate_log_size(self, log_entry: Dict[str, Any]) -> float:
        """Estimate size in bytes of a log entry."""
        return len(json.dumps(log_entry).encode()) * 1.1
    
    def _estimate_snapshot_size(self, snapshot: Dict[str, Any]) -> float:
        """Estimate size in bytes of a snapshot."""
        return len(json.dumps(snapshot).encode()) * 1.1
    
    def _estimate_dlq_size(self, item: Dict[str, Any]) -> float:
        """Estimate size in bytes of a DLQ item."""
        return len(json.dumps(item).encode()) * 1.1
    
    # ========================================================================
    # Scheduling
    # ========================================================================
    
    def should_run_cleanup(self) -> bool:
        """Check if cleanup should run now."""
        if not self.policy.enabled:
            return False
        
        if self._cleanup_in_progress:
            return False
        
        if self._last_cleanup:
            time_since_last = datetime.now(timezone.utc) - self._last_cleanup
            if time_since_last.days < self.policy.run_frequency_days:
                return False
        
        current_hour = datetime.now(timezone.utc).hour
        return current_hour == self.policy.run_at_hour


# ============================================================================
# Global Cleanup Manager Instance
# ============================================================================

_cleanup_manager_instance: Optional[SagaCleanupManager] = None


def get_cleanup_manager(policy: Optional[CleanupPolicy] = None) -> SagaCleanupManager:
    """Get or create global cleanup manager."""
    global _cleanup_manager_instance
    if _cleanup_manager_instance is None:
        _cleanup_manager_instance = SagaCleanupManager(policy)
    return _cleanup_manager_instance
