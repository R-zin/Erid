"""Test fixtures: run the FastAPI app against an isolated in-memory SQLite DB.

The API writes to Postgres in prod, but the ORM is engine-agnostic, so for
integration tests we swap the engine to per-test SQLite (aiosqlite) and
override the ``get_db`` dependency. This needs no Postgres and no extra code
changes — and by importing ``app.main`` we exercise the real app factory.
"""

import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Point the app at SQLite BEFORE importing it (the engine binds at import
# time). Static pooling keeps one shared in-memory DB for the app's own engine.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ.setdefault("EVENT_BUS_BACKEND", "memory")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.settings import settings  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest.fixture
async def db_engine():
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
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
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


def test_settings_sqlite_override():
    assert settings.database_url.startswith("sqlite")
