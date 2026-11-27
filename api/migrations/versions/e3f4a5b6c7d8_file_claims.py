"""file claims: advisory leases on paths

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-11-26 00:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_claims",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("holder", sa.String(length=128), nullable=False),
        sa.Column("exclusive", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("task_id", sa.UUID(), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_file_claims_workspace_id", "file_claims", ["workspace_id"])
    op.create_index("ix_file_claims_holder", "file_claims", ["holder"])
    op.create_index("ix_file_claims_task_id", "file_claims", ["task_id"])
    op.create_index("ix_file_claims_expires_at", "file_claims", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_file_claims_expires_at", table_name="file_claims")
    op.drop_index("ix_file_claims_task_id", table_name="file_claims")
    op.drop_index("ix_file_claims_holder", table_name="file_claims")
    op.drop_index("ix_file_claims_workspace_id", table_name="file_claims")
    op.drop_table("file_claims")
