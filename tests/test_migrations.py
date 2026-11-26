"""Migration integrity on Postgres: the schema the migrations build matches the
ORM models, and the newest migrations downgrade and re-apply cleanly."""

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.db.session import Base
from app.models import models  # noqa: F401  (register tables)
from conftest import IS_POSTGRES, TEST_DATABASE_URL
from sqlalchemy import inspect, text

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not IS_POSTGRES, reason="needs ERID_TEST_DATABASE_URL pointing at Postgres"),
]

API_ROOT = Path(__file__).resolve().parent.parent / "api"
# The last migration before this release's (rate limits/audit, file claims).
BEFORE_THIS_RELEASE = "c1d2e3f4a5b6"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


def _is_expected(diff) -> bool:
    """Differences that are deliberate: Postgres-only search columns and
    indexes (full-text and trigram) that the migrations create and the ORM
    doesn't map (see app.services.context._search_vector)."""
    text_repr = repr(diff)
    return any(marker in text_repr for marker in ("search_vector", "_fts", "_trgm"))


async def test_migrated_schema_matches_the_models(db_engine):
    async with db_engine.connect() as conn:

        def diff(sync_conn):
            ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
            return compare_metadata(ctx, Base.metadata)

        diffs = await conn.run_sync(diff)
    unexpected = [d for d in diffs if not _is_expected(d)]
    assert not unexpected, f"models and migrations disagree: {unexpected}"


async def test_new_migrations_downgrade_and_reapply(db_engine):
    cfg = _cfg()
    await asyncio.to_thread(command.downgrade, cfg, BEFORE_THIS_RELEASE)
    try:
        async with db_engine.connect() as conn:
            tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert not {"rate_limits", "audit_events", "file_claims"} & tables
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert {"rate_limits", "audit_events", "file_claims"} <= tables
    assert [version] == ScriptDirectory.from_config(cfg).get_heads()
