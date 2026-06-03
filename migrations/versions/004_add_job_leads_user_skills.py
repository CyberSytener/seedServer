"""
Alembic migration: Create job_leads and user_skills tables with pgvector support

Generated: 2026-02-09
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "job_leads_001"
down_revision = "pgvector_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_leads (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL,
            source text NOT NULL,
            external_id text,
            title text NOT NULL,
            company text,
            location text,
            salary_range jsonb,
            description text,
            skills jsonb,
            embedding vector(1536),
            embedding_model text,
            embedding_updated_at timestamptz,
            scores jsonb NOT NULL DEFAULT '{}'::jsonb,
            score_stage smallint DEFAULT 1,
            match_reason text,
            status text DEFAULT 'new',
            scan_id uuid,
            created_at timestamptz DEFAULT now(),
            expires_at timestamptz,
            UNIQUE (user_id, source, external_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_leads_user_status ON job_leads(user_id, status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_leads_expires ON job_leads(expires_at) "
        "WHERE status = 'hot_lead'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_leads_embedding "
        "ON job_leads USING ivfflat (embedding vector_cosine_ops)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_skills (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL,
            skill text NOT NULL,
            level text,
            source text,
            embedding vector(1536),
            embedding_model text,
            embedding_updated_at timestamptz,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(),
            UNIQUE (user_id, skill)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_skills_user ON user_skills(user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_skills_embedding "
        "ON user_skills USING ivfflat (embedding vector_cosine_ops)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_embeddings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type text NOT NULL,
            entity_id text NOT NULL,
            text text NOT NULL,
            embedding vector(1536) NOT NULL,
            model text NOT NULL,
            created_at timestamptz DEFAULT now(),
            UNIQUE (entity_type, entity_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_skill_embeddings_ann "
        "ON skill_embeddings USING ivfflat (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_skill_embeddings_ann")
    op.execute("DROP TABLE IF EXISTS skill_embeddings")
    op.execute("DROP INDEX IF EXISTS ix_user_skills_embedding")
    op.execute("DROP INDEX IF EXISTS idx_user_skills_user")
    op.execute("DROP TABLE IF EXISTS user_skills")
    op.execute("DROP INDEX IF EXISTS ix_job_leads_embedding")
    op.execute("DROP INDEX IF EXISTS idx_job_leads_expires")
    op.execute("DROP INDEX IF EXISTS idx_job_leads_user_status")
    op.execute("DROP TABLE IF EXISTS job_leads")
