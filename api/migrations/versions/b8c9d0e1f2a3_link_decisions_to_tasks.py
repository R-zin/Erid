"""link decisions to tasks

Adds a nullable ``decisions.task_id`` foreign key so a decision can reference the
task it informs (decision ↔ task linking). ``SET NULL`` keeps the decision when
the task is deleted.

Revision ID: b8c9d0e1f2a3
Revises: f52d92a7d306
Create Date: 2026-07-30 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "f52d92a7d306"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("decisions", sa.Column("task_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_decisions_task_id"), "decisions", ["task_id"], unique=False)
    op.create_foreign_key("fk_decisions_task_id_tasks", "decisions", "tasks", ["task_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_decisions_task_id_tasks", "decisions", type_="foreignkey")
    op.drop_index(op.f("ix_decisions_task_id"), table_name="decisions")
    op.drop_column("decisions", "task_id")
