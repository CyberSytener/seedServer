"""
API Key management functions for revocation, rotation, and auditing.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from app.infrastructure.db.sqlite import DB
from app.core.auth import issue_key_for_user, _hash_key


def revoke_api_key(db: DB, user_id: str, reason: str, revoked_by: str) -> bool:
    """
    Revoke user's API key.
    
    Args:
        db: Database instance
        user_id: User whose key to revoke
        reason: Reason for revocation (for audit)
        revoked_by: Admin user performing revocation
        
    Returns:
        True if key was revoked, False if user not found
    """
    row = db.fetchone("SELECT api_key_hash, api_key_last4 FROM users WHERE id = ?", (user_id,))
    if not row:
        return False
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Clear API key from user record
    db.execute(
        "UPDATE users SET api_key_hash = NULL, api_key_last4 = NULL WHERE id = ?",
        (user_id,)
    )
    
    # Log revocation for audit
    db.execute("""
        INSERT INTO key_revocations (user_id, key_last4, reason, revoked_by, revoked_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, row["api_key_last4"], reason, revoked_by, now))
    
    logging.warning(
        "API key revoked",
        extra={
            "user_id": user_id,
            "key_last4": row["api_key_last4"],
            "reason": reason,
            "revoked_by": revoked_by
        }
    )
    
    return True


def rotate_api_key(db: DB, user_id: str, rotated_by: str) -> Optional[str]:
    """
    Rotate user's API key (revoke old, issue new).
    
    Args:
        db: Database instance
        user_id: User whose key to rotate
        rotated_by: User performing rotation (can be self or admin)
        
    Returns:
        New API key if successful, None if user not found
    """
    row = db.fetchone("SELECT id, api_key_last4 FROM users WHERE id = ?", (user_id,))
    if not row:
        return None
    
    old_last4 = row["api_key_last4"]
    
    # Issue new key (this will overwrite the old one)
    new_key = issue_key_for_user(db, user_id)
    
    # Log rotation for audit
    now = datetime.now(timezone.utc).isoformat()
    db.execute("""
        INSERT INTO key_rotations (user_id, old_key_last4, new_key_last4, rotated_by, rotated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, old_last4, new_key[-4:], rotated_by, now))
    
    logging.info(
        "API key rotated",
        extra={
            "user_id": user_id,
            "old_key_last4": old_last4,
            "new_key_last4": new_key[-4:],
            "rotated_by": rotated_by
        }
    )
    
    return new_key


def get_key_audit_log(db: DB, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get audit log of key operations for a user.
    
    Returns list of revocations and rotations.
    """
    revocations = db.fetchall("""
        SELECT 'revocation' as event_type, user_id, key_last4, reason, revoked_by as actor, revoked_at as timestamp
        FROM key_revocations
        WHERE user_id = ?
        ORDER BY revoked_at DESC
        LIMIT ?
    """, (user_id, limit))
    
    rotations = db.fetchall("""
        SELECT 'rotation' as event_type, user_id, old_key_last4, new_key_last4, rotated_by as actor, rotated_at as timestamp
        FROM key_rotations
        WHERE user_id = ?
        ORDER BY rotated_at DESC
        LIMIT ?
    """, (user_id, limit))
    
    # Combine and sort by timestamp
    events = []
    for row in revocations:
        events.append({
            "event_type": "revocation",
            "user_id": row["user_id"],
            "key_last4": row["key_last4"] or "",
            "reason": row["reason"] or "",
            "actor": row["actor"] or "",
            "timestamp": row["timestamp"]
        })
    
    for row in rotations:
        events.append({
            "event_type": "rotation",
            "user_id": row["user_id"],
            "old_key_last4": row["old_key_last4"] or "",
            "new_key_last4": row["new_key_last4"] or "",
            "actor": row["actor"] or "",
            "timestamp": row["timestamp"]
        })
    
    # Sort by timestamp descending
    events.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return events[:limit]


def ensure_key_audit_tables(db: DB):
    """Create audit tables for key management."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS key_revocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            key_last4 TEXT,
            reason TEXT,
            revoked_by TEXT NOT NULL,
            revoked_at TEXT NOT NULL
        )
    """)
    
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_key_revocations_user 
        ON key_revocations(user_id, revoked_at DESC)
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS key_rotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            old_key_last4 TEXT,
            new_key_last4 TEXT NOT NULL,
            rotated_by TEXT NOT NULL,
            rotated_at TEXT NOT NULL
        )
    """)
    
    db.execute("""
        CREATE INDEX IF NOT EXISTS idx_key_rotations_user 
        ON key_rotations(user_id, rotated_at DESC)
    """)


