"""actor and grant tables for richer auth

Adds ``actors`` (named per-workspace identities with a role and a hashed key)
and ``actor_grants`` (fine-grained, per-resource permissions). Raw keys are
never stored — only SHA-256 digests.

Revision ID: f52d92a7d306
Revises: a1b2c3d4e5f6
Create Date: 2026-07-30 10:24:04.989463

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f52d92a7d306"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "actors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.Enum("reader", "writer", "owner", name="actorrole"), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_actors_workspace_name"),
    )
    op.create_index(op.f("ix_actors_workspace_id"), "actors", ["workspace_id"], unique=False)
    op.create_table(
        "actor_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column(
            "permission",
            sa.Enum("read", "write_tasks", "write_decisions", "presence", "admin_keys", "owner", name="permission"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "permission", name="uq_grants_actor_permission"),
    )
    op.create_index(op.f("ix_actor_grants_actor_id"), "actor_grants", ["actor_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_actor_grants_actor_id"), table_name="actor_grants")
    op.drop_table("actor_grants")
    op.drop_index(op.f("ix_actors_workspace_id"), table_name="actors")
    op.drop_table("actors")
