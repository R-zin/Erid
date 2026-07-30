"""Alembic migration environment.

Uses the application's own settings and metadata so migrations always match the
ORM models. Migrations run through an async engine (the app's ``asyncpg``
driver, or ``aiosqlite`` in tests) via ``connection.run_sync``. Both online
(live DB) and offline (SQL script) modes are supported.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from app.core.settings import settings
from app.db.session import Base
from app.models import models  # noqa: F401  (register tables on Base.metadata)
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate diffs against the ORM models.
target_metadata = Base.metadata

# Point Alembic at the app's database (async URL; asyncpg / aiosqlite).
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a live connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the app's database."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
