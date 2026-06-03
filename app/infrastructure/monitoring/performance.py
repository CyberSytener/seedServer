"""
Performance monitoring and metrics collection for production readiness.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.infrastructure.db.sqlite import DB


@dataclass
class PerformanceMetric:
    """Single performance measurement."""
    timestamp: str
    operation: str  # 'diagnostic_generation', 'lesson_generation', etc.
    duration_ms: float
    token_count: Optional[int] = None
    item_count: Optional[int] = None
    success: bool = True
    error_type: Optional[str] = None
    prompt_version: Optional[str] = None
    parser_version: Optional[str] = None
    user_id: Optional[str] = None
    validation_retry_count: Optional[int] = None  # LLM validation retries
    validation_failure_reason: Optional[str] = None  # Why validation failed


@dataclass
class PerformanceSnapshot:
    """Aggregated performance snapshot."""
    period_start: str
    period_end: str
    total_operations: int
    successful_operations: int
    failed_operations: int
    avg_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    total_tokens: int
    avg_tokens_per_operation: float
    operations_by_type: Dict[str, int]


class PerformanceMonitor:
    """Monitor and track system performance metrics."""
    
    def __init__(self, db: DB):
        self.db = db
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create performance metrics tables if they don't exist."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                operation TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                token_count INTEGER,
                item_count INTEGER,
                success INTEGER NOT NULL DEFAULT 1,
                error_type TEXT,
                prompt_version TEXT,
                parser_version TEXT,
                user_id TEXT,
                validation_retry_count INTEGER,
                validation_failure_reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_perf_timestamp 
            ON performance_metrics(timestamp)
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_perf_operation 
            ON performance_metrics(operation)
        """)
    
    def record_metric(self, metric: PerformanceMetric):
        """Record a performance metric."""
        self.db.execute("""
            INSERT INTO performance_metrics 
            (timestamp, operation, duration_ms, token_count, item_count, 
             success, error_type, prompt_version, parser_version, user_id,
             validation_retry_count, validation_failure_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metric.timestamp,
            metric.operation,
            metric.duration_ms,
            metric.token_count,
            metric.item_count,
            1 if metric.success else 0,
            metric.error_type,
            metric.prompt_version,
            metric.parser_version,
            metric.user_id,
            metric.validation_retry_count,
            metric.validation_failure_reason
        ))
    
    def get_snapshot(
        self, 
        hours: int = 24,
        operation: Optional[str] = None
    ) -> PerformanceSnapshot:
        """Get performance snapshot for the last N hours."""
        from datetime import timedelta
        
        now = datetime.now(timezone.utc)
        start_time = (now - timedelta(hours=hours)).isoformat()
        
        # Build query
        where_clause = "WHERE timestamp >= ?"
        params = [start_time]
        
        if operation:
            where_clause += " AND operation = ?"
            params.append(operation)
        
        # Get basic stats
        row = self.db.fetchone(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                AVG(duration_ms) as avg_duration,
                SUM(COALESCE(token_count, 0)) as total_tokens
            FROM performance_metrics
            {where_clause}
        """, tuple(params))
        
        if not row or row['total'] == 0:
            return PerformanceSnapshot(
                period_start=start_time,
                period_end=now.isoformat(),
                total_operations=0,
                successful_operations=0,
                failed_operations=0,
                avg_duration_ms=0.0,
                p50_duration_ms=0.0,
                p95_duration_ms=0.0,
                p99_duration_ms=0.0,
                total_tokens=0,
                avg_tokens_per_operation=0.0,
                operations_by_type={}
            )
        
        # Get percentiles
        durations = self.db.fetchall(f"""
            SELECT duration_ms 
            FROM performance_metrics
            {where_clause}
            ORDER BY duration_ms
        """, tuple(params))
        
        duration_list = [d['duration_ms'] for d in durations]
        total = len(duration_list)
        
        p50 = duration_list[int(total * 0.50)] if total > 0 else 0
        p95 = duration_list[int(total * 0.95)] if total > 0 else 0
        p99 = duration_list[int(total * 0.99)] if total > 0 else 0
        
        # Get operations by type
        ops_by_type = {}
        type_rows = self.db.fetchall(f"""
            SELECT operation, COUNT(*) as count
            FROM performance_metrics
            {where_clause}
            GROUP BY operation
        """, tuple(params))
        
        for type_row in type_rows:
            ops_by_type[type_row['operation']] = type_row['count']
        
        avg_tokens = (row['total_tokens'] / row['total']) if row['total'] > 0 else 0
        
        return PerformanceSnapshot(
            period_start=start_time,
            period_end=now.isoformat(),
            total_operations=row['total'],
            successful_operations=row['successful'],
            failed_operations=row['failed'],
            avg_duration_ms=row['avg_duration'],
            p50_duration_ms=p50,
            p95_duration_ms=p95,
            p99_duration_ms=p99,
            total_tokens=row['total_tokens'],
            avg_tokens_per_operation=avg_tokens,
            operations_by_type=ops_by_type
        )
    
    def check_degradation(
        self,
        current_snapshot: PerformanceSnapshot,
        baseline_snapshot: PerformanceSnapshot,
        thresholds: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Check for performance degradation compared to baseline.
        
        Returns dict with alerts and recommendations.
        """
        if thresholds is None:
            thresholds = {
                'duration_increase_pct': 20.0,  # 20% slower
                'token_increase_pct': 15.0,      # 15% more tokens
                'error_rate_pct': 5.0             # 5% error rate
            }
        
        alerts = []
        recommendations = []
        
        # Check duration degradation
        if baseline_snapshot.avg_duration_ms > 0:
            duration_change = (
                (current_snapshot.avg_duration_ms - baseline_snapshot.avg_duration_ms) 
                / baseline_snapshot.avg_duration_ms * 100
            )
            
            if duration_change > thresholds['duration_increase_pct']:
                alerts.append({
                    'type': 'duration_degradation',
                    'severity': 'warning',
                    'message': f"Average duration increased by {duration_change:.1f}%",
                    'current': current_snapshot.avg_duration_ms,
                    'baseline': baseline_snapshot.avg_duration_ms
                })
                recommendations.append("Check for LLM API latency issues or network problems")
        
        # Check token usage
        if baseline_snapshot.avg_tokens_per_operation > 0:
            token_change = (
                (current_snapshot.avg_tokens_per_operation - baseline_snapshot.avg_tokens_per_operation)
                / baseline_snapshot.avg_tokens_per_operation * 100
            )
            
            if token_change > thresholds['token_increase_pct']:
                alerts.append({
                    'type': 'token_usage_increase',
                    'severity': 'info',
                    'message': f"Token usage increased by {token_change:.1f}%",
                    'current': current_snapshot.avg_tokens_per_operation,
                    'baseline': baseline_snapshot.avg_tokens_per_operation
                })
                recommendations.append("Review prompt templates for unnecessary verbosity")
        
        # Check error rate
        if current_snapshot.total_operations > 0:
            current_error_rate = (
                current_snapshot.failed_operations / current_snapshot.total_operations * 100
            )
            
            if current_error_rate > thresholds['error_rate_pct']:
                alerts.append({
                    'type': 'high_error_rate',
                    'severity': 'critical',
                    'message': f"Error rate is {current_error_rate:.1f}%",
                    'current_errors': current_snapshot.failed_operations,
                    'total_operations': current_snapshot.total_operations
                })
                recommendations.append("Investigate recent errors and validation failures")
        
        return {
            'has_alerts': len(alerts) > 0,
            'alert_count': len(alerts),
            'alerts': alerts,
            'recommendations': recommendations,
            'thresholds_used': thresholds
        }


class PerformanceContext:
    """Context manager for automatic performance tracking."""
    
    def __init__(
        self,
        monitor: PerformanceMonitor,
        operation: str,
        user_id: Optional[str] = None,
        prompt_version: Optional[str] = None,
        parser_version: Optional[str] = None
    ):
        self.monitor = monitor
        self.operation = operation
        self.user_id = user_id
        self.prompt_version = prompt_version
        self.parser_version = parser_version
        self.start_time = None
        self.token_count = None
        self.item_count = None
        self.success = True
        self.error_type = None
        self.validation_retry_count = None
        self.validation_failure_reason = None
    
    def __enter__(self):
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        
        if exc_type is not None:
            self.success = False
            self.error_type = exc_type.__name__
        
        metric = PerformanceMetric(
            timestamp=datetime.now(timezone.utc).isoformat(),
            operation=self.operation,
            duration_ms=duration_ms,
            token_count=self.token_count,
            item_count=self.item_count,
            success=self.success,
            error_type=self.error_type,
            prompt_version=self.prompt_version,
            parser_version=self.parser_version,
            user_id=self.user_id,
            validation_retry_count=self.validation_retry_count,
            validation_failure_reason=self.validation_failure_reason
        )
        
        try:
            self.monitor.record_metric(metric)
        except Exception as e:
            logging.error(f"Failed to record performance metric: {e}")
        
        return False  # Don't suppress exceptions
    
    def set_token_count(self, count: int):
        """Set token count for this operation."""
        self.token_count = count
    
    def set_item_count(self, count: int):
        """Set item count for this operation."""
        self.item_count = count
    
    def set_validation_retry(self, retry_count: int, failure_reason: Optional[str] = None):
        """Set validation retry information."""
        self.validation_retry_count = retry_count
        self.validation_failure_reason = failure_reason
        self.item_count = count


