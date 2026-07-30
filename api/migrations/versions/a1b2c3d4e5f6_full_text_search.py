"""full-text search for search_context

Replace the ``ILIKE '%q%'`` substring search with Postgres full-text search:
a generated ``search_vector`` column (weighted so titles rank above bodies) plus
a GIN index on decisions and tasks, and ``pg_trgm`` trigram indexes on the exact
columns the search queries so substring matching also uses an index.

Postgres-only: gated on the dialect so SQLite/test runs and offline SQL
generation skip this migration's DDL.

Revision ID: a1b2c3d4e5f6
Revises: d6019e176d79
Create Date: 2026-07-30 10:30:00.000000

"""

from collections.abc import Sequence

from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "d6019e176d79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Weighted per column: titles matter more (A) than reasons (B). The generated
# column stays fresh automatically as rows change.
_DECISION_VECTOR = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') "
    "|| setweight(to_tsvector('english', coalesce(reason, '')), 'B')"
)
_TASK_VECTOR = "setweight(to_tsvector('english', coalesce(title, '')), 'A')"


def _is_postgres() -> bool:
    return context.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    """Upgrade schema."""
    if not _is_postgres():
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Stored tsvector columns + GIN indexes for ranked full-text search.
    op.execute(
        f"ALTER TABLE decisions ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ({_DECISION_VECTOR}) STORED"
    )
    op.execute("CREATE INDEX ix_decisions_search_vector ON decisions USING gin (search_vector)")
    op.execute(f"ALTER TABLE tasks ADD COLUMN search_vector tsvector GENERATED ALWAYS AS ({_TASK_VECTOR}) STORED")
    op.execute("CREATE INDEX ix_tasks_search_vector ON tasks USING gin (search_vector)")

    # Trigram indexes accelerate ILIKE '%q%' substring queries on the exact
    # columns the search route filters.
    op.execute("CREATE INDEX ix_decisions_title_trgm ON decisions USING gin (title gin_trgm_ops)")
    op.execute("CREATE INDEX ix_decisions_reason_trgm ON decisions USING gin (reason gin_trgm_ops)")
    op.execute("CREATE INDEX ix_tasks_title_trgm ON tasks USING gin (title gin_trgm_ops)")


def downgrade() -> None:
    """Downgrade schema."""
    if not _is_postgres():
        return

    op.execute("DROP INDEX IF EXISTS ix_tasks_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_decisions_reason_trgm")
    op.execute("DROP INDEX IF EXISTS ix_decisions_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_tasks_search_vector")
    op.execute("DROP INDEX IF EXISTS ix_decisions_search_vector")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE decisions DROP COLUMN IF EXISTS search_vector")
