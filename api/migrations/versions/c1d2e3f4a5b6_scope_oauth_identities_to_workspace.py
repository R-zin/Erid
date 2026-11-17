"""scope oauth identities to a workspace

Adds ``oauth_identities.workspace_id`` (backfilled from the linked actor) and
replaces the global ``(provider, provider_subject)`` unique constraint with
``(provider, provider_subject, workspace_id)``. Before this, a single external
account mapped to one actor *globally*, so logging in to workspace B with an
identity first linked in workspace A minted a B token for A's actor.

Revision ID: c1d2e3f4a5b6
Revises: a9b0c1d2e3f4
Create Date: 2026-11-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "a9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("oauth_identities", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.execute(
        "UPDATE oauth_identities AS oi SET workspace_id = a.workspace_id FROM actors AS a WHERE a.id = oi.actor_id"
    )
    # actor_id is NOT NULL with ON DELETE CASCADE, so every row has an actor;
    # drop any stragglers defensively rather than fail the NOT NULL below.
    op.execute("DELETE FROM oauth_identities WHERE workspace_id IS NULL")
    op.alter_column("oauth_identities", "workspace_id", nullable=False)
    op.create_foreign_key(
        "fk_oauth_identities_workspace_id",
        "oauth_identities",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_oauth_identities_workspace_id"), "oauth_identities", ["workspace_id"], unique=False)
    op.drop_constraint("uq_oauth_provider_subject", "oauth_identities", type_="unique")
    op.create_unique_constraint(
        "uq_oauth_provider_subject_workspace",
        "oauth_identities",
        ["provider", "provider_subject", "workspace_id"],
    )


def downgrade() -> None:
    """Downgrade schema.

    Collapsing back to one identity per external account is lossy: keep the
    oldest link per ``(provider, provider_subject)`` and drop the rest.
    """
    op.drop_constraint("uq_oauth_provider_subject_workspace", "oauth_identities", type_="unique")
    op.execute(
        """
        DELETE FROM oauth_identities AS oi
        USING oauth_identities AS keep
        WHERE oi.provider = keep.provider
          AND oi.provider_subject = keep.provider_subject
          AND (oi.created_at, oi.id::text) > (keep.created_at, keep.id::text)
        """
    )
    op.create_unique_constraint("uq_oauth_provider_subject", "oauth_identities", ["provider", "provider_subject"])
    op.drop_index(op.f("ix_oauth_identities_workspace_id"), table_name="oauth_identities")
    op.drop_constraint("fk_oauth_identities_workspace_id", "oauth_identities", type_="foreignkey")
    op.drop_column("oauth_identities", "workspace_id")
