"""
Alembic migration: Add saga indexes and tuning

Generated: 2026-02-04
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "saga_indexes_001"
down_revision = "photo_credit_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexes to saga tables and tune autovacuum."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not inspector.has_table("sagas"):
        return

    op.create_index("ix_sagas_state", "sagas", ["state"])
    op.create_index("ix_sagas_state_updated", "sagas", ["state", "updated_at"])
    op.create_index("ix_sagas_user_id", "sagas", ["user_id"])
    op.create_index("ix_sagas_correlation_id", "sagas", ["correlation_id"])

    if dialect == "postgresql":
        op.create_index(
            "ix_sagas_expires_at",
            "sagas",
            ["expires_at"],
            postgresql_where=sa.text("expires_at IS NOT NULL"),
        )
    else:
        op.create_index("ix_sagas_expires_at", "sagas", ["expires_at"])

    if inspector.has_table("saga_idempotency"):
        op.create_index("ix_saga_idempotency_expires", "saga_idempotency", ["expires_at"])

    if inspector.has_table("compensation_history"):
        op.create_index("ix_compensation_history_saga", "compensation_history", ["saga_id"])

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE sagas SET (
                autovacuum_vacuum_scale_factor = 0.05,
                autovacuum_vacuum_cost_delay = 10,
                autovacuum_vacuum_cost_limit = 2000
            )
            """
        )


def downgrade() -> None:
    """Drop saga indexes and revert tuning."""
    op.drop_index("ix_compensation_history_saga", table_name="compensation_history")
    op.drop_index("ix_saga_idempotency_expires", table_name="saga_idempotency")
    op.drop_index("ix_sagas_expires_at", table_name="sagas")
    op.drop_index("ix_sagas_correlation_id", table_name="sagas")
    op.drop_index("ix_sagas_user_id", table_name="sagas")
    op.drop_index("ix_sagas_state_updated", table_name="sagas")
    op.drop_index("ix_sagas_state", table_name="sagas")
