"""presence unique constraint and lookup indexes

Adds a unique constraint on ``presence (workspace_id, actor_name)`` so the
presence heartbeat can be a true atomic upsert (''INSERT ... ON CONFLICT''), and
indexes on ``decisions.made_by`` and ``tasks.assigned_to`` for the
filter-by-actor lookups. Portable across Postgres and SQLite — no dialect gate.

The upgrade first deduplicates any pre-existing presence rows per
``(workspace_id, actor_name)`` (a running deployment may have accumulated
duplicates from the old read-then-insert race) so the constraint can be created
cleanly.

Revision ID: 2c3bc1c08eea
Revises: b8c9d0e1f2a3
Create Date: 2026-07-30 11:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2c3bc1c08eea"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Keep the freshest row per (workspace, actor), dropping older duplicates.
    # Format-safe on both Postgres and SQLite (id is a UUID stored as text).
    op.execute(
        sa.text("DELETE FROM presence WHERE id NOT IN (SELECT MAX(id) FROM presence GROUP BY workspace_id, actor_name)")
    )
    # SQLite cannot ALTER a table to add a constraint, so use batch mode
    # (copy-and-move) for the presence unique constraint; on Postgres the batch
    # context is a thin wrapper around a plain ALTER TABLE.
    with op.batch_alter_table("presence") as batch_op:
        batch_op.create_unique_constraint("uq_presence_workspace_actor", ["workspace_id", "actor_name"])
    op.create_index(op.f("ix_decisions_made_by"), "decisions", ["made_by"], unique=False)
    op.create_index(op.f("ix_tasks_assigned_to"), "tasks", ["assigned_to"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_tasks_assigned_to"), table_name="tasks")
    op.drop_index(op.f("ix_decisions_made_by"), table_name="decisions")
    with op.batch_alter_table("presence") as batch_op:
        batch_op.drop_constraint("uq_presence_workspace_actor", type_="unique")
