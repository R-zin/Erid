"""event outbox table

Revision ID: f7a8b9c0d1e2
Revises: e1a2b3c4d5e6
Create Date: 2026-11-14 00:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "e1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.UUID(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_workspace_id", "events", ["workspace_id"])
    op.create_index("ix_events_created_at", "events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_events_created_at", table_name="events")
    op.drop_index("ix_events_workspace_id", table_name="events")
    op.drop_table("events")
