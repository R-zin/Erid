"""Regression tests for bugs found in the production-readiness audit.

* Input that exceeds a database column's length must be rejected up front with
  422. Without a schema limit it reached Postgres and surfaced as a 500.
* A JWT minted from the shared workspace key must stop working once that key
  is rotated, and must never carry over to a different workspace that later
  reuses the slug.
* Tenant isolation: no credential for one workspace reads or writes another.
* Every workspace-scoped route refuses an anonymous caller on a secured workspace.
"""

import uuid

import pytest
from app.main import app
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

LONG = "x" * 600


# ---------------------------------------------------------------------------
# Over-long input -> 422, not a database error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("tasks", {"title": "t", "assigned_to": LONG}),
        ("tasks", {"title": "t", "created_by": LONG}),
        ("decisions", {"title": "d", "made_by": LONG}),
        ("decisions", {"title": "d", "reason": "r" * 20_000}),
        ("decisions", {"title": "d", "related_files": "f" * 20_000}),
        ("presence", {"actor_name": "a", "actor_type": LONG}),
        ("presence", {"actor_name": "a", "current_file": LONG}),
        ("presence", {"actor_name": "a", "current_task": LONG}),
    ],
)
async def test_overlong_fields_are_422(client: AsyncClient, authed, path, body):
    slug, headers = authed
    r = await client.post(f"/api/workspaces/{slug}/{path}", json=body, headers=headers)
    assert r.status_code == 422, r.text


async def test_overlong_task_update_assignee_is_422(client: AsyncClient, authed):
    slug, headers = authed
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "t"}, headers=headers)).json()
    r = await client.put(f"/api/workspaces/{slug}/tasks/{task['id']}", json={"assigned_to": LONG}, headers=headers)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("slug", ["s" * 200, "has space", "../etc", "", "-leading-dash", "émoji🙂"])
async def test_invalid_slug_rejected_on_provision(client: AsyncClient, slug):
    r = await client.post("/api/workspaces", params={"slug": slug})
    assert r.status_code == 422, r.text


async def test_overlong_slug_in_path_is_not_a_server_error(client: AsyncClient):
    r = await client.get(f"/api/workspaces/{'s' * 300}/tasks")
    assert r.status_code in (404, 422), r.text


# ---------------------------------------------------------------------------
# Workspace-key JWTs are bound to the key that minted them
# ---------------------------------------------------------------------------


async def _legacy_token(client: AsyncClient, slug: str, key: str) -> str:
    r = await client.post(f"/api/workspaces/{slug}/token", json={"api_key": key})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_workspace_key_token_dies_when_key_rotates(client: AsyncClient, authed):
    slug, headers = authed
    token = await _legacy_token(client, slug, headers["X-API-Key"])
    bearer = {"Authorization": f"Bearer {token}"}
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=bearer)).status_code == 200

    rotated = await client.post(f"/api/workspaces/{slug}/rotate-key", headers=headers)
    assert rotated.status_code == 200

    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=bearer)).status_code == 403


async def test_workspace_key_token_does_not_survive_slug_reuse(client: AsyncClient):
    slug = "reused-slug"
    key = (await client.post("/api/workspaces", params={"slug": slug})).json()["api_key"]
    token = await _legacy_token(client, slug, key)

    assert (await client.delete(f"/api/workspaces/{slug}", headers={"X-API-Key": key})).status_code == 204
    # Someone else provisions the same slug afterwards.
    assert (await client.post("/api/workspaces", params={"slug": slug})).status_code == 201

    r = await client.get(f"/api/workspaces/{slug}/tasks", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def _workspace(client: AsyncClient, slug: str) -> dict[str, str]:
    r = await client.post("/api/workspaces", params={"slug": slug})
    assert r.status_code == 201
    return {"X-API-Key": r.json()["api_key"]}


async def test_tenant_isolation(client: AsyncClient):
    a = await _workspace(client, "tenant-a")
    b = await _workspace(client, "tenant-b")
    task = (await client.post("/api/workspaces/tenant-a/tasks", json={"title": "secret"}, headers=a)).json()
    decision = (await client.post("/api/workspaces/tenant-a/decisions", json={"title": "d"}, headers=a)).json()
    handoff = (await client.post("/api/workspaces/tenant-a/handoffs", json={"summary": "s"}, headers=a)).json()

    # A's key on B's workspace, and B's key on A's.
    assert (await client.get("/api/workspaces/tenant-b/tasks", headers=a)).status_code == 403
    assert (await client.get("/api/workspaces/tenant-a/tasks", headers=b)).status_code == 403

    # A's JWT is scoped to A.
    token = await _legacy_token(client, "tenant-a", a["X-API-Key"])
    assert (
        await client.get("/api/workspaces/tenant-b/tasks", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 403

    # A's object ids are invisible through B, even with B's valid key.
    tid, did, hid = task["id"], decision["id"], handoff["id"]
    assert (
        await client.put(f"/api/workspaces/tenant-b/tasks/{tid}", json={"title": "x"}, headers=b)
    ).status_code == 404
    assert (await client.delete(f"/api/workspaces/tenant-b/tasks/{tid}", headers=b)).status_code == 404
    assert (await client.delete(f"/api/workspaces/tenant-b/decisions/{did}", headers=b)).status_code == 404
    assert (await client.get(f"/api/workspaces/tenant-b/handoffs/{hid}", headers=b)).status_code == 404
    assert (await client.post(f"/api/workspaces/tenant-b/handoffs/{hid}/resolve", headers=b)).status_code == 404
    # B can't link its own decision to A's task.
    r = await client.post("/api/workspaces/tenant-b/decisions", json={"title": "d", "task_id": tid}, headers=b)
    assert r.status_code == 404

    # A's data is still intact and search through B finds nothing of A's.
    assert [t["title"] for t in (await client.get("/api/workspaces/tenant-a/tasks", headers=a)).json()] == ["secret"]
    found = (await client.get("/api/workspaces/tenant-b/search", params={"q": "secret"}, headers=b)).json()
    assert found["tasks"] == [] and found["decisions"] == []


# ---------------------------------------------------------------------------
# Every workspace-scoped route refuses anonymous callers on a secured workspace
# ---------------------------------------------------------------------------

# Routes that are deliberately anonymous: the key->JWT login, and claiming an
# open workspace (which a secured workspace refuses by returning no key).
_ANONYMOUS_OK = {("POST", "/api/workspaces/{slug}/token"), ("POST", "/api/workspaces/{slug}/secure")}


def _workspace_routes() -> list[tuple[str, str]]:
    """Every (METHOD, path) under /api/workspaces/{slug}, from the OpenAPI schema."""
    out = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/workspaces/{slug}"):
            continue
        for method in operations:
            if (method.upper(), path) not in _ANONYMOUS_OK:
                out.append((method.upper(), path))
    return out


async def test_every_workspace_route_requires_credentials(client: AsyncClient, authed):
    slug, headers = authed
    routes = _workspace_routes()
    assert len(routes) > 15  # sanity: the enumeration found the API
    fake = str(uuid.uuid4())
    for method, template in routes:
        path = template.replace("{slug}", slug)
        for param in ("{task_id}", "{decision_id}", "{handoff_id}", "{actor_id}", "{claim_id}"):
            path = path.replace(param, fake)
        r = await client.request(method, path, json={})
        assert r.status_code in (401, 403, 422), f"{method} {template} -> {r.status_code}"
        assert not (200 <= r.status_code < 300)
