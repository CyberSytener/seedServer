"""
Durable Storage for Pending Confirmations and Audit Trail

Uses Postgres for:
- Pending confirmations (survives restarts)
- Audit trail (append-only, immutable)
- PII redaction
"""

import json
import logging
from typing import Any, Dict, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
from enum import Enum
import uuid

logger = logging.getLogger(__name__)

# SQL Schema (execute once on startup)
MIGRATIONS_SQL = """
-- Distributed Idempotency Cache (backup for Redis failures)
CREATE TABLE IF NOT EXISTS action_idempotency (
    action_id uuid PRIMARY KEY,
    user_id uuid,
    result jsonb,
    error text,
    created_at timestamptz DEFAULT now(),
    expires_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON action_idempotency(expires_at);

-- Pending Confirmations (durable, survives restarts)
CREATE TABLE IF NOT EXISTS pending_actions (
    action_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    action_name text NOT NULL,
    params jsonb NOT NULL,
    human_readable text,
    created_at timestamptz DEFAULT now(),
    expires_at timestamptz NOT NULL,
    status text DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'rejected', 'expired', 'cancelled')),
    rejection_reason text
);
CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_actions(user_id);
CREATE INDEX IF NOT EXISTS idx_pending_expires ON pending_actions(expires_at);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_actions(status);

-- Audit Trail (append-only, immutable)
CREATE TABLE IF NOT EXISTS action_audit (
    id bigserial PRIMARY KEY,
    action_id uuid NOT NULL,
    user_id uuid,
    action_name text NOT NULL,
    params_redacted jsonb,
    result jsonb,
    status text NOT NULL,
    trace_id text,
    source text,  -- 'mock' | 'adapter' | 'provider'
    error_message text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_action_id ON action_audit(action_id);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON action_audit(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON action_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_trace_id ON action_audit(trace_id);
"""


class ActionStatus(Enum):
    """Action execution status"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PendingActionStore:
    """Durable storage for pending confirmations"""
    
    def __init__(self, db_pool):
        """
        Args:
            db_pool: asyncpg or psycopg2 connection pool
        """
        self.db = db_pool
    
    async def store_pending(
        self,
        action_id: str,
        user_id: str,
        action_name: str,
        params: Dict[str, Any],
        human_readable: str,
        ttl_seconds: int = 3600
    ) -> bool:
        """Store pending confirmation (awaiting user approval)"""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        
        try:
            async with self.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO pending_actions 
                    (action_id, user_id, action_name, params, human_readable, expires_at, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (action_id) DO NOTHING
                """, 
                    uuid.UUID(action_id), 
                    uuid.UUID(user_id),
                    action_name,
                    json.dumps(params),
                    human_readable,
                    expires_at,
                    ActionStatus.PENDING.value
                )
            logger.info(f"Stored pending action: {action_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store pending action: {e}")
            return False
    
    async def get_pending(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve pending action"""
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT action_id, user_id, action_name, params, human_readable, 
                           created_at, expires_at, status
                    FROM pending_actions
                    WHERE action_id = $1
                """, uuid.UUID(action_id))
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Failed to get pending action: {e}")
            return None
    
    async def mark_confirmed(self, action_id: str) -> bool:
        """Mark action as confirmed by user"""
        try:
            async with self.db.acquire() as conn:
                result = await conn.execute("""
                    UPDATE pending_actions
                    SET status = $1
                    WHERE action_id = $2 AND status = $3
                """, ActionStatus.CONFIRMED.value, uuid.UUID(action_id), ActionStatus.PENDING.value)
            logger.info(f"Marked confirmed: {action_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to mark confirmed: {e}")
            return False
    
    async def mark_rejected(self, action_id: str, reason: str = "") -> bool:
        """Mark action as rejected by user"""
        try:
            async with self.db.acquire() as conn:
                await conn.execute("""
                    UPDATE pending_actions
                    SET status = $1, rejection_reason = $2
                    WHERE action_id = $3
                """, ActionStatus.REJECTED.value, reason, uuid.UUID(action_id))
            logger.info(f"Marked rejected: {action_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to mark rejected: {e}")
            return False
    
    async def cleanup_expired(self) -> int:
        """Remove expired pending actions"""
        try:
            async with self.db.acquire() as conn:
                result = await conn.execute("""
                    UPDATE pending_actions
                    SET status = $1
                    WHERE expires_at < now() AND status = $2
                """, ActionStatus.EXPIRED.value, ActionStatus.PENDING.value)
            count = int(result.split()[-1])
            logger.info(f"Cleaned up {count} expired pending actions")
            return count
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return 0
    
    async def get_pending_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all pending actions for user"""
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT action_id, user_id, action_name, params, human_readable,
                           created_at, expires_at, status
                    FROM pending_actions
                    WHERE user_id = $1 AND status = $2
                    ORDER BY created_at DESC
                """, uuid.UUID(user_id), ActionStatus.PENDING.value)
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get pending for user: {e}")
            return []


class AuditTrailStore:
    """Durable append-only audit trail"""
    
    def __init__(self, db_pool):
        """
        Args:
            db_pool: asyncpg or psycopg2 connection pool
        """
        self.db = db_pool
    
    @staticmethod
    def _redact_pii(params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove PII from params for audit logging"""
        redacted = params.copy()
        
        # Fields to redact
        pii_fields = ['password', 'api_key', 'secret', 'credit_card', 'ssn', 'phone', 'email']
        
        for field in pii_fields:
            if field in redacted:
                redacted[field] = "***REDACTED***"
        
        # Redact nested objects
        for key, value in redacted.items():
            if isinstance(value, dict):
                redacted[key] = AuditTrailStore._redact_pii(value)
        
        return redacted
    
    async def record_action(
        self,
        action_id: str,
        user_id: str,
        action_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
        status: str,
        trace_id: str = None,
        source: str = "mock",
        error_message: str = None
    ) -> bool:
        """Record action execution in audit trail (INSERT only, no UPDATE)"""
        try:
            params_redacted = self._redact_pii(params)
            
            async with self.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO action_audit 
                    (action_id, user_id, action_name, params_redacted, result, status, trace_id, source, error_message)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                    uuid.UUID(action_id) if action_id else None,
                    uuid.UUID(user_id) if user_id else None,
                    action_name,
                    json.dumps(params_redacted),
                    json.dumps(result),
                    status,
                    trace_id,
                    source,
                    error_message
                )
            logger.info(f"Recorded audit: {action_name} → {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to record audit: {e}")
            return False
    
    async def get_audit_trail(
        self,
        action_id: str = None,
        user_id: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Retrieve audit trail (read-only)"""
        try:
            query = "SELECT * FROM action_audit WHERE 1=1"
            params = []
            
            if action_id:
                query += f" AND action_id = ${len(params) + 1}"
                params.append(uuid.UUID(action_id))
            
            if user_id:
                query += f" AND user_id = ${len(params) + 1}"
                params.append(uuid.UUID(user_id))
            
            query += f" ORDER BY created_at DESC LIMIT {limit}"
            
            async with self.db.acquire() as conn:
                rows = await conn.fetch(query, *params)
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to retrieve audit trail: {e}")
            return []
