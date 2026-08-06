"""oauth identities for social login

Adds ``oauth_identities``, linking an external OAuth account (Google/GitHub)
to a workspace ``Actor``. OAuth login resolves to a real actor row (no API key)
and mints the internal JWT for it, so the existing auth path is unchanged.

Revision ID: b7e3a2c1d9f4
Revises: 2c3bc1c08eea
Create Date: 2026-08-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3a2c1d9f4"
down_revision: str | Sequence[str] | None = "2c3bc1c08eea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
    )
    op.create_index(op.f("ix_oauth_identities_actor_id"), "oauth_identities", ["actor_id"], unique=False)
    op.create_index(op.f("ix_oauth_identities_email"), "oauth_identities", ["email"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_oauth_identities_email"), table_name="oauth_identities")
    op.drop_index(op.f("ix_oauth_identities_actor_id"), table_name="oauth_identities")
    op.drop_table("oauth_identities")
