"""
Admin Dashboard for Saga Orchestrator
Real-time monitoring of active sagas, health metrics, and system status.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
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

class DashboardMetricType(Enum):
    """Dashboard metric categories."""
    REALTIME = "realtime"
    HOURLY = "hourly"
    DAILY = "daily"


@dataclass
class ActiveSagaInfo:
    """Information about an active saga."""
    saga_id: str
    saga_type: str
    status: str  # running, paused, waiting
    created_at: str
    duration_seconds: float
    current_step: str
    retry_count: int
    failure_reason: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class SagaCompletionStats:
    """Statistics about completed sagas."""
    total_completed: int
    successful: int
    failed: int
    compensated: int
    average_duration_seconds: float
    success_rate: float  # 0.0 to 1.0
    failure_rate: float
    compensation_rate: float


@dataclass
class SystemHealthMetrics:
    """Overall system health."""
    active_sagas_count: int
    dlq_items_count: int
    circuit_breaker_open: bool
    circuit_breaker_trips_24h: int
    adapter_errors_24h: Dict[str, int]
    average_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    uptime_seconds: float
    memory_usage_mb: float
    cpu_usage_percent: float


@dataclass
class DashboardSnapshot:
    """Complete dashboard snapshot."""
    timestamp: str
    active_sagas: List[ActiveSagaInfo]
    completion_stats: SagaCompletionStats
    system_health: SystemHealthMetrics
    alerts: List[str]  # Active alerts


# ============================================================================
# Admin Dashboard Manager
# ============================================================================

class SagaAdminDashboard:
    """Manages admin dashboard data and views."""
    
    def __init__(self):
        """Initialize dashboard manager."""
        self._active_sagas: Dict[str, Dict[str, Any]] = {}
        self._completion_history: List[Dict[str, Any]] = []
        self._metrics_history: Dict[str, List[Any]] = {
            "realtime": [],
            "hourly": [],
            "daily": []
        }
        self._alerts: List[str] = []
        self._start_time = datetime.now(timezone.utc)
        logger.info("Admin dashboard initialized")
    
    # ========================================================================
    # Active Saga Management
    # ========================================================================
    
    def register_saga(
        self,
        saga_id: str,
        saga_type: str,
        user_id: Optional[str] = None
    ) -> None:
        """Register a saga as active."""
        self._active_sagas[saga_id] = {
            "saga_id": saga_id,
            "saga_type": saga_type,
            "status": "running",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "current_step": "initial",
            "retry_count": 0,
            "failure_reason": None,
            "user_id": user_id,
            "step_history": []
        }
        logger.info(f"Saga {saga_id} registered on dashboard")
    
    def update_saga_step(
        self,
        saga_id: str,
        step_name: str,
        status: str = "running"
    ) -> None:
        """Update saga's current step."""
        if saga_id in self._active_sagas:
            saga = self._active_sagas[saga_id]
            saga["current_step"] = step_name
            saga["status"] = status
            saga["step_history"].append({
                "step": step_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": status
            })
            logger.debug(f"Saga {saga_id} updated to step {step_name}")
    
    def mark_saga_paused(self, saga_id: str) -> None:
        """Mark saga as paused."""
        if saga_id in self._active_sagas:
            self._active_sagas[saga_id]["status"] = "paused"
    
    def mark_saga_waiting(self, saga_id: str, reason: str) -> None:
        """Mark saga as waiting for external action."""
        if saga_id in self._active_sagas:
            self._active_sagas[saga_id]["status"] = "waiting"
            self._active_sagas[saga_id]["failure_reason"] = reason
    
    def increment_saga_retry(self, saga_id: str) -> None:
        """Increment retry count for saga."""
        if saga_id in self._active_sagas:
            self._active_sagas[saga_id]["retry_count"] += 1
    
    def complete_saga(
        self,
        saga_id: str,
        status: str,
        failure_reason: Optional[str] = None
    ) -> None:
        """Mark saga as completed and archive."""
        if saga_id not in self._active_sagas:
            return
        
        saga = self._active_sagas[saga_id]
        created_at = datetime.fromisoformat(saga["created_at"])
        created_at = _ensure_utc(created_at)
        duration = (datetime.now(timezone.utc) - created_at).total_seconds()
        
        # Archive completion
        self._completion_history.append({
            "saga_id": saga_id,
            "saga_type": saga["saga_type"],
            "status": status,
            "duration_seconds": duration,
            "retry_count": saga["retry_count"],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "user_id": saga.get("user_id"),
            "step_history": saga["step_history"]
        })
        
        # Remove from active
        del self._active_sagas[saga_id]
        logger.info(f"Saga {saga_id} completed with status {status}")
    
    # ========================================================================
    # Metrics and Statistics
    # ========================================================================
    
    def get_completion_stats(self) -> SagaCompletionStats:
        """Get statistics about completed sagas."""
        if not self._completion_history:
            return SagaCompletionStats(
                total_completed=0,
                successful=0,
                failed=0,
                compensated=0,
                average_duration_seconds=0.0,
                success_rate=0.0,
                failure_rate=0.0,
                compensation_rate=0.0
            )
        
        total = len(self._completion_history)
        successful = len([s for s in self._completion_history if s["status"] == "succeeded"])
        failed = len([s for s in self._completion_history if s["status"] == "failed"])
        compensated = len([s for s in self._completion_history if s["status"] == "compensated"])
        
        avg_duration = sum(s["duration_seconds"] for s in self._completion_history) / total
        
        return SagaCompletionStats(
            total_completed=total,
            successful=successful,
            failed=failed,
            compensated=compensated,
            average_duration_seconds=avg_duration,
            success_rate=successful / total if total > 0 else 0.0,
            failure_rate=failed / total if total > 0 else 0.0,
            compensation_rate=compensated / total if total > 0 else 0.0
        )
    
    def get_system_health(
        self,
        circuit_breaker_open: bool = False,
        circuit_breaker_trips_24h: int = 0,
        adapter_errors_24h: Optional[Dict[str, int]] = None
    ) -> SystemHealthMetrics:
        """Get current system health metrics."""
        uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        
        return SystemHealthMetrics(
            active_sagas_count=len(self._active_sagas),
            dlq_items_count=0,  # Would be fetched from DLQ
            circuit_breaker_open=circuit_breaker_open,
            circuit_breaker_trips_24h=circuit_breaker_trips_24h,
            adapter_errors_24h=adapter_errors_24h or {},
            average_response_time_ms=0.0,
            p95_response_time_ms=0.0,
            p99_response_time_ms=0.0,
            uptime_seconds=uptime,
            memory_usage_mb=0.0,
            cpu_usage_percent=0.0
        )
    
    # ========================================================================
    # Dashboard Views
    # ========================================================================
    
    def get_active_sagas_view(self) -> List[ActiveSagaInfo]:
        """Get list of all active sagas."""
        sagas = []
        for saga_data in self._active_sagas.values():
            created_at = datetime.fromisoformat(saga_data["created_at"])
            created_at = _ensure_utc(created_at)
            duration = (datetime.now(timezone.utc) - created_at).total_seconds()
            
            saga = ActiveSagaInfo(
                saga_id=saga_data["saga_id"],
                saga_type=saga_data["saga_type"],
                status=saga_data["status"],
                created_at=saga_data["created_at"],
                duration_seconds=duration,
                current_step=saga_data["current_step"],
                retry_count=saga_data["retry_count"],
                failure_reason=saga_data.get("failure_reason"),
                user_id=saga_data.get("user_id")
            )
            sagas.append(saga)
        
        # Sort by duration (longest running first)
        sagas.sort(key=lambda s: s.duration_seconds, reverse=True)
        return sagas
    
    def get_dashboard_snapshot(self) -> DashboardSnapshot:
        """Get complete dashboard snapshot."""
        return DashboardSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            active_sagas=self.get_active_sagas_view(),
            completion_stats=self.get_completion_stats(),
            system_health=self.get_system_health(),
            alerts=self._alerts.copy()
        )
    
    def get_saga_detail(self, saga_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific saga."""
        if saga_id in self._active_sagas:
            saga = self._active_sagas[saga_id].copy()
            created_at = datetime.fromisoformat(saga["created_at"])
            created_at = _ensure_utc(created_at)
            saga["duration_seconds"] = (datetime.now(timezone.utc) - created_at).total_seconds()
            return saga
        
        # Check completed history
        for completed in self._completion_history:
            if completed["saga_id"] == saga_id:
                return completed
        
        return None
    
    def get_saga_timeline(self, saga_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get timeline of saga execution."""
        detail = self.get_saga_detail(saga_id)
        if detail and "step_history" in detail:
            return detail["step_history"]
        return None
    
    def get_sagas_by_type(self, saga_type: str) -> List[Dict[str, Any]]:
        """Get all sagas of a specific type."""
        result = []
        
        # Active sagas
        for saga in self._active_sagas.values():
            if saga["saga_type"] == saga_type:
                created_at = datetime.fromisoformat(saga["created_at"])
                created_at = _ensure_utc(created_at)
                duration = (datetime.now(timezone.utc) - created_at).total_seconds()
                result.append({
                    "saga_id": saga["saga_id"],
                    "status": saga["status"],
                    "duration_seconds": duration,
                    "current_step": saga["current_step"],
                    "type": "active"
                })
        
        # Completed sagas (last 100)
        for completed in self._completion_history[-100:]:
            if completed["saga_type"] == saga_type:
                result.append({
                    "saga_id": completed["saga_id"],
                    "status": completed["status"],
                    "duration_seconds": completed["duration_seconds"],
                    "type": "completed"
                })
        
        return result
    
    # ========================================================================
    # Filtering and Searching
    # ========================================================================
    
    def search_sagas(
        self,
        query: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Search sagas by ID, type, or user."""
        results = []
        query_lower = query.lower()
        
        # Search active sagas
        for saga in self._active_sagas.values():
            if (query_lower in saga["saga_id"].lower() or
                query_lower in saga["saga_type"].lower() or
                (saga.get("user_id") and query_lower in saga["user_id"].lower())):
                created_at = datetime.fromisoformat(saga["created_at"])
                created_at = _ensure_utc(created_at)
                duration = (datetime.now(timezone.utc) - created_at).total_seconds()
                results.append({
                    "saga_id": saga["saga_id"],
                    "saga_type": saga["saga_type"],
                    "status": saga["status"],
                    "duration_seconds": duration,
                    "type": "active"
                })
        
        # Search completed sagas
        for completed in self._completion_history[-1000:]:
            if (query_lower in completed["saga_id"].lower() or
                query_lower in completed["saga_type"].lower() or
                (completed.get("user_id") and query_lower in completed["user_id"].lower())):
                results.append({
                    "saga_id": completed["saga_id"],
                    "saga_type": completed["saga_type"],
                    "status": completed["status"],
                    "duration_seconds": completed["duration_seconds"],
                    "type": "completed"
                })
        
        return results[:limit]
    
    def get_sagas_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all sagas for a specific user."""
        results = []
        
        # Active sagas
        for saga in self._active_sagas.values():
            if saga.get("user_id") == user_id:
                created_at = datetime.fromisoformat(saga["created_at"])
                created_at = _ensure_utc(created_at)
                duration = (datetime.now(timezone.utc) - created_at).total_seconds()
                results.append({
                    "saga_id": saga["saga_id"],
                    "status": saga["status"],
                    "duration_seconds": duration,
                    "type": "active"
                })
        
        # Completed sagas
        for completed in self._completion_history:
            if completed.get("user_id") == user_id:
                results.append({
                    "saga_id": completed["saga_id"],
                    "status": completed["status"],
                    "duration_seconds": completed["duration_seconds"],
                    "type": "completed"
                })
        
        return results
    
    # ========================================================================
    # Alerts and Notifications
    # ========================================================================
    
    def add_alert(self, alert_message: str) -> None:
        """Add an alert."""
        self._alerts.append(f"[{datetime.now(timezone.utc).isoformat()}] {alert_message}")
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-1000:]
        logger.warning(f"Alert: {alert_message}")
    
    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self._alerts.clear()
    
    def get_alerts(self) -> List[str]:
        """Get current alerts."""
        return self._alerts.copy()
    
    # ========================================================================
    # Data Export
    # ========================================================================
    
    def export_snapshot_json(self) -> str:
        """Export dashboard snapshot as JSON."""
        snapshot = self.get_dashboard_snapshot()
        data = {
            "timestamp": snapshot.timestamp,
            "active_sagas_count": len(snapshot.active_sagas),
            "completion_stats": asdict(snapshot.completion_stats),
            "system_health": asdict(snapshot.system_health),
            "active_sagas": [asdict(s) for s in snapshot.active_sagas[:50]],
            "alerts": snapshot.alerts
        }
        return json.dumps(data, indent=2)
    
    def get_metrics_report(self) -> Dict[str, Any]:
        """Get comprehensive metrics report."""
        completion_stats = self.get_completion_stats()
        active_sagas = self.get_active_sagas_view()
        
        # Group active sagas by status
        status_breakdown = {}
        for saga in active_sagas:
            status_breakdown[saga.status] = status_breakdown.get(saga.status, 0) + 1
        
        # Group completed by type
        type_breakdown = {}
        for completed in self._completion_history:
            saga_type = completed["saga_type"]
            if saga_type not in type_breakdown:
                type_breakdown[saga_type] = {
                    "total": 0,
                    "successful": 0,
                    "failed": 0
                }
            type_breakdown[saga_type]["total"] += 1
            if completed["status"] == "succeeded":
                type_breakdown[saga_type]["successful"] += 1
            elif completed["status"] == "failed":
                type_breakdown[saga_type]["failed"] += 1
        
        return {
            "summary": {
                "active_sagas": len(active_sagas),
                "total_completed": completion_stats.total_completed,
                "success_rate": completion_stats.success_rate,
                "failure_rate": completion_stats.failure_rate,
                "average_duration_seconds": completion_stats.average_duration_seconds
            },
            "active_sagas_by_status": status_breakdown,
            "completed_sagas_by_type": type_breakdown,
            "alerts_count": len(self._alerts),
            "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds()
        }


# ============================================================================
# Global Dashboard Instance
# ============================================================================

_dashboard_instance: Optional[SagaAdminDashboard] = None


def get_admin_dashboard() -> SagaAdminDashboard:
    """Get or create global dashboard instance."""
    global _dashboard_instance
    if _dashboard_instance is None:
        _dashboard_instance = SagaAdminDashboard()
    return _dashboard_instance
