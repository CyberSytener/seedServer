-- Migration: Add correlation_id column to sagas table for distributed tracing
-- Created: 2024
-- Purpose: Enable distributed tracing across saga operations

-- Add correlation_id column for distributed tracing
ALTER TABLE sagas 
ADD COLUMN IF NOT EXISTS correlation_id UUID;

-- Create index for correlation_id lookups
CREATE INDEX IF NOT EXISTS idx_sagas_correlation_id 
ON sagas(correlation_id);

-- Add comment for documentation
COMMENT ON COLUMN sagas.correlation_id IS 'Distributed tracing correlation ID for tracking saga across services';
