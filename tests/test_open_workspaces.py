"""Tests for the ``ERID_ALLOW_OPEN_WORKSPACES`` flag.

Open workspaces are the zero-config default: the first request naming any slug
creates that workspace, keyless, with full access, and ``POST /{slug}/secure``
hands its owner key to whoever asks first. Convenient locally, but on a public
deployment it lets a stranger grow the ``workspaces`` table at will and squat
slugs before the real team provisions them.

These tests pin both modes: that the open default still behaves exactly as
documented, and that closed mode (``allow_open_workspaces = False``) shuts the
implicit create, the anonymous claim, and anonymous access to a pre-existing
keyless workspace — while leaving explicit provisioning as the way in.
"""

import pytest
from app.core.security import resolve_ws_principal
from app.core.settings import settings
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _restore_settings():
    """Restore the frozen Settings singleton after each test.

    ``Settings`` is a frozen dataclass, so ``monkeypatch.setattr`` on the instance
    raises ``FrozenInstanceError``; mutate via ``object.__setattr__`` instead (the
    same singleton is read at call time by both security.py and context.py) and
    put the original back afterwards. Mirrors tests/test_oauth.py.
    """
    original = settings.allow_open_workspaces
    yield
    object.__setattr__(settings, "allow_open_workspaces", original)


def _set_open_workspaces(value: bool) -> None:
    object.__setattr__(settings, "allow_open_workspaces", value)


# ---------------------------------------------------------------------------
# Open mode (the default) — unchanged behaviour
# ---------------------------------------------------------------------------


async def test_open_mode_creates_workspace_on_first_touch(client: AsyncClient):
    """The documented zero-config flow: read an unknown slug, get an empty list."""
    r = await client.get("/api/workspaces/brand-new/tasks")
    assert r.status_code == 200
    assert r.json() == []

    # ...and the workspace now exists, keyless, in the directory.
    listing = (await client.get("/api/workspaces")).json()
    entry = next(w for w in listing if w["slug"] == "brand-new")
    assert entry["secured"] is False


async def test_open_mode_allows_anonymous_claim(client: AsyncClient):
    """`/secure` discloses the key once to the first caller (back-compat)."""
    await client.get("/api/workspaces/claimable/tasks")
    r = await client.post("/api/workspaces/claimable/secure")
    assert r.status_code == 200
    body = r.json()
    assert body["secured"] is True
    assert body["api_key"]

    # A second claim never re-discloses it.
    again = await client.post("/api/workspaces/claimable/secure")
    assert again.status_code == 200
    assert again.json()["api_key"] is None


# ---------------------------------------------------------------------------
# Closed mode
# ---------------------------------------------------------------------------


async def test_closed_mode_unknown_slug_404s_and_creates_nothing(client: AsyncClient):
    _set_open_workspaces(False)

    r = await client.get("/api/workspaces/never-provisioned/tasks")
    assert r.status_code == 404

    # The key property: no row was inserted, so the table can't be grown by an
    # anonymous caller walking slugs.
    listing = (await client.get("/api/workspaces")).json()
    assert all(w["slug"] != "never-provisioned" for w in listing)


async def test_closed_mode_write_to_unknown_slug_404s(client: AsyncClient):
    _set_open_workspaces(False)

    r = await client.post("/api/workspaces/never-provisioned/tasks", json={"title": "nope"})
    assert r.status_code == 404


async def test_closed_mode_provisioned_workspace_still_works(client: AsyncClient):
    """Explicit provisioning remains the way in — it mints a key up front."""
    _set_open_workspaces(False)

    created = await client.post("/api/workspaces", params={"slug": "proper"})
    assert created.status_code == 201
    headers = {"X-API-Key": created.json()["api_key"]}

    made = await client.post("/api/workspaces/proper/tasks", json={"title": "real work"}, headers=headers)
    assert made.status_code == 201
    listed = await client.get("/api/workspaces/proper/tasks", headers=headers)
    assert [t["title"] for t in listed.json()] == ["real work"]


async def test_closed_mode_locks_preexisting_keyless_workspace(client: AsyncClient):
    """A workspace left keyless from open mode stops being a free-for-all."""
    await client.get("/api/workspaces/legacy-open/tasks")  # created while open
    _set_open_workspaces(False)

    r = await client.get("/api/workspaces/legacy-open/tasks")
    assert r.status_code == 401
    assert "open workspaces are disabled" in r.json()["detail"]


async def test_closed_mode_refuses_anonymous_claim(client: AsyncClient):
    """The squatting half: nobody can take the owner key by asking."""
    await client.get("/api/workspaces/legacy-open/tasks")  # created while open
    _set_open_workspaces(False)

    r = await client.post("/api/workspaces/legacy-open/secure")
    assert r.status_code == 403
    assert "open workspaces are disabled" in r.json()["detail"]

    # Still keyless — the refusal didn't half-secure it.
    listing = (await client.get("/api/workspaces")).json()
    assert next(w for w in listing if w["slug"] == "legacy-open")["secured"] is False


async def test_closed_mode_secure_reports_already_secured_workspace(client: AsyncClient):
    """An already-secured workspace answers before the flag check, as before."""
    await client.post("/api/workspaces", params={"slug": "already"})
    _set_open_workspaces(False)

    r = await client.post("/api/workspaces/already/secure")
    assert r.status_code == 200
    assert r.json() == {"slug": "already", "secured": True, "api_key": None}


# ---------------------------------------------------------------------------
# WebSocket resolution (the endpoint closes with 1008 on a None principal)
# ---------------------------------------------------------------------------


async def test_closed_mode_ws_principal_is_none_for_unknown_slug(db_engine):
    _set_open_workspaces(False)
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        assert await resolve_ws_principal("no-such-ws", db, key=None, token=None) is None


async def test_open_mode_ws_principal_is_open_for_unknown_slug(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        principal = await resolve_ws_principal("fresh-ws", db, key=None, token=None)

    assert principal is not None
    assert principal.kind.value == "open"
