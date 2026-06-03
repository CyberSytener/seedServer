"""
Alembic migration: Create stock_levels table

Generated: 2026-02-12
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "stock_levels_001"
down_revision = "job_leads_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_levels (
            ingredient_name text PRIMARY KEY,
            barcode text,
            quantity numeric NOT NULL DEFAULT 0,
            unit text,
            metadata jsonb,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_levels_barcode ON stock_levels(barcode)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stock_levels_updated_at ON stock_levels(updated_at)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_stock_levels_updated_at")
    op.execute("DROP INDEX IF EXISTS ux_stock_levels_barcode")
    op.execute("DROP TABLE IF EXISTS stock_levels")
