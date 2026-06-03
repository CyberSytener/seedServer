"""
Database migrations for STEP 4: Saga Orchestration

Adds tables for:
- saga orchestration records
- adapter execution logs
- compensation history
"""

STEP4_MIGRATIONS = """

-- Saga orchestration table
CREATE TABLE IF NOT EXISTS sagas (
    saga_id UUID PRIMARY KEY,
    action_id UUID NOT NULL,
    user_id UUID,
    saga_type TEXT NOT NULL,                  -- e.g., "booking_flow", "calendar_event", "payment_flow"
    saga_version TEXT NOT NULL DEFAULT 'v1',  -- version of saga definition
    state TEXT NOT NULL,                      -- "pending", "in_progress", "waiting_confirm", "succeeded", "failed", "compensating", "compensated"
    payload JSONB NOT NULL,                   -- input parameters / context
    steps JSONB DEFAULT '[]'::jsonb,          -- list of step records [{name, status, meta, timestamp}]
    result JSONB,                             -- final result or error details
    compensation_meta JSONB,                  -- track compensations attempted
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ                    -- auto-cleanup for old sagas
);

CREATE INDEX idx_sagas_action_id ON sagas (action_id);
CREATE INDEX idx_sagas_user_id ON sagas (user_id);
CREATE INDEX idx_sagas_state ON sagas (state);
CREATE INDEX idx_sagas_saga_type ON sagas (saga_type);
CREATE INDEX idx_sagas_saga_type_version ON sagas (saga_type, saga_version);
CREATE INDEX idx_sagas_created_at ON sagas (created_at DESC);
CREATE INDEX idx_sagas_expires_at ON sagas (expires_at);

-- Add saga_version column for existing installations
ALTER TABLE IF EXISTS sagas
    ADD COLUMN IF NOT EXISTS saga_version TEXT DEFAULT 'v1';

-- Adapter execution log (for observability)
CREATE TABLE IF NOT EXISTS adapter_executions (
    execution_id UUID PRIMARY KEY,
    saga_id UUID NOT NULL REFERENCES sagas(saga_id) ON DELETE CASCADE,
    adapter_type TEXT NOT NULL,               -- "booking", "calendar", "payment", etc.
    operation TEXT NOT NULL,                  -- "reserve", "confirm", "compensate"
    status TEXT NOT NULL,                     -- "pending", "in_progress", "succeeded", "failed"
    input JSONB,
    output JSONB,
    error_message TEXT,
    duration_ms INT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_adapter_exec_saga_id ON adapter_executions (saga_id);
CREATE INDEX idx_adapter_exec_adapter_type ON adapter_executions (adapter_type);
CREATE INDEX idx_adapter_exec_status ON adapter_executions (status);

-- Compensation history (for audit)
CREATE TABLE IF NOT EXISTS compensation_history (
    compensation_id UUID PRIMARY KEY,
    saga_id UUID NOT NULL REFERENCES sagas(saga_id) ON DELETE CASCADE,
    original_operation TEXT NOT NULL,         -- e.g., "booking.confirm"
    compensation_operation TEXT NOT NULL,     -- e.g., "booking.cancel"
    original_result JSONB,
    compensation_result JSONB,
    reason TEXT,                              -- "confirm_failed", "user_cancelled", etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_compensation_saga_id ON compensation_history (saga_id);

-- Cleanup function: remove old completed/failed sagas (retention policy)
CREATE OR REPLACE FUNCTION cleanup_old_sagas(days_retention INT DEFAULT 90)
RETURNS INT AS $$
DECLARE
    deleted_count INT;
BEGIN
    DELETE FROM sagas
    WHERE state IN ('succeeded', 'compensated', 'failed')
    AND created_at < NOW() - (days_retention || ' days')::INTERVAL;
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- View: Current active sagas (not yet completed)
CREATE OR REPLACE VIEW active_sagas AS
SELECT 
    saga_id,
    action_id,
    user_id,
    saga_type,
    state,
    created_at,
    updated_at,
    (updated_at - created_at) as duration
FROM sagas
WHERE state NOT IN ('succeeded', 'compensated', 'failed');

-- View: Saga summary (for monitoring)
CREATE OR REPLACE VIEW saga_summary AS
SELECT
    saga_type,
    state,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_duration_sec,
    MAX(updated_at) as last_updated
FROM sagas
WHERE created_at > NOW() - '7 days'::INTERVAL
GROUP BY saga_type, state;
"""
