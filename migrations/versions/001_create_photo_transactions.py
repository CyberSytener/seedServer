"""
Alembic migration: Create photo_credit_transactions table

Generated: 2025-01-30
Phase: 6
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'photo_credit_001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create photo_credit_transactions table"""
    op.create_table(
        'photo_credit_transactions',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),
        sa.Column('job_id', sa.String(36), nullable=True, index=True),
        sa.Column('amount', sa.Float, nullable=False),
        sa.Column('transaction_type', sa.String(20), nullable=False),
        sa.Column('reason', sa.Text, nullable=True),
        sa.Column('balance_before', sa.Float, nullable=True),
        sa.Column('balance_after', sa.Float, nullable=True),
        sa.Column('api_cost_usd', sa.Float, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, 
                  server_default=sa.func.now(), index=True),
    )
    
    # Create indexes for common queries
    op.create_index('ix_photo_credit_user_id', 'photo_credit_transactions', ['user_id'])
    op.create_index('ix_photo_credit_job_id', 'photo_credit_transactions', ['job_id'])
    op.create_index('ix_photo_credit_created', 'photo_credit_transactions', ['created_at'])


def downgrade() -> None:
    """Drop photo_credit_transactions table"""
    op.drop_index('ix_photo_credit_created', table_name='photo_credit_transactions')
    op.drop_index('ix_photo_credit_job_id', table_name='photo_credit_transactions')
    op.drop_index('ix_photo_credit_user_id', table_name='photo_credit_transactions')
    op.drop_table('photo_credit_transactions')
