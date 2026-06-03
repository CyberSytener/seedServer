"""
Alembic migration: Create saga orchestration tables

Generated: 2026-02-12
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "saga_tables_001"
down_revision = "inventory_ledger_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sagas (
            saga_id uuid PRIMARY KEY,
            action_id uuid NOT NULL,
            user_id uuid,
            saga_type text NOT NULL,
            saga_version text NOT NULL DEFAULT 'v1',
            state text NOT NULL,
            payload jsonb NOT NULL,
            steps jsonb DEFAULT '[]'::jsonb,
            result jsonb,
            compensation_meta jsonb,
            correlation_id text,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(),
            expires_at timestamptz
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS adapter_executions (
            execution_id uuid PRIMARY KEY,
            saga_id uuid NOT NULL REFERENCES sagas(saga_id) ON DELETE CASCADE,
            adapter_type text NOT NULL,
            operation text NOT NULL,
            status text NOT NULL,
            input jsonb,
            output jsonb,
            error_message text,
            duration_ms int,
            retry_count int DEFAULT 0,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compensation_history (
            compensation_id uuid PRIMARY KEY,
            saga_id uuid NOT NULL REFERENCES sagas(saga_id) ON DELETE CASCADE,
            original_operation text NOT NULL,
            compensation_operation text NOT NULL,
            original_result jsonb,
            compensation_result jsonb,
            reason text,
            created_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_state ON sagas(state)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_state_updated ON sagas(state, updated_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_user_id ON sagas(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_correlation_id ON sagas(correlation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_expires_at ON sagas(expires_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_action_id ON sagas(action_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_saga_type ON sagas(saga_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sagas_saga_type_version ON sagas(saga_type, saga_version)")

    op.execute("CREATE INDEX IF NOT EXISTS ix_adapter_exec_saga_id ON adapter_executions(saga_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_adapter_exec_adapter_type ON adapter_executions(adapter_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_adapter_exec_status ON adapter_executions(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_compensation_history_saga ON compensation_history(saga_id)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_compensation_history_saga")
    op.execute("DROP INDEX IF EXISTS ix_adapter_exec_status")
    op.execute("DROP INDEX IF EXISTS ix_adapter_exec_adapter_type")
    op.execute("DROP INDEX IF EXISTS ix_adapter_exec_saga_id")
    op.execute("DROP INDEX IF EXISTS ix_sagas_saga_type_version")
    op.execute("DROP INDEX IF EXISTS ix_sagas_saga_type")
    op.execute("DROP INDEX IF EXISTS ix_sagas_action_id")
    op.execute("DROP INDEX IF EXISTS ix_sagas_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_sagas_correlation_id")
    op.execute("DROP INDEX IF EXISTS ix_sagas_user_id")
    op.execute("DROP INDEX IF EXISTS ix_sagas_state_updated")
    op.execute("DROP INDEX IF EXISTS ix_sagas_state")

    op.execute("DROP TABLE IF EXISTS compensation_history")
    op.execute("DROP TABLE IF EXISTS adapter_executions")
    op.execute("DROP TABLE IF EXISTS sagas")
