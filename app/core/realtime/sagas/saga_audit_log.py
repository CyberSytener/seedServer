"""
Audit logging for Saga Orchestrator operations.
Tracks all important saga operations for compliance and debugging.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
import json
import logging

logger = logging.getLogger(__name__)


class SagaAuditEvent(str, Enum):
    """Saga operations that are audited."""
    SAGA_STARTED = "saga_started"
    SAGA_SUCCEEDED = "saga_succeeded"
    SAGA_FAILED = "saga_failed"
    SAGA_RESUMED = "saga_resumed"
    SAGA_PAUSED = "saga_paused"
    SAGA_CANCELLED = "saga_cancelled"
    SAGA_COMPENSATED = "saga_compensated"
    STEP_EXECUTED = "step_executed"
    STEP_FAILED = "step_failed"
    COMPENSATION_EXECUTED = "compensation_executed"
    CIRCUIT_BREAKER_OPENED = "circuit_breaker_opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"
    DLQ_ITEM_ADDED = "dlq_item_added"
    DLQ_ITEM_RETRIED = "dlq_item_retried"
    ADAPTER_CALLED = "adapter_called"
    ADAPTER_ERROR = "adapter_error"
    AUTHORIZATION_DENIED = "authorization_denied"
    AUTHORIZATION_GRANTED = "authorization_granted"


class SagaAuditLevel(str, Enum):
    """Audit event severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class SagaAuditRecord:
    """Represents an audit log entry."""
    timestamp: datetime
    event_type: SagaAuditEvent
    level: SagaAuditLevel
    user_id: str
    username: str
    saga_id: str
    step_name: Optional[str] = None
    adapter_name: Optional[str] = None
    status: str = "success"
    details: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    request_id: Optional[str] = None
    ip_address: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["event_type"] = self.event_type.value
        data["level"] = self.level.value
        return data
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


class SagaAuditLogger:
    """Logs audit events for saga operations."""
    
    def __init__(self, max_records: int = 10000):
        """
        Initialize audit logger.
        
        Args:
            max_records: Maximum records to keep in memory
        """
        self.records: List[SagaAuditRecord] = []
        self.max_records = max_records
        self.file_logger: Optional[logging.FileHandler] = None
    
    def log_event(
        self,
        event_type: SagaAuditEvent,
        user_id: str,
        username: str,
        saga_id: str,
        level: SagaAuditLevel = SagaAuditLevel.INFO,
        step_name: Optional[str] = None,
        adapter_name: Optional[str] = None,
        status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        request_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> SagaAuditRecord:
        """
        Log an audit event.
        
        Args:
            event_type: Type of event
            user_id: ID of user performing action
            username: Username of user
            saga_id: Saga ID involved
            level: Severity level
            step_name: Saga step name (if applicable)
            adapter_name: Adapter name (if applicable)
            status: Operation status (success/failure)
            details: Additional details dictionary
            error_message: Error message if failed
            request_id: Correlated request ID
            ip_address: Client IP address
        
        Returns:
            The created audit record
        """
        record = SagaAuditRecord(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            level=level,
            user_id=user_id,
            username=username,
            saga_id=saga_id,
            step_name=step_name,
            adapter_name=adapter_name,
            status=status,
            details=details or {},
            error_message=error_message,
            request_id=request_id,
            ip_address=ip_address,
        )
        
        # Add to records
        self.records.append(record)
        
        # Trim if exceeds max
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]
        
        # Log to file if configured
        if self.file_logger:
            logger.info(f"AUDIT: {record.to_json()}")
        
        # Log warning/error if needed
        if level == SagaAuditLevel.WARNING:
            logger.warning(f"[AUDIT] {event_type.value}: {saga_id} by {username}")
        elif level in (SagaAuditLevel.ERROR, SagaAuditLevel.CRITICAL):
            logger.error(f"[AUDIT] {event_type.value}: {saga_id} by {username} - {error_message}")
        else:
            logger.debug(f"[AUDIT] {event_type.value}: {saga_id} by {username}")
        
        return record
    
    def get_saga_history(
        self,
        saga_id: str,
        limit: Optional[int] = None,
    ) -> List[SagaAuditRecord]:
        """Get audit history for a saga."""
        saga_records = [r for r in self.records if r.saga_id == saga_id]
        
        if limit:
            saga_records = saga_records[-limit:]
        
        return saga_records
    
    def get_user_activity(
        self,
        user_id: str,
        limit: Optional[int] = 100,
    ) -> List[SagaAuditRecord]:
        """Get audit records for a user."""
        user_records = [r for r in self.records if r.user_id == user_id]
        
        if limit:
            user_records = user_records[-limit:]
        
        return user_records
    
    def get_recent_events(
        self,
        event_type: Optional[SagaAuditEvent] = None,
        limit: int = 100,
    ) -> List[SagaAuditRecord]:
        """Get recent events."""
        events = self.records
        
        if event_type:
            events = [r for r in events if r.event_type == event_type]
        
        return events[-limit:]
    
    def get_failed_operations(self, limit: int = 100) -> List[SagaAuditRecord]:
        """Get failed operations."""
        failed = [r for r in self.records if r.status != "success"]
        return failed[-limit:]
    
    def get_unauthorized_attempts(self, limit: int = 100) -> List[SagaAuditRecord]:
        """Get unauthorized access attempts."""
        attempts = [
            r for r in self.records
            if r.event_type == SagaAuditEvent.AUTHORIZATION_DENIED
        ]
        return attempts[-limit:]
    
    def get_summary(self) -> dict:
        """Get audit summary statistics."""
        total = len(self.records)
        
        # Count by event type
        event_counts = {}
        for record in self.records:
            event_key = record.event_type.value
            event_counts[event_key] = event_counts.get(event_key, 0) + 1
        
        # Count by level
        level_counts = {}
        for record in self.records:
            level_key = record.level.value
            level_counts[level_key] = level_counts.get(level_key, 0) + 1
        
        # Count failures
        failures = sum(1 for r in self.records if r.status != "success")
        
        # Unique sagas
        unique_sagas = len(set(r.saga_id for r in self.records))
        
        # Unique users
        unique_users = len(set(r.user_id for r in self.records))
        
        return {
            "total_records": total,
            "failures": failures,
            "failure_rate": (failures / total * 100) if total > 0 else 0,
            "unique_sagas": unique_sagas,
            "unique_users": unique_users,
            "event_types": event_counts,
            "levels": level_counts,
        }
    
    def export_json(self, saga_id: Optional[str] = None) -> str:
        """Export audit records as JSON."""
        records = self.records
        if saga_id:
            records = [r for r in records if r.saga_id == saga_id]
        
        return json.dumps([r.to_dict() for r in records], indent=2, default=str)
    
    def enable_file_logging(self, filepath: str) -> None:
        """Enable logging to file."""
        self.file_logger = logging.FileHandler(filepath)
        logger.info(f"File audit logging enabled: {filepath}")
    
    def clear_history(self, saga_id: Optional[str] = None) -> int:
        """Clear audit history."""
        if saga_id:
            original_count = len(self.records)
            self.records = [r for r in self.records if r.saga_id != saga_id]
            removed = original_count - len(self.records)
            logger.warning(f"Cleared {removed} audit records for saga {saga_id}")
            return removed
        else:
            count = len(self.records)
            self.records.clear()
            logger.warning(f"Cleared all {count} audit records")
            return count


# Global audit logger instance
_audit_logger: Optional[SagaAuditLogger] = None


def get_audit_logger() -> SagaAuditLogger:
    """Get or create global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = SagaAuditLogger()
    return _audit_logger


def audit_log(
    event_type: SagaAuditEvent,
    user_id: str,
    username: str,
    saga_id: str,
    **kwargs
) -> SagaAuditRecord:
    """
    Log an audit event using the global logger.
    
    Convenience function for quick audit logging.
    """
    logger_instance = get_audit_logger()
    return logger_instance.log_event(
        event_type=event_type,
        user_id=user_id,
        username=username,
        saga_id=saga_id,
        **kwargs
    )
