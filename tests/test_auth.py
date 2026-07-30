"""Integration tests for richer auth: actors, roles, grants, and JWT.

Covers the per-permission enforcement matrix, actor key minting/login, JWT
round-trips, legacy workspace-key back-compat, and write attribution. Runs
against SQLite via the shared fixtures in conftest.py.
"""

import pytest

pytestmark = pytest.mark.asyncio


def _key_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _mint_actor(client, slug: str, admin_headers, name: str, role: str, permissions=None):
    body = {"name": name, "role": role}
    if permissions is not None:
        body["permissions"] = permissions
    r = await client.post(f"/api/workspaces/{slug}/actors", json=body, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


# --- actor minting --------------------------------------------------------------


async def test_mint_actor_discloses_key_once(client, authed):
    slug, admin = authed
    actor = await _mint_actor(client, slug, admin, "alice", "writer")
    assert actor["name"] == "alice"
    assert actor["role"] == "writer"
    assert actor["api_key"]  # raw key shown once

    # Listing never discloses keys.
    listed = (await client.get(f"/api/workspaces/{slug}/actors", headers=admin)).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "alice"
    assert "api_key" not in listed[0]


async def test_mint_actor_requires_admin(client, authed):
    slug, admin = authed
    # A writer actor cannot mint other actors.
    writer = await _mint_actor(client, slug, admin, "bob", "writer")
    r = await client.post(
        f"/api/workspaces/{slug}/actors",
        json={"name": "eve", "role": "reader"},
        headers=_key_headers(writer["api_key"]),
    )
    assert r.status_code == 403

    # Anonymous can't either.
    r2 = await client.post(f"/api/workspaces/{slug}/actors", json={"name": "eve", "role": "reader"})
    assert r2.status_code == 401


async def test_duplicate_actor_conflict(client, authed):
    slug, admin = authed
    await _mint_actor(client, slug, admin, "alice", "writer")
    r = await client.post(f"/api/workspaces/{slug}/actors", json={"name": "alice", "role": "reader"}, headers=admin)
    assert r.status_code == 409


# --- role-based read/write enforcement -----------------------------------------


async def test_reader_can_read_but_not_write(client, authed):
    slug, admin = authed
    reader = await _mint_actor(client, slug, admin, "reader-bot", "reader")
    h = _key_headers(reader["api_key"])

    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=h)).status_code == 200
    assert (await client.get(f"/api/workspaces/{slug}/decisions", headers=h)).status_code == 200
    assert (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "x"}, headers=h)).status_code == 403
    assert (await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "d"}, headers=h)).status_code == 403
    assert (
        await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "r"}, headers=h)
    ).status_code == 403


async def test_writer_can_write_but_not_admin(client, authed):
    slug, admin = authed
    writer = await _mint_actor(client, slug, admin, "dev", "writer")
    h = _key_headers(writer["api_key"])

    assert (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "x"}, headers=h)).status_code == 201
    assert (await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "d"}, headers=h)).status_code == 201
    assert (
        await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "dev"}, headers=h)
    ).status_code == 200
    # but admin endpoints are off-limits
    assert (await client.get(f"/api/workspaces/{slug}/actors", headers=h)).status_code == 403


async def test_custom_grants_override_role_default(client, authed):
    slug, admin = authed
    # Reader role but explicitly granted only write_tasks: can write tasks but
    # NOT decisions (custom grants replace the role's read default? No — grants
    # are additive to the role default).
    actor = await _mint_actor(client, slug, admin, "narrow", "reader", permissions=["write_tasks"])
    h = _key_headers(actor["api_key"])

    # role default grants read
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=h)).status_code == 200
    # explicit extra grant
    assert (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "x"}, headers=h)).status_code == 201
    # not granted
    assert (await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "d"}, headers=h)).status_code == 403


# --- JWT login round-trip --------------------------------------------------------


async def test_login_issues_usable_jwt(client, authed):
    slug, admin = authed
    writer = await _mint_actor(client, slug, admin, "jwt-dev", "writer")

    token_r = await client.post(f"/api/workspaces/{slug}/token", json={"api_key": writer["api_key"]})
    assert token_r.status_code == 200, token_r.text
    token = token_r.json()["access_token"]
    assert token_r.json()["token_type"] == "bearer"

    bh = _bearer_headers(token)
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=bh)).status_code == 200
    assert (
        await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "via jwt"}, headers=bh)
    ).status_code == 201


async def test_jwt_enforces_actor_permissions(client, authed):
    slug, admin = authed
    reader = await _mint_actor(client, slug, admin, "jwt-reader", "reader")
    token = (await client.post(f"/api/workspaces/{slug}/token", json={"api_key": reader["api_key"]})).json()[
        "access_token"
    ]
    bh = _bearer_headers(token)
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=bh)).status_code == 200
    assert (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "x"}, headers=bh)).status_code == 403


async def test_jwt_scoped_to_workspace(client, authed):
    slug, admin = authed
    writer = await _mint_actor(client, slug, admin, "scoped", "writer")
    token = (await client.post(f"/api/workspaces/{slug}/token", json={"api_key": writer["api_key"]})).json()[
        "access_token"
    ]
    # Token minted for `slug` must not authorize another secured workspace.
    r2 = await client.post("/api/workspaces", params={"slug": "other-ws"})
    other_key = r2.json()["api_key"]
    r = await client.get("/api/workspaces/other-ws/tasks", headers=_bearer_headers(token))
    assert r.status_code == 403
    # sanity: its own key works
    assert (await client.get("/api/workspaces/other-ws/tasks", headers=_key_headers(other_key))).status_code == 200


async def test_login_rejects_bad_key(client, authed):
    slug, _ = authed
    assert (await client.post(f"/api/workspaces/{slug}/token", json={"api_key": "nope"})).status_code == 403


async def test_legacy_workspace_key_gets_owner_jwt(client, authed):
    slug, admin = authed
    token_r = await client.post(f"/api/workspaces/{slug}/token", json={"api_key": admin["X-API-Key"]})
    assert token_r.status_code == 200
    bh = _bearer_headers(token_r.json()["access_token"])
    # owner token can hit an admin endpoint
    assert (await client.get(f"/api/workspaces/{slug}/actors", headers=bh)).status_code == 200
    # and can mint actors
    r = await client.post(f"/api/workspaces/{slug}/actors", json={"name": "sub", "role": "reader"}, headers=bh)
    assert r.status_code == 201


# --- attribution ---------------------------------------------------------------


async def test_writes_default_to_actor_name(client, authed):
    slug, admin = authed
    writer = await _mint_actor(client, slug, admin, "casey", "writer")
    h = _key_headers(writer["api_key"])

    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "build"}, headers=h)).json()
    assert task["created_by"] == "casey"
    decision = (await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "chose"}, headers=h)).json()
    assert decision["made_by"] == "casey"


async def test_explicit_attribution_preserved(client, authed):
    slug, admin = authed
    # An explicitly-supplied attribution wins over the caller's identity.
    task = (
        await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "t", "created_by": "me"}, headers=admin)
    ).json()
    assert task["created_by"] == "me"


# --- revocation ------------------------------------------------------------------


async def test_revoked_actor_loses_access(client, authed):
    slug, admin = authed
    actor = await _mint_actor(client, slug, admin, "temp", "writer")
    h = _key_headers(actor["api_key"])
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=h)).status_code == 200

    r = await client.delete(f"/api/workspaces/{slug}/actors/{actor['id']}", headers=admin)
    assert r.status_code == 204
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=h)).status_code == 403
