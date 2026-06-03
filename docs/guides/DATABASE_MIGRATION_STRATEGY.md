# Database Migration Strategy

## Overview
This document describes the database migration strategy for the Seed Server, including migration tooling, procedures, and best practices.

## Current Database Schema
**Technology**: SQLite 3.35+  
**Location**: Configured via `DATABASE_URL` environment variable  
**Tables**: 20+ tables including:
- Users & Authentication: `users`, `sessions`, `api_keys`
- Learning Content: `units`, `nodes`, `lessons`, `diagnostics`
- User Progress: `learning_profiles`, `skill_levels`, `progress_tracking`
- Job System: `jobs`, `job_results`
- Testing: `prompt_test_runs`, `prompt_test_results`

## Migration Tool Selection

### Recommended: Alembic
**Why Alembic:**
- Industry standard for SQLAlchemy migrations
- Automatic migration generation from model changes
- Version control for database schema
- Rollback capabilities
- SQLite support with batch mode for ALTER operations

### Installation
```bash
pip install alembic
```

### Initialization
```bash
alembic init migrations
```

## Migration File Structure

```
seed_server/
├── migrations/
│   ├── versions/
│   │   ├── 001_initial_schema.py
│   │   ├── 002_add_course_tables.py
│   │   ├── 003_add_learning_path_v2.py
│   │   └── ...
│   ├── env.py
│   ├── script.py.mako
│   └── alembic.ini
└── app/
    └── models.py
```

## Configuration

### alembic.ini
```ini
[alembic]
script_location = migrations
sqlalchemy.url = sqlite:///./data/seed_server.db

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### migrations/env.py
```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys

# Add app directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.models import Base  # Import your SQLAlchemy Base

# this is the Alembic Config object
config = context.config

# Override sqlalchemy.url from environment
database_url = os.getenv('DATABASE_URL', 'sqlite:///./data/seed_server.db')
config.set_main_option('sqlalchemy.url', database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Required for SQLite ALTER operations
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # Required for SQLite ALTER operations
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

## Migration Workflow

### 1. Creating a New Migration

**Auto-generate from model changes:**
```bash
alembic revision --autogenerate -m "Add course modeling tables"
```

**Manual migration:**
```bash
alembic revision -m "Add custom index on user_id"
```

### 2. Review Generated Migration
Always review auto-generated migrations before applying:
```python
# migrations/versions/002_add_course_tables.py
def upgrade() -> None:
    # Review these operations
    op.create_table('courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    op.drop_table('courses')
```

### 3. Apply Migration

**Local/Development:**
```bash
alembic upgrade head
```

**Production:**
```bash
# Backup first!
./scripts/backup_database.sh

# Apply migration
alembic upgrade head

# Verify
alembic current
```

### 4. Rollback if Needed
```bash
# Rollback one version
alembic downgrade -1

# Rollback to specific version
alembic downgrade abc123def456

# Rollback all
alembic downgrade base
```

## Migration Best Practices

### 1. Always Backup Before Migration
```bash
# See scripts/backup_database.sh
sqlite3 data/seed_server.db ".backup data/backups/seed_server_$(date +%Y%m%d_%H%M%S).db"
```

### 2. Test Migrations Locally First
```bash
# Test on copy of production data
cp data/production.db data/test_migration.db
DATABASE_URL=sqlite:///./data/test_migration.db alembic upgrade head
```

### 3. SQLite-Specific Considerations
- Use `render_as_batch=True` for ALTER operations
- Some operations require table recreation (e.g., dropping columns)
- Foreign key constraints may need special handling
- Use `PRAGMA foreign_keys=ON` in production

### 4. Data Migrations
For data transformations, create separate migration:
```python
def upgrade() -> None:
    # Schema change
    op.add_column('lessons', sa.Column('course_id', sa.Integer(), nullable=True))
    
    # Data migration
    op.execute("""
        UPDATE lessons 
        SET course_id = (
            SELECT id FROM courses 
            WHERE courses.unit_id = lessons.unit_id
            LIMIT 1
        )
    """)
    
    # Make column non-nullable after data populated
    with op.batch_alter_table('lessons') as batch_op:
        batch_op.alter_column('course_id', nullable=False)
```

### 5. Version Control
- Commit migrations to git immediately after creation
- Never modify applied migrations (create new ones instead)
- Keep migrations small and focused

## Deployment Procedure

### Development
```bash
# 1. Make model changes in app/models.py
# 2. Generate migration
alembic revision --autogenerate -m "Description"
# 3. Review and edit migration file
# 4. Test locally
alembic upgrade head
# 5. Commit migration file
git add migrations/versions/*.py
git commit -m "Add migration: description"
```

### Production
```bash
# 1. Backup database
./scripts/backup_database.sh

# 2. Put server in maintenance mode (optional)
# systemctl stop seed-server

# 3. Pull latest code
git pull origin main

# 4. Apply migrations
alembic upgrade head

# 5. Verify migration
alembic current
sqlite3 data/seed_server.db ".schema" | grep -A 10 "new_table"

# 6. Restart server
# systemctl start seed-server

# 7. Monitor logs
tail -f logs/server.log
```

## Migration History Commands

```bash
# Show current version
alembic current

# Show migration history
alembic history

# Show pending migrations
alembic history --verbose

# Show SQL without applying
alembic upgrade head --sql
```

## Emergency Rollback Procedure

```bash
# 1. Stop server
systemctl stop seed-server

# 2. Restore from backup
cp data/backups/seed_server_20260112_143000.db data/seed_server.db

# 3. Verify data integrity
sqlite3 data/seed_server.db "PRAGMA integrity_check;"

# 4. Start server
systemctl start seed-server

# 5. Alert team and investigate
```

## Course Modeling Migration Example

**Migration for new course feature:**
```python
"""Add course modeling tables

Revision ID: 002_course_modeling
Revises: 001_initial_schema
Create Date: 2026-01-12 14:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '002_course_modeling'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Courses table
    op.create_table('courses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('difficulty_level', sa.String(20), nullable=False),
        sa.Column('estimated_hours', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_courses_created_by', 'courses', ['created_by'])
    
    # Course units (linking courses to existing units)
    op.create_table('course_units',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('sequence_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['unit_id'], ['units.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'unit_id', name='uq_course_unit')
    )
    op.create_index('ix_course_units_course_id', 'course_units', ['course_id'])
    
    # Course enrollment
    op.create_table('course_enrollments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('progress_percentage', sa.Float(), default=0.0),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_id', 'user_id', name='uq_course_enrollment')
    )
    op.create_index('ix_enrollments_user_id', 'course_enrollments', ['user_id'])

def downgrade() -> None:
    op.drop_index('ix_enrollments_user_id', table_name='course_enrollments')
    op.drop_table('course_enrollments')
    op.drop_index('ix_course_units_course_id', table_name='course_units')
    op.drop_table('course_units')
    op.drop_index('ix_courses_created_by', table_name='courses')
    op.drop_table('courses')
```

## Integration with CI/CD

### GitHub Actions
```yaml
- name: Run Database Migrations
  run: |
    alembic upgrade head
    
- name: Verify Migration
  run: |
    alembic current | grep -q "head"
```

## Monitoring & Alerts

### Track Migration Status
```python
# Add to monitoring/metrics
from alembic import command
from alembic.config import Config

def check_migration_status():
    """Check if database is at latest migration"""
    alembic_cfg = Config("alembic.ini")
    # Compare current vs head
    # Alert if not at head
```

## Next Steps

1. **Initialize Alembic**: Run `alembic init migrations`
2. **Create Initial Migration**: Capture current schema
3. **Document Current Schema**: Add ER diagram
4. **Set Up Backup Automation**: See `scripts/backup_database.sh`
5. **Test Rollback Procedure**: Practice on development database
6. **Add to CI/CD**: Integrate migration checks

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLite ALTER TABLE Limitations](https://www.sqlite.org/lang_altertable.html)
- [SQLAlchemy Models](app/models.py)
- [Backup Strategy](docs/guides/OPERATIONAL_RUNBOOKS.md#database-backups)
