"""
SLO (Service Level Objectives) monitoring and compliance tracking.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

import yaml
from pathlib import Path

from app.infrastructure.db.sqlite import DB


@dataclass
class SLOStatus:
    """Current status of an SLO."""
    name: str
    target: float
    current: float
    is_compliant: bool
    window: str
    last_checked: str
    details: Dict[str, Any]


@dataclass
class SLOReport:
    """Complete SLO compliance report."""
    timestamp: str
    overall_compliance: bool
    slo_count: int
    compliant_count: int
    non_compliant_count: int
    statuses: List[SLOStatus]


class SLOMonitor:
    """Monitor and track SLO compliance."""
    
    def __init__(self, db: DB, config_path: Optional[str] = None):
        self.db = db
        self.logger = logging.getLogger(__name__)
        
        # Load SLO configuration
        if config_path is None:
            config_path = Path(__file__).parent.parent / "slo_config.yaml"
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.slos = self.config.get('slos', {})
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create SLO tracking tables."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS slo_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                slo_name TEXT NOT NULL,
                target_value REAL NOT NULL,
                measured_value REAL NOT NULL,
                is_compliant INTEGER NOT NULL,
                window_hours INTEGER NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_slo_timestamp 
            ON slo_measurements(timestamp)
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_slo_name 
            ON slo_measurements(slo_name)
        """)
    
    def check_availability_slo(self) -> SLOStatus:
        """Check availability SLO based on error rates."""
        slo_config = self.slos.get('availability', {})
        target = slo_config.get('target', 99.9)
        window = slo_config.get('window', '30d')
        
        # Calculate hours from window string
        hours = self._parse_window(window)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Get total requests and errors from performance metrics
        row = self.db.fetchone("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors
            FROM performance_metrics
            WHERE timestamp >= ?
        """, (cutoff,))
        
        total = row['total'] if row and row['total'] else 0
        errors = row['errors'] if row and row['errors'] else 0
        
        if total == 0:
            availability = 100.0
        else:
            availability = ((total - errors) / total) * 100
        
        is_compliant = availability >= target
        
        status = SLOStatus(
            name="availability",
            target=target,
            current=round(availability, 3),
            is_compliant=is_compliant,
            window=window,
            last_checked=datetime.now(timezone.utc).isoformat(),
            details={
                "total_requests": total,
                "error_count": errors,
                "measurement_period_hours": hours
            }
        )
        
        self._record_measurement(status)
        return status
    
    def check_latency_slo(self, endpoint: Optional[str] = None) -> SLOStatus:
        """Check latency SLO for p95 response times."""
        slo_config = self.slos.get('latency', {})
        
        if endpoint and endpoint in slo_config.get('endpoints', {}):
            endpoint_config = slo_config['endpoints'][endpoint]
            target = endpoint_config.get('p95_target_ms', 3000)
        else:
            target = slo_config.get('p95_target_ms', 3000)
        
        window = slo_config.get('window', '7d')
        hours = self._parse_window(window)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Build query with optional operation filter for endpoint-specific checks
        operation_filter = ""
        params = [cutoff]
        
        if endpoint:
            # Map endpoint names to operation types
            operation_map = {
                'api_general': 'api_request',
                'diagnostic_generation': 'diagnostic_generation',
                'lesson_generation': 'lesson_generation',
                'lesson_streaming': 'lesson_generation'
            }
            if endpoint in operation_map:
                operation_filter = " AND operation = ?"
                params.append(operation_map[endpoint])
        
        # Get p95 latency from performance metrics
        durations = self.db.fetchall(f"""
            SELECT duration_ms
            FROM performance_metrics
            WHERE timestamp >= ?
            AND success = 1
            {operation_filter}
            ORDER BY duration_ms
        """, tuple(params))
        
        if not durations:
            p95_latency = 0.0
        else:
            duration_list = [d['duration_ms'] for d in durations]
            p95_index = int(len(duration_list) * 0.95)
            p95_latency = duration_list[p95_index] if p95_index < len(duration_list) else duration_list[-1]
        
        is_compliant = p95_latency <= target or len(durations) == 0
        
        status = SLOStatus(
            name=f"latency_{endpoint}" if endpoint else "latency",
            target=target,
            current=round(p95_latency, 2),
            is_compliant=is_compliant,
            window=window,
            last_checked=datetime.now(timezone.utc).isoformat(),
            details={
                "p95_ms": round(p95_latency, 2),
                "sample_count": len(durations),
                "endpoint": endpoint
            }
        )
        
        self._record_measurement(status)
        return status
    
    def check_error_rate_slo(self) -> SLOStatus:
        """Check error rate SLO."""
        slo_config = self.slos.get('error_rate', {})
        target = slo_config.get('target_pct', 1.0)
        window = slo_config.get('window', '24h')
        hours = self._parse_window(window)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        row = self.db.fetchone("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as errors
            FROM performance_metrics
            WHERE timestamp >= ?
        """, (cutoff,))
        
        total = row['total'] if row and row['total'] else 0
        errors = row['errors'] if row and row['errors'] else 0
        
        if total == 0:
            error_rate = 0.0
        else:
            error_rate = (errors / total) * 100
        
        is_compliant = error_rate <= target
        
        status = SLOStatus(
            name="error_rate",
            target=target,
            current=round(error_rate, 3),
            is_compliant=is_compliant,
            window=window,
            last_checked=datetime.now(timezone.utc).isoformat(),
            details={
                "total_requests": total,
                "error_count": errors,
                "error_rate_pct": round(error_rate, 3)
            }
        )
        
        self._record_measurement(status)
        return status
    
    def check_validation_quality_slo(self) -> SLOStatus:
        """Check data quality SLO for LLM validation success rate."""
        slo_config = self.slos.get('data_quality', {})
        target = slo_config.get('validation_success_rate', 98.0)
        window = slo_config.get('window', '24h')
        hours = self._parse_window(window)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        # Count validation attempts vs failures
        row = self.db.fetchone("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN validation_failure_reason IS NOT NULL THEN 1 ELSE 0 END) as failures,
                SUM(COALESCE(validation_retry_count, 0)) as total_retries
            FROM performance_metrics
            WHERE timestamp >= ?
            AND operation IN ('diagnostic_generation', 'lesson_generation')
        """, (cutoff,))
        
        total = row['total'] if row and row['total'] else 0
        failures = row['failures'] if row and row['failures'] else 0
        retries = row['total_retries'] if row and row['total_retries'] else 0
        
        if total == 0:
            success_rate = 100.0
        else:
            success_rate = ((total - failures) / total) * 100
        
        is_compliant = success_rate >= target
        
        status = SLOStatus(
            name="validation_quality",
            target=target,
            current=round(success_rate, 2),
            is_compliant=is_compliant,
            window=window,
            last_checked=datetime.now(timezone.utc).isoformat(),
            details={
                "total_validations": total,
                "failure_count": failures,
                "total_retries": retries,
                "avg_retries_per_request": round(retries / total, 2) if total > 0 else 0
            }
        )
        
        self._record_measurement(status)
        return status
    
    def get_full_report(self) -> SLOReport:
        """Generate complete SLO compliance report."""
        statuses = []
        
        # Check all SLOs
        statuses.append(self.check_availability_slo())
        statuses.append(self.check_latency_slo())
        statuses.append(self.check_error_rate_slo())
        statuses.append(self.check_validation_quality_slo())
        
        # Check endpoint-specific latency SLOs
        endpoints = self.slos.get('latency', {}).get('endpoints', {})
        for endpoint in endpoints.keys():
            statuses.append(self.check_latency_slo(endpoint))
        
        compliant = [s for s in statuses if s.is_compliant]
        non_compliant = [s for s in statuses if not s.is_compliant]
        
        return SLOReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_compliance=len(non_compliant) == 0,
            slo_count=len(statuses),
            compliant_count=len(compliant),
            non_compliant_count=len(non_compliant),
            statuses=statuses
        )
    
    def get_slo_history(self, slo_name: str, hours: int = 168) -> List[Dict[str, Any]]:
        """Get historical SLO measurements (default: last 7 days)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        rows = self.db.fetchall("""
            SELECT 
                timestamp,
                target_value,
                measured_value,
                is_compliant,
                details
            FROM slo_measurements
            WHERE slo_name = ?
            AND timestamp >= ?
            ORDER BY timestamp DESC
        """, (slo_name, cutoff))
        
        return [dict(row) for row in rows]
    
    def _record_measurement(self, status: SLOStatus):
        """Record an SLO measurement."""
        import json
        
        self.db.execute("""
            INSERT INTO slo_measurements
            (timestamp, slo_name, target_value, measured_value, is_compliant, 
             window_hours, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            status.last_checked,
            status.name,
            status.target,
            status.current,
            1 if status.is_compliant else 0,
            self._parse_window(status.window),
            json.dumps(status.details)
        ))
    
    def _parse_window(self, window: str) -> int:
        """Parse window string (e.g., '7d', '24h') to hours."""
        if window.endswith('d'):
            return int(window[:-1]) * 24
        elif window.endswith('h'):
            return int(window[:-1])
        elif window.endswith('m'):
            return int(window[:-1]) // 60
        else:
            return 24  # Default to 24 hours


