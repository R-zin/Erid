"""Tests for operator gating: ``ERID_ADMIN_TOKEN`` and ``ERID_PUBLIC_WORKSPACE_DIRECTORY``.

On a public deployment, workspace provisioning (which mints an owner key) and
the anonymous workspace directory should be operator-only. Both are opt-in so
the zero-config local flow is unchanged.
"""

import pytest
from app.core.settings import settings
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

TOKEN = "op-secret-123"


@pytest.fixture(autouse=True)
def _restore_settings():
    original = (settings.admin_token, settings.public_workspace_directory)
    yield
    object.__setattr__(settings, "admin_token", original[0])
    object.__setattr__(settings, "public_workspace_directory", original[1])


def _set(**kw) -> None:
    for k, v in kw.items():
        object.__setattr__(settings, k, v)


async def test_provision_open_when_no_admin_token(client: AsyncClient):
    _set(admin_token="")
    r = await client.post("/api/workspaces?slug=free")
    assert r.status_code == 201
    assert r.json()["api_key"]


async def test_provision_requires_admin_token_when_configured(client: AsyncClient):
    _set(admin_token=TOKEN)
    assert (await client.post("/api/workspaces?slug=gated")).status_code == 401
    bad = await client.post("/api/workspaces?slug=gated", headers={"X-Admin-Token": "nope"})
    assert bad.status_code == 401
    ok = await client.post("/api/workspaces?slug=gated", headers={"X-Admin-Token": TOKEN})
    assert ok.status_code == 201
    assert ok.json()["api_key"]


async def test_directory_public_by_default(client: AsyncClient):
    _set(admin_token=TOKEN, public_workspace_directory=True)
    await client.post("/api/workspaces?slug=listed", headers={"X-Admin-Token": TOKEN})
    r = await client.get("/api/workspaces")
    assert r.status_code == 200
    assert any(w["slug"] == "listed" for w in r.json())


async def test_private_directory_needs_admin_token(client: AsyncClient):
    _set(admin_token=TOKEN, public_workspace_directory=False)
    await client.post("/api/workspaces?slug=hidden", headers={"X-Admin-Token": TOKEN})
    assert (await client.get("/api/workspaces")).status_code == 403
    r = await client.get("/api/workspaces", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    assert any(w["slug"] == "hidden" for w in r.json())


async def test_private_directory_without_any_admin_token_is_closed(client: AsyncClient):
    """No token configured means nobody is an operator, so the listing stays shut."""
    _set(admin_token="", public_workspace_directory=False)
    assert (await client.get("/api/workspaces", headers={"X-Admin-Token": ""})).status_code == 403
