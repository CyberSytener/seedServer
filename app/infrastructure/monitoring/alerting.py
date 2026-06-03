"""
Alerting system for critical metrics and degradation detection.
"""
import logging
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum

from app.infrastructure.db.sqlite import DB
from .performance_monitor import PerformanceMonitor


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of alerts."""
    PERFORMANCE_DEGRADATION = "performance_degradation"
    HIGH_ERROR_RATE = "high_error_rate"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SYSTEM_OVERLOAD = "system_overload"
    SECURITY_BREACH = "security_breach"


@dataclass
class Alert:
    """Alert record."""
    id: Optional[int]
    alert_type: str
    severity: str
    title: str
    message: str
    metadata: Dict[str, Any]
    created_at: str
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


class AlertingSystem:
    """Centralized alerting system for monitoring critical metrics."""
    
    def __init__(self, db: DB):
        self.db = db
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create alerts table."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT
            )
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_created 
            ON alerts(created_at DESC)
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_alerts_resolved 
            ON alerts(resolved_at) WHERE resolved_at IS NULL
        """)
    
    def create_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Create a new alert.
        
        Returns alert ID.
        """
        now = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        
        cursor = self.db.execute("""
            INSERT INTO alerts (alert_type, severity, title, message, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            alert_type.value,
            severity.value,
            title,
            message,
            json.dumps(metadata),
            now
        ))
        
        alert_id = cursor.lastrowid
        
        # Log alert
        logging.log(
            self._severity_to_log_level(severity),
            f"[ALERT] {title}: {message}",
            extra={
                "alert_id": alert_id,
                "alert_type": alert_type.value,
                "severity": severity.value,
                "metadata": metadata
            }
        )
        
        return alert_id
    
    def resolve_alert(self, alert_id: int, resolved_by: str):
        """Mark an alert as resolved."""
        now = datetime.now(timezone.utc).isoformat()
        
        self.db.execute("""
            UPDATE alerts
            SET resolved_at = ?, resolved_by = ?
            WHERE id = ? AND resolved_at IS NULL
        """, (now, resolved_by, alert_id))
        
        logging.info(f"Alert {alert_id} resolved by {resolved_by}")
    
    def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[Alert]:
        """Get all unresolved alerts, optionally filtered by severity."""
        if severity:
            rows = self.db.fetchall("""
                SELECT * FROM alerts
                WHERE resolved_at IS NULL AND severity = ?
                ORDER BY created_at DESC
            """, (severity.value,))
        else:
            rows = self.db.fetchall("""
                SELECT * FROM alerts
                WHERE resolved_at IS NULL
                ORDER BY created_at DESC
            """)
        
        return [self._row_to_alert(row) for row in rows]
    
    def get_recent_alerts(self, hours: int = 24, limit: int = 100) -> List[Alert]:
        """Get recent alerts within time window."""
        from datetime import timedelta
        
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        rows = self.db.fetchall("""
            SELECT * FROM alerts
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (cutoff, limit))
        
        return [self._row_to_alert(row) for row in rows]
    
    def check_performance_degradation(self):
        """
        Check for performance degradation and create alerts if needed.
        
        Compares recent performance (last hour) to baseline (last 24h).
        """
        monitor = PerformanceMonitor(self.db)
        
        current_snapshot = monitor.get_snapshot(hours=1)
        baseline_snapshot = monitor.get_snapshot(hours=24)
        
        if current_snapshot.total_operations < 5:
            # Not enough data to determine degradation
            return
        
        alerts_created = monitor.check_degradation(current_snapshot, baseline_snapshot)
        
        # Create alerts based on degradation
        if alerts_created.get("has_alerts"):
            if alerts_created.get("duration_alert"):
                self.create_alert(
                    AlertType.PERFORMANCE_DEGRADATION,
                    AlertSeverity.WARNING,
                    "Performance Degradation: Duration Increased",
                    f"Average duration increased by {alerts_created['duration_pct']:.1f}%",
                    {
                        "current_avg_ms": current_snapshot.avg_duration_ms,
                        "baseline_avg_ms": baseline_snapshot.avg_duration_ms,
                        "degradation_pct": alerts_created["duration_pct"]
                    }
                )
            
            if alerts_created.get("token_alert"):
                self.create_alert(
                    AlertType.PERFORMANCE_DEGRADATION,
                    AlertSeverity.WARNING,
                    "Performance Degradation: Token Usage Increased",
                    f"Token usage increased by {alerts_created['token_pct']:.1f}%",
                    {
                        "current_avg_tokens": current_snapshot.avg_tokens_per_operation,
                        "baseline_avg_tokens": baseline_snapshot.avg_tokens_per_operation,
                        "increase_pct": alerts_created["token_pct"]
                    }
                )
            
            if alerts_created.get("error_alert"):
                error_rate = (current_snapshot.failed_operations / current_snapshot.total_operations * 100)
                self.create_alert(
                    AlertType.HIGH_ERROR_RATE,
                    AlertSeverity.ERROR,
                    "High Error Rate Detected",
                    f"Error rate: {error_rate:.1f}%",
                    {
                        "error_rate_pct": error_rate,
                        "failed_operations": current_snapshot.failed_operations,
                        "total_operations": current_snapshot.total_operations
                    }
                )
    
    def check_rate_limit_abuse(self, threshold_violations: int = 10):
        """
        Check for potential rate limit abuse patterns.
        
        Creates alerts if users are repeatedly hitting rate limits.
        
        Args:
            threshold_violations: Number of rate limit violations to trigger alert
        """
        from datetime import timedelta
        
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        
        # Query API usage to detect rate limit patterns
        # Look for users with excessive requests in short time window
        rows = self.db.fetchall("""
            SELECT user_id, COUNT(*) as request_count,
                   AVG(duration_ms) as avg_duration,
                   SUM(CASE WHEN duration_ms > 5000 THEN 1 ELSE 0 END) as slow_requests
            FROM api_usage
            WHERE created_at >= ?
            GROUP BY user_id
            HAVING request_count > ?
            ORDER BY request_count DESC
        """, (cutoff, threshold_violations * 10))
        
        for row in rows:
            user_id = row["user_id"]
            request_count = row["request_count"]
            avg_duration = row["avg_duration"]
            slow_requests = row["slow_requests"]
            
            # Calculate requests per minute
            requests_per_minute = request_count / 60.0
            
            # Check if pattern looks abusive
            if requests_per_minute > 10:  # More than 10 requests/minute sustained
                self.create_alert(
                    AlertType.RATE_LIMIT_EXCEEDED,
                    AlertSeverity.WARNING,
                    f"High Request Rate: User {user_id[:8]}...",
                    f"User making {requests_per_minute:.1f} requests/min (total: {request_count})",
                    {
                        "user_id": user_id,
                        "request_count": request_count,
                        "requests_per_minute": requests_per_minute,
                        "avg_duration_ms": avg_duration,
                        "slow_requests": slow_requests,
                        "time_window_hours": 1
                    }
                )
            
            # Check for suspicious patterns (many slow requests = possible attack)
            if slow_requests > threshold_violations:
                self.create_alert(
                    AlertType.SYSTEM_OVERLOAD,
                    AlertSeverity.ERROR,
                    f"Potential DoS Pattern: User {user_id[:8]}...",
                    f"User generated {slow_requests} slow requests (>5s) in past hour",
                    {
                        "user_id": user_id,
                        "slow_requests": slow_requests,
                        "total_requests": request_count,
                        "avg_duration_ms": avg_duration
                    }
                )
    
    def _row_to_alert(self, row) -> Alert:
        """Convert database row to Alert object."""
        return Alert(
            id=row["id"],
            alert_type=row["alert_type"],
            severity=row["severity"],
            title=row["title"],
            message=row["message"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            resolved_at=row.get("resolved_at"),
            resolved_by=row.get("resolved_by")
        )
    
    def _severity_to_log_level(self, severity: AlertSeverity) -> int:
        """Map alert severity to Python logging level."""
        mapping = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.ERROR: logging.ERROR,
            AlertSeverity.CRITICAL: logging.CRITICAL
        }
        return mapping.get(severity, logging.WARNING)


