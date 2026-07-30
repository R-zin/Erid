import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.settings import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_API_ROOT = Path(__file__).resolve().parents[2]


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Bring the database schema up to date.

    Tests run against SQLite, which has no Alembic history, so they (and any
    explicit opt-in via ``ERID_SKIP_MIGRATIONS=1``) create the schema directly
    from the models. Real deployments run Alembic ``upgrade head`` on startup.
    """
    if settings.skip_migrations or engine.url.get_backend_name() == "sqlite":
        await create_schema()
        return
    # Run Alembic in a thread: it drives its own connection and must not block
    # the event loop.
    await asyncio.to_thread(_run_migrations)


def _run_migrations() -> None:
    # Import models so they register on the metadata Alembic targets.
    from app.models import models  # noqa: F401

    cfg = Config(str(_API_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


async def create_schema() -> None:
    """Create tables directly from the ORM metadata (tests / SQLite only)."""
    # Import models so they register on the metadata before create_all.
    from app.models import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
