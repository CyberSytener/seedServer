"""
Alembic migration: Add pgvector extension and embedding columns

Generated: 2026-02-08
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "pgvector_001"
down_revision = "saga_indexes_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable pgvector and add embedding columns (PostgreSQL only)."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    inspector = sa.inspect(bind)

    if inspector.has_table("job_leads"):
        op.execute("ALTER TABLE job_leads ADD COLUMN IF NOT EXISTS embedding vector(1536)")
        op.execute("ALTER TABLE job_leads ADD COLUMN IF NOT EXISTS embedding_model text")
        op.execute("ALTER TABLE job_leads ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_job_leads_embedding "
            "ON job_leads USING ivfflat (embedding vector_cosine_ops)"
        )

    if inspector.has_table("user_skills"):
        op.execute("ALTER TABLE user_skills ADD COLUMN IF NOT EXISTS embedding vector(1536)")
        op.execute("ALTER TABLE user_skills ADD COLUMN IF NOT EXISTS embedding_model text")
        op.execute("ALTER TABLE user_skills ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_user_skills_embedding "
            "ON user_skills USING ivfflat (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    """Drop embedding columns and indexes (PostgreSQL only)."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_job_leads_embedding")
    op.execute("DROP INDEX IF EXISTS ix_user_skills_embedding")

    if sa.inspect(bind).has_table("job_leads"):
        op.execute("ALTER TABLE job_leads DROP COLUMN IF EXISTS embedding_updated_at")
        op.execute("ALTER TABLE job_leads DROP COLUMN IF EXISTS embedding_model")
        op.execute("ALTER TABLE job_leads DROP COLUMN IF EXISTS embedding")

    if sa.inspect(bind).has_table("user_skills"):
        op.execute("ALTER TABLE user_skills DROP COLUMN IF EXISTS embedding_updated_at")
        op.execute("ALTER TABLE user_skills DROP COLUMN IF EXISTS embedding_model")
        op.execute("ALTER TABLE user_skills DROP COLUMN IF EXISTS embedding")
