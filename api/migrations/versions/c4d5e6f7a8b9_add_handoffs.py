"""add handoffs table

Adds the ``handoffs`` table for durable session handoffs: what was done, which
files/commands were involved, blockers, and the recommended next action, with
an ``open → acknowledged → resolved`` lifecycle. ``task_id`` is a soft link with
``SET NULL`` so a handoff survives its task being deleted (mirrors decisions).

Revision ID: c4d5e6f7a8b9
Revises: b7e3a2c1d9f4
Create Date: 2026-09-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b7e3a2c1d9f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "handoffs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("recipient", sa.String(length=128), nullable=True),
        sa.Column("branch", sa.String(length=256), nullable=True),
        sa.Column("worktree", sa.String(length=512), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("files_changed", sa.Text(), nullable=True),
        sa.Column("commands_run", sa.Text(), nullable=True),
        sa.Column("blockers", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "acknowledged", "resolved", name="handoffstatus"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_handoffs_task_id_tasks", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_handoffs_workspace_id_workspaces", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_handoffs_workspace_id"), "handoffs", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_handoffs_task_id"), "handoffs", ["task_id"], unique=False)
    op.create_index(op.f("ix_handoffs_created_by"), "handoffs", ["created_by"], unique=False)
    op.create_index(op.f("ix_handoffs_recipient"), "handoffs", ["recipient"], unique=False)
    op.create_index(op.f("ix_handoffs_status"), "handoffs", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_handoffs_status"), table_name="handoffs")
    op.drop_index(op.f("ix_handoffs_recipient"), table_name="handoffs")
    op.drop_index(op.f("ix_handoffs_created_by"), table_name="handoffs")
    op.drop_index(op.f("ix_handoffs_task_id"), table_name="handoffs")
    op.drop_index(op.f("ix_handoffs_workspace_id"), table_name="handoffs")
    op.drop_table("handoffs")
    # Drop the enum type on Postgres (no-op on SQLite, which has no native enums).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="handoffstatus").drop(bind, checkfirst=True)
