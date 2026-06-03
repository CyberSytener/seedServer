"""
Alembic migration: Add webhook subscriptions tables

Generated: 2026-04-01
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "webhook_subs_001"
down_revision = "hot_offer_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_subscriptions (
            subscription_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            notification_url TEXT NOT NULL,
            resource TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            last_validated TIMESTAMPTZ,
            validation_token TEXT
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_subs_user_id
            ON webhook_subscriptions(user_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_subs_expires_at
            ON webhook_subscriptions(expires_at)
            WHERE is_active = TRUE
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS webhook_events (
            notification_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL REFERENCES webhook_subscriptions(subscription_id) ON DELETE CASCADE,
            resource TEXT NOT NULL,
            resource_data JSONB NOT NULL DEFAULT '{}'::jsonb,
            event_type TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_validated BOOLEAN NOT NULL DEFAULT FALSE
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_events_subscription
            ON webhook_events(subscription_id, received_at DESC)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_webhook_events_user
            ON webhook_events(user_id, received_at DESC)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TABLE IF EXISTS webhook_events")
    op.execute("DROP TABLE IF EXISTS webhook_subscriptions")
