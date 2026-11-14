"""add write_handoffs to the permission enum

The handoffs migration added ``Permission.write_handoffs`` to the model and to
the ``writer`` role defaults, but never extended the Postgres ``permission``
enum type. Minting any writer actor on Postgres therefore failed with
``invalid input value for enum permission: "write_handoffs"``. SQLite stores
enums as plain strings, which is why the SQLite test suite never saw it.

Revision ID: e1a2b3c4d5e6
Revises: c4d5e6f7a8b9
Create Date: 2026-11-14 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # ADD VALUE cannot run inside a transaction block on older Postgres; the
    # autocommit block makes this safe everywhere.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE permission ADD VALUE IF NOT EXISTS 'write_handoffs'")


def downgrade() -> None:
    # Postgres cannot drop a single enum value; leaving it is harmless.
    pass
