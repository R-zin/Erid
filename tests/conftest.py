"""Test fixtures: run the FastAPI app against an isolated database.

By default every test gets a fresh in-memory SQLite DB (aiosqlite), so the suite
needs no services. Set ``ERID_TEST_DATABASE_URL`` to a Postgres URL to run the
same suite against Postgres instead: the schema is built once by the real
Alembic migrations (so Postgres-only features like the full-text-search column
and ``LISTEN/NOTIFY`` are exercised) and every table is truncated between tests.
"""

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Point the app at the test DB BEFORE importing it (the engine binds at import
# time). Static pooling keeps one shared in-memory DB for the app's own engine.
TEST_DATABASE_URL = os.environ.get("ERID_TEST_DATABASE_URL") or "sqlite+aiosqlite://"
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("EVENT_BUS_BACKEND", "memory")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from app.core.settings import settings  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.pool import NullPool, StaticPool  # noqa: E402


def _migrate_postgres_once() -> None:
    """Rebuild the Postgres test schema from scratch with Alembic (sync, at import)."""
    import asyncio

    from alembic import command
    from alembic.config import Config

    api_root = Path(__file__).resolve().parent.parent / "api"

    async def _reset() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(_reset())
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")


if IS_POSTGRES:
    _migrate_postgres_once()
    # Live-server tests run uvicorn in a fresh thread + event loop per test, and
    # asyncpg connections are bound to the loop that opened them. Rebind the
    # app's own engine to NullPool so no connection outlives its loop.
    import app.db.session as _session

    _session.engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    _session.AsyncSessionLocal = async_sessionmaker(_session.engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def db_engine():
    if IS_POSTGRES:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        yield engine
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await engine.dispose()
        return

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db_engine) -> AsyncGenerator[AsyncClient]:
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def authed(client: AsyncClient):
    """Provision a secured workspace and return (slug, api_key) + headers."""
    slug = "secured-ws"
    r = await client.post("/api/workspaces", params={"slug": slug})
    assert r.status_code == 201
    api_key = r.json()["api_key"]
    return slug, {"X-API-Key": api_key}


def test_settings_database_override():
    assert settings.database_url == TEST_DATABASE_URL
