"""
Dead Letter Queue (DLQ) for Saga Orchestrator.

Handles sagas that permanently fail and require manual intervention.
"""

import logging
import json
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


# =========================================================================
# DLQ Message Types
# =========================================================================

class DLQMessageType(str, Enum):
    """Type of DLQ message."""
    PERMANENT_FAILURE = "permanent_failure"
    COMPENSATION_FAILED = "compensation_failed"
    TIMEOUT_NO_RESPONSE = "timeout_no_response"
    LOCK_TIMEOUT = "lock_timeout"
    ADAPTER_CIRCUIT_OPEN = "adapter_circuit_open"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class DLQMessage:
    """Message in the dead letter queue."""
    
    # Core saga data
    saga_id: str
    action_id: str
    correlation_id: str
    flow_name: str
    
    # Failure info
    message_type: DLQMessageType
    error_message: str
    error_type: str
    
    # Saga state at failure
    last_successful_step: str
    failed_step: str
    saga_state: Dict[str, Any] = field(default_factory=dict)
    attempted_compensation_steps: List[str] = field(default_factory=list)
    
    # Timing
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    saga_duration_ms: float = 0
    
    # Retry info
    retry_count: int = 0
    last_retry_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    
    # Metadata
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


# =========================================================================
# Dead Letter Queue
# =========================================================================

class DeadLetterQueue:
    """In-memory DLQ for failed sagas (suitable for single instance)."""
    
    def __init__(self, max_size: int = 10000):
        self.messages: List[DLQMessage] = []
        self.max_size = max_size
        self.processed_count = 0
    
    # =====================================================================
    # Message Management
    # =====================================================================
    
    def add_message(self, message: DLQMessage) -> str:
        """
        Add a message to DLQ.
        
        Args:
            message: DLQ message
        
        Returns:
            Message ID (saga_id)
        """
        if len(self.messages) >= self.max_size:
            # Remove oldest message
            old_msg = self.messages.pop(0)
            logger.warning(
                f"⚠️  DLQ full, removing oldest message: {old_msg.saga_id} "
                f"(created: {old_msg.created_at})"
            )
        
        self.messages.append(message)
        
        logger.error(
            f"❌ Saga moved to DLQ: {message.saga_id}\n"
            f"   Type: {message.message_type}\n"
            f"   Error: {message.error_message}\n"
            f"   Last step: {message.last_successful_step}\n"
            f"   Failed step: {message.failed_step}"
        )
        
        return message.saga_id
    
    def get_message(self, saga_id: str) -> Optional[DLQMessage]:
        """Get a specific DLQ message."""
        for msg in self.messages:
            if msg.saga_id == saga_id:
                return msg
        return None
    
    def remove_message(self, saga_id: str) -> bool:
        """
        Remove a message from DLQ (after manual resolution).
        
        Args:
            saga_id: Saga ID to remove
        
        Returns:
            True if removed, False if not found
        """
        for i, msg in enumerate(self.messages):
            if msg.saga_id == saga_id:
                self.messages.pop(i)
                self.processed_count += 1
                logger.info(f"✅ DLQ message processed: {saga_id}")
                return True
        return False
    
    def retry_message(self, saga_id: str) -> Optional[DLQMessage]:
        """
        Mark message for retry and return it for reprocessing.
        
        Args:
            saga_id: Saga ID to retry
        
        Returns:
            Updated message, or None if not found
        """
        msg = self.get_message(saga_id)
        if not msg:
            return None
        
        msg.retry_count += 1
        msg.last_retry_at = datetime.now(timezone.utc).isoformat()
        
        # Calculate next retry (exponential backoff: 5min, 15min, 1h, 4h...)
        retry_delays = [300, 900, 3600, 14400]  # seconds
        delay_seconds = retry_delays[min(msg.retry_count - 1, len(retry_delays) - 1)]
        
        next_retry = datetime.now(timezone.utc).replace(microsecond=0)
        
        msg.next_retry_at = (next_retry).isoformat()
        
        logger.info(
            f"🔄 DLQ message marked for retry: {saga_id}\n"
            f"   Retry count: {msg.retry_count}\n"
            f"   Next retry at: {msg.next_retry_at}"
        )
        
        return msg
    
    # =====================================================================
    # Querying
    # =====================================================================
    
    def get_all_messages(self) -> List[DLQMessage]:
        """Get all messages in DLQ."""
        return self.messages.copy()
    
    def get_messages_by_type(self, message_type: DLQMessageType) -> List[DLQMessage]:
        """Get messages of specific type."""
        return [msg for msg in self.messages if msg.message_type == message_type]
    
    def get_messages_by_flow(self, flow_name: str) -> List[DLQMessage]:
        """Get messages for specific flow."""
        return [msg for msg in self.messages if msg.flow_name == flow_name]
    
    def get_pending_retries(self) -> List[DLQMessage]:
        """Get messages pending retry."""
        current_time = datetime.now(timezone.utc).isoformat()
        return [
            msg for msg in self.messages
            if msg.next_retry_at and msg.next_retry_at <= current_time
        ]
    
    def get_recent_messages(self, limit: int = 100) -> List[DLQMessage]:
        """Get most recent DLQ messages."""
        return self.messages[-limit:]
    
    # =====================================================================
    # Statistics
    # =====================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get DLQ statistics."""
        type_counts = {}
        for msg in self.messages:
            msg_type = msg.message_type.value
            type_counts[msg_type] = type_counts.get(msg_type, 0) + 1
        
        flow_counts = {}
        for msg in self.messages:
            flow_counts[msg.flow_name] = flow_counts.get(msg.flow_name, 0) + 1
        
        pending_retries = len(self.get_pending_retries())
        
        return {
            "total_messages": len(self.messages),
            "queue_utilization_percent": (len(self.messages) / self.max_size * 100),
            "processed_count": self.processed_count,
            "messages_by_type": type_counts,
            "messages_by_flow": flow_counts,
            "pending_retries": pending_retries,
            "max_size": self.max_size,
        }
    
    # =====================================================================
    # Export and Reporting
    # =====================================================================
    
    def export_to_json(self, saga_id: Optional[str] = None) -> str:
        """
        Export DLQ messages to JSON.
        
        Args:
            saga_id: Optional specific saga to export, or all if None
        
        Returns:
            JSON string
        """
        if saga_id:
            msg = self.get_message(saga_id)
            messages = [msg] if msg else []
        else:
            messages = self.messages
        
        data = [asdict(msg) for msg in messages]
        return json.dumps(data, indent=2, default=str)
    
    def generate_report(self) -> str:
        """Generate DLQ report for monitoring."""
        stats = self.get_stats()
        
        report = [
            "\n" + "="*70,
            "DEAD LETTER QUEUE REPORT",
            "="*70,
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
            f"Total messages: {stats['total_messages']}/{stats['max_size']}",
            f"Queue utilization: {stats['queue_utilization_percent']:.1f}%",
            f"Processed (resolved): {stats['processed_count']}",
            f"Pending retries: {stats['pending_retries']}",
            "",
            "MESSAGES BY TYPE:",
        ]
        
        for msg_type, count in stats['messages_by_type'].items():
            report.append(f"  {msg_type}: {count}")
        
        report.append("")
        report.append("MESSAGES BY FLOW:")
        for flow_name, count in stats['messages_by_flow'].items():
            report.append(f"  {flow_name}: {count}")
        
        report.append("")
        report.append("RECENT MESSAGES:")
        for msg in self.get_recent_messages(limit=5):
            report.append(
                f"  {msg.saga_id} ({msg.message_type.value}): {msg.error_message[:50]}"
            )
        
        report.append("="*70 + "\n")
        
        return "\n".join(report)
