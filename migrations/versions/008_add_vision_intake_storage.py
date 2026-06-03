"""
Alembic migration: Add vision intake and storage tables

Generated: 2026-02-12
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "vision_intake_001"
down_revision = "saga_tables_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vision_intake (
            intake_id uuid PRIMARY KEY,
            user_id text,
            intent text NOT NULL,
            image_url text,
            image_base64 text,
            prompt text,
            raw_payload jsonb,
            analysis jsonb,
            confidence numeric,
            model_name text,
            status text NOT NULL DEFAULT 'received',
            confirmation_notes text,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_item (
            storage_id uuid PRIMARY KEY,
            name text NOT NULL,
            quantity numeric NOT NULL,
            unit text NOT NULL,
            expires_at date,
            metadata jsonb,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_intake_status ON vision_intake(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_intake_intent ON vision_intake(intent)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_storage_item_expires_at ON storage_item(expires_at)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_storage_item_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_vision_intake_intent")
    op.execute("DROP INDEX IF EXISTS ix_vision_intake_status")
    op.execute("DROP TABLE IF EXISTS storage_item")
    op.execute("DROP TABLE IF EXISTS vision_intake")
