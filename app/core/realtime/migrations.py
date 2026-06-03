"""
Database Migrations for Production Idempotency & Audit Trail

Run once on startup or during deployment:
    psql -U postgres -d seed_server -f migrations.sql

Or via Python:
    from app.core.interfaces.database import AsyncDatabaseProtocol, DatabaseProtocol
    from app.core.realtime.postgres_stores import MIGRATIONS_SQL
    execute_migrations()
"""

# SQL migration script
MIGRATIONS_SQL = """
-- ============================================================================
-- Action Idempotency Cache (Postgres fallback for Redis)
-- ============================================================================

CREATE TABLE IF NOT EXISTS action_idempotency (
    action_id uuid PRIMARY KEY,
    user_id uuid,
    result jsonb,
    error text,
    created_at timestamptz DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_expires 
    ON action_idempotency(expires_at)
    WHERE expires_at > now();

CREATE INDEX IF NOT EXISTS idx_idempotency_user 
    ON action_idempotency(user_id);


-- ============================================================================
-- Pending Confirmations (Durable, survives restarts)
-- ============================================================================

CREATE TABLE IF NOT EXISTS pending_actions (
    action_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    action_name text NOT NULL,
    params jsonb NOT NULL,
    human_readable text,
    created_at timestamptz DEFAULT now(),
    expires_at timestamptz NOT NULL,
    status text DEFAULT 'pending' CHECK (
        status IN ('pending', 'confirmed', 'rejected', 'expired', 'cancelled')
    ),
    rejection_reason text,
    
    CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_pending_user 
    ON pending_actions(user_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_pending_expires 
    ON pending_actions(expires_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_pending_status 
    ON pending_actions(status);

CREATE INDEX IF NOT EXISTS idx_pending_action_name 
    ON pending_actions(action_name);


-- ============================================================================
-- Audit Trail (Append-only, immutable, NEVER UPDATE)
-- ============================================================================

CREATE TABLE IF NOT EXISTS action_audit (
    id bigserial PRIMARY KEY,
    
    -- Action Identification
    action_id uuid,
    user_id uuid,
    action_name text NOT NULL,
    trace_id text,
    
    -- Execution Details
    params_redacted jsonb,       -- PII removed
    result jsonb,
    status text NOT NULL CHECK (
        status IN ('success', 'failed', 'requires_manual_review', 'pending')
    ),
    error_message text,
    
    -- Source Tracking
    source text CHECK (source IN ('mock', 'adapter', 'provider')),
    
    -- Timestamps (never updated)
    created_at timestamptz DEFAULT now()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_audit_action_id 
    ON action_audit(action_id);

CREATE INDEX IF NOT EXISTS idx_audit_user_id 
    ON action_audit(user_id);

CREATE INDEX IF NOT EXISTS idx_audit_created 
    ON action_audit(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_trace_id 
    ON action_audit(trace_id);

CREATE INDEX IF NOT EXISTS idx_audit_action_name 
    ON action_audit(action_name);

-- Prevent updates (audit trail is immutable)
CREATE OR REPLACE RULE prevent_audit_update AS ON UPDATE TO action_audit
    DO INSTEAD NOTHING;

CREATE OR REPLACE RULE prevent_audit_delete AS ON DELETE TO action_audit
    DO INSTEAD NOTHING;


-- ============================================================================
-- Cleanup Jobs (manual or scheduled via pg_cron)
-- ============================================================================

-- Cleanup expired pending actions (manual trigger)
CREATE OR REPLACE FUNCTION cleanup_expired_pending() RETURNS int AS $$
DECLARE
    deleted_count int;
BEGIN
    UPDATE pending_actions
    SET status = 'expired'
    WHERE expires_at < now() AND status = 'pending';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;


-- Cleanup expired idempotency cache (manual trigger)
CREATE OR REPLACE FUNCTION cleanup_expired_idempotency() RETURNS int AS $$
DECLARE
    deleted_count int;
BEGIN
    DELETE FROM action_idempotency
    WHERE expires_at < now();
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- Views for Operations
-- ============================================================================

-- Current pending actions (not expired)
CREATE OR REPLACE VIEW pending_actions_current AS
SELECT 
    action_id,
    user_id,
    action_name,
    human_readable,
    created_at,
    expires_at,
    age(expires_at, now()) as time_remaining
FROM pending_actions
WHERE status = 'pending' AND expires_at > now()
ORDER BY created_at DESC;


-- Audit summary by action
CREATE OR REPLACE VIEW audit_summary AS
SELECT 
    action_name,
    status,
    COUNT(*) as count,
    COUNT(CASE WHEN status = 'success' THEN 1 END)::float / COUNT(*) as success_rate,
    MIN(created_at) as first_execution,
    MAX(created_at) as last_execution
FROM action_audit
GROUP BY action_name, status;


-- ============================================================================
-- Retention Policies (manual cleanup, or via pg_partman)
-- ============================================================================

-- Audit trail retention: keep 90 days (configurable)
-- To remove old audit entries (run manually or scheduled):
-- DELETE FROM action_audit WHERE created_at < now() - interval '90 days';

-- Idempotency cache retention: keep 24 hours (should be handled by Redis TTL)
-- DELETE FROM action_idempotency WHERE expires_at < now();

-- Pending actions: cleanup expired on startup
-- SELECT cleanup_expired_pending();


-- ============================================================================
-- Grants (if needed for multi-user access)
-- ============================================================================

-- GRANT SELECT, INSERT ON action_audit TO app_user;
-- GRANT SELECT, INSERT, UPDATE ON pending_actions TO app_user;
-- GRANT SELECT, INSERT, UPDATE ON action_idempotency TO app_user;

"""


def execute_migrations(db: DatabaseProtocol) -> None:
    """Execute migrations using a sync database adapter."""
    db.execute(MIGRATIONS_SQL)


async def execute_migrations_async(db: AsyncDatabaseProtocol) -> None:
    """Execute migrations using an async database adapter."""
    await db.execute(MIGRATIONS_SQL)


if __name__ == "__main__":
    raise SystemExit("Use infrastructure adapters to run migrations from the application startup.")

