"""store workspace keys hashed

Replaces ``workspaces.api_key`` (the raw legacy/owner key) with
``workspaces.api_key_hash`` (its SHA-256 hex digest), matching how actor keys
were already stored. Existing keys keep working: they are hashed in place.
Raw keys can't be recovered from their hashes, so the downgrade refuses to run
while any workspace is secured (dropping the hash would silently make it open).

Revision ID: a9b0c1d2e3f4
Revises: f7a8b9c0d1e2
Create Date: 2026-11-14 00:00:02.000000

"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9b0c1d2e3f4"
down_revision: str | Sequence[str] | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("api_key_hash", sa.String(length=64), nullable=True))

    bind = op.get_bind()
    workspaces = sa.table(
        "workspaces",
        sa.column("id", sa.UUID()),
        sa.column("api_key", sa.String()),
        sa.column("api_key_hash", sa.String()),
    )
    rows = bind.execute(sa.select(workspaces.c.id, workspaces.c.api_key).where(workspaces.c.api_key.is_not(None)))
    for ws_id, raw in rows.fetchall():
        bind.execute(
            workspaces.update()
            .where(workspaces.c.id == ws_id)
            .values(api_key_hash=hashlib.sha256(raw.encode()).hexdigest())
        )

    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("api_key")


def downgrade() -> None:
    secured = op.get_bind().execute(sa.text("SELECT count(*) FROM workspaces WHERE api_key_hash IS NOT NULL"))
    if secured.scalar_one():
        raise RuntimeError(
            "refusing to downgrade: secured workspaces exist and their raw keys cannot be recovered "
            "from the stored hashes (the downgrade would leave them open)"
        )
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("api_key", sa.String(length=128), nullable=True))
        batch.drop_column("api_key_hash")
