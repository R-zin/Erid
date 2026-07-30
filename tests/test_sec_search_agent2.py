"""Tests for the now-secured ``/search`` and ``/summary`` endpoints (#10, agent-2).

The secured copies live in ``app.api.routes.context_misc`` (scoped behind
``require_action(Permission.read)``). The legacy open handlers still sit in
``context.py`` and would shadow these at the app level, so these tests exercise
``context_misc.router`` mounted on its own app — this isolates the intended
post-reconciliation behavior and depends only on search/summary semantics.

Matrix: open workspace → 200; secured without creds → 401; bad creds → 403;
valid read principal (legacy key and a ``reader`` actor) → 200.
"""

import pytest
from app.api.routes import context_misc
from app.db.session import get_db
from app.main import app as main_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sec_client(db_engine):
    """Two apps sharing one in-memory DB: the full main app (for provisioning/
    minting) and a minimal app mounting ONLY the secured search/summary router."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    secured = FastAPI()
    secured.include_router(context_misc.router, prefix="/api")
    secured.dependency_overrides[get_db] = override_get_db
    main_app.dependency_overrides[get_db] = override_get_db

    async with (
        AsyncClient(transport=ASGITransport(app=secured), base_url="http://test") as sec,
        AsyncClient(transport=ASGITransport(app=main_app), base_url="http://test") as main,
    ):
        yield sec, main

    secured.dependency_overrides.clear()
    main_app.dependency_overrides.clear()


# --- open workspace: no key configured → read is fully public ------------------


async def test_summary_open_workspace_allows_anonymous(sec_client):
    sec, _ = sec_client
    slug = "open-ws"
    # A keyless workspace is auto-created on first read; no credentials needed.
    r = await sec.get(f"/api/workspaces/{slug}/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == slug
    assert "task_count" in body and "active_developers" in body


async def test_search_open_workspace_allows_anonymous(sec_client):
    sec, _ = sec_client
    r = await sec.get("/api/workspaces/open-ws-search/search", params={"q": "anything"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "anything"
    assert body["decisions"] == [] and body["tasks"] == []


# --- secured workspace: key configured → creds required -----------------------


async def test_summary_secured_requires_credentials(sec_client):
    sec, main = sec_client
    slug = "sec-ws"
    key = await _provision(main, slug)

    assert (await sec.get(f"/api/workspaces/{slug}/summary")).status_code == 401
    assert (await sec.get(f"/api/workspaces/{slug}/summary", headers={"X-API-Key": "wrong"})).status_code == 403

    r = await sec.get(f"/api/workspaces/{slug}/summary", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json()["slug"] == slug


async def test_search_secured_requires_credentials(sec_client):
    sec, main = sec_client
    slug = "sec-ws-search"
    key = await _provision(main, slug)

    assert (await sec.get(f"/api/workspaces/{slug}/search", params={"q": "x"})).status_code == 401
    assert (
        await sec.get(f"/api/workspaces/{slug}/search", params={"q": "x"}, headers={"X-API-Key": "nope"})
    ).status_code == 403

    r = await sec.get(f"/api/workspaces/{slug}/search", params={"q": "x"}, headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json()["query"] == "x"


async def test_search_and_summary_return_seeded_data(sec_client):
    """Search/summary actually read this workspace's rows (not just auth)."""
    sec, main = sec_client
    slug = "sec-ws-data"
    key = await _provision(main, slug)
    admin = {"X-API-Key": key}
    assert (
        await main.post(f"/api/workspaces/{slug}/tasks", json={"title": "build the thing"}, headers=admin)
    ).status_code == 201
    assert (
        await main.post(f"/api/workspaces/{slug}/decisions", json={"title": "chose the stack"}, headers=admin)
    ).status_code == 201

    summary = (await sec.get(f"/api/workspaces/{slug}/summary", headers=admin)).json()
    assert summary["task_count"] == 1
    assert summary["decision_count"] == 1

    hit = (await sec.get(f"/api/workspaces/{slug}/search", params={"q": "stack"}, headers=admin)).json()
    assert [d["title"] for d in hit["decisions"]] == ["chose the stack"]
    miss = (await sec.get(f"/api/workspaces/{slug}/search", params={"q": "nope"}, headers=admin)).json()
    assert miss["tasks"] == [] and miss["decisions"] == []


async def test_reader_actor_gets_200(sec_client):
    """A per-actor key with the reader role carries read permission → 200."""
    sec, main = sec_client
    slug = "sec-ws-reader"
    owner_key = await _provision(main, slug)
    ar = await main.post(
        f"/api/workspaces/{slug}/actors",
        json={"name": "reader-bot", "role": "reader"},
        headers={"X-API-Key": owner_key},
    )
    assert ar.status_code == 201, ar.text
    h = {"X-API-Key": ar.json()["api_key"]}

    assert (await sec.get(f"/api/workspaces/{slug}/summary", headers=h)).status_code == 200
    assert (await sec.get(f"/api/workspaces/{slug}/search", params={"q": "x"}, headers=h)).status_code == 200


# --- helpers ------------------------------------------------------------------


async def _provision(main: AsyncClient, slug: str) -> str:
    """Provision a keyed workspace via the main app; return its owner key."""
    r = await main.post("/api/workspaces", params={"slug": slug})
    assert r.status_code == 201, r.text
    return r.json()["api_key"]


# --- CORS configuration (the other half of #10) --------------------------------


async def test_cors_origins_default_is_not_wildcard():
    """allow_credentials=True demands enumerated origins, never '*'."""
    from app.core.settings import settings

    assert settings.cors_origins
    assert "*" not in settings.cors_origins
    assert "http://localhost:5173" in settings.cors_origins


async def test_cors_preflight_from_dashboard_origin(sec_client):
    """A preflight from the allowed dashboard origin is accepted (echoed back,
    with credentials advertised); a disallowed origin is not."""
    _, main = sec_client  # main_app carries the real CORSMiddleware
    r = await main.options(
        "/api/workspaces/open-ws/summary",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert r.headers["access-control-allow-credentials"] == "true"

    denied = await main.options(
        "/api/workspaces/open-ws/summary",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers
