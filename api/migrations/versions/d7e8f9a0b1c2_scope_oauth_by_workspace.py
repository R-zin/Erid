"""scope oauth identities by workspace

Adds ``workspace_id`` to ``oauth_identities`` and updates the unique constraint
to ``(provider, provider_subject, workspace_id)`` so an external OAuth account
can join multiple workspaces without tenant identity collision.

Revision ID: d7e8f9a0b1c2
Revises: c4d5e6f7a8b9
Create Date: 2026-10-29 14:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("oauth_identities", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.execute(
        "UPDATE oauth_identities SET workspace_id = actors.workspace_id "
        "FROM actors WHERE oauth_identities.actor_id = actors.id"
    )
    op.alter_column("oauth_identities", "workspace_id", nullable=False)
    op.drop_constraint("uq_oauth_provider_subject", "oauth_identities", type_="unique")
    op.create_unique_constraint(
        "uq_oauth_provider_subject_workspace",
        "oauth_identities",
        ["provider", "provider_subject", "workspace_id"],
    )
    op.create_foreign_key(
        "fk_oauth_identities_workspace_id",
        "oauth_identities",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_oauth_identities_workspace_id"), "oauth_identities", ["workspace_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_oauth_identities_workspace_id"), table_name="oauth_identities")
    op.drop_constraint("fk_oauth_identities_workspace_id", "oauth_identities", type_="foreignkey")
    op.drop_constraint("uq_oauth_provider_subject_workspace", "oauth_identities", type_="unique")
    op.create_unique_constraint("uq_oauth_provider_subject", "oauth_identities", ["provider", "provider_subject"])
    op.drop_column("oauth_identities", "workspace_id")
