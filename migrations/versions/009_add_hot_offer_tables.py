"""
Alembic migration: Add hot offer tables

Generated: 2026-02-12
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "hot_offer_001"
down_revision = "vision_intake_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_stats (
            stat_id uuid PRIMARY KEY,
            location_id uuid,
            day_of_week int NOT NULL,
            hour_of_day int NOT NULL,
            category text,
            recipe_name text,
            avg_units_sold numeric,
            created_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_offers (
            offer_id uuid PRIMARY KEY,
            status text NOT NULL,
            offer_payload jsonb NOT NULL,
            validation_scores jsonb,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hot_offer_history (
            offer_id uuid PRIMARY KEY,
            status text NOT NULL,
            offer_payload jsonb NOT NULL,
            notes text,
            created_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_stats_location ON sales_stats(location_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_stats_day_hour ON sales_stats(day_of_week, hour_of_day)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_offers_status ON pending_offers(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hot_offer_history_status ON hot_offer_history(status)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_hot_offer_history_status")
    op.execute("DROP INDEX IF EXISTS ix_pending_offers_status")
    op.execute("DROP INDEX IF EXISTS ix_sales_stats_day_hour")
    op.execute("DROP INDEX IF EXISTS ix_sales_stats_location")

    op.execute("DROP TABLE IF EXISTS hot_offer_history")
    op.execute("DROP TABLE IF EXISTS pending_offers")
    op.execute("DROP TABLE IF EXISTS sales_stats")
