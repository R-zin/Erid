"""Integration tests for agent-1 (backend-api) tasks.

#7 presence atomic upsert + presence uniqueness and lookup indexes, #8 delete
endpoints (task/decision/workspace), #9 workspace management (list/secure/
rotate-key). Runs against the shared in-memory SQLite fixtures in conftest.py.
"""

import asyncio

import pytest
from app.db.session import Base

pytestmark = pytest.mark.asyncio


def _key_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


async def _create_open_workspace(client, slug: str) -> None:
    """Create a keyless (open) workspace via an implicit-create summary read."""
    r = await client.get(f"/api/workspaces/{slug}/summary")
    assert r.status_code == 200, r.text


async def _create_actor(client, slug: str, admin_headers, name: str, role: str):
    r = await client.post(f"/api/workspaces/{slug}/actors", json={"name": name, "role": role}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


# --- #7: presence upsert + indexes --------------------------------------------


async def test_presence_upsert_updates_existing_row(client, authed):
    slug, admin = authed
    body = {"actor_name": "raz", "actor_type": "ai", "current_file": "a.py"}
    r1 = await client.post(f"/api/workspaces/{slug}/presence", json=body, headers=admin)
    assert r1.status_code == 200, r1.text
    first_id = r1.json()["id"]

    # Repeat the heartbeat for the same (workspace, actor): update, not insert.
    body["current_file"] = "b.py"
    r2 = await client.post(f"/api/workspaces/{slug}/presence", json=body, headers=admin)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == first_id
    assert r2.json()["current_file"] == "b.py"

    listed = (await client.get(f"/api/workspaces/{slug}/presence", headers=admin)).json()
    assert len([p for p in listed if p["actor_name"] == "raz"]) == 1


async def test_presence_concurrent_posts_do_not_conflict(client, authed):
    slug, admin = authed
    body = {"actor_name": "raz", "current_file": "x.py"}
    results = await asyncio.gather(
        *(client.post(f"/api/workspaces/{slug}/presence", json=body, headers=admin) for _ in range(5))
    )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    listed = (await client.get(f"/api/workspaces/{slug}/presence", headers=admin)).json()
    assert len([p for p in listed if p["actor_name"] == "raz"]) == 1


async def test_presence_unique_constraint_on_model():
    table = Base.metadata.tables["presence"]
    uq = next((c for c in table.constraints if c.name == "uq_presence_workspace_actor"), None)
    assert uq is not None
    assert {col.name for col in uq.columns} == {"workspace_id", "actor_name"}


async def test_lookup_indexes_present():
    assert "ix_decisions_made_by" in {i.name for i in Base.metadata.tables["decisions"].indexes}
    assert "ix_tasks_assigned_to" in {i.name for i in Base.metadata.tables["tasks"].indexes}


async def test_schema_reflects_constraint_and_indexes(db_engine):
    from sqlalchemy import inspect

    async with db_engine.connect() as conn:
        uqs = await conn.run_sync(lambda c: inspect(c).get_unique_constraints("presence"))
        idx_d = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("decisions")})
        idx_t = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("tasks")})

    assert {tuple(sorted(u["column_names"])) for u in uqs} >= {tuple(sorted(["workspace_id", "actor_name"]))}
    assert "ix_decisions_made_by" in idx_d
    assert "ix_tasks_assigned_to" in idx_t


# --- #8: delete endpoints ------------------------------------------------------


async def test_delete_task(client, authed):
    slug, admin = authed
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "gone"}, headers=admin)).json()
    assert (await client.delete(f"/api/workspaces/{slug}/tasks/{task['id']}", headers=admin)).status_code == 204
    remaining = (await client.get(f"/api/workspaces/{slug}/tasks", headers=admin)).json()
    assert all(t["id"] != task["id"] for t in remaining)


async def test_delete_task_404(client, authed):
    slug, admin = authed
    r = await client.delete(f"/api/workspaces/{slug}/tasks/00000000-0000-0000-0000-000000000000", headers=admin)
    assert r.status_code == 404


async def test_delete_task_requires_write_tasks(client, authed):
    slug, admin = authed
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "t"}, headers=admin)).json()
    reader = await _create_actor(client, slug, admin, "reader-bot", "reader")
    r = await client.delete(f"/api/workspaces/{slug}/tasks/{task['id']}", headers=_key_headers(reader["api_key"]))
    assert r.status_code == 403


async def test_delete_decision(client, authed):
    slug, admin = authed
    decision = (await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "chose"}, headers=admin)).json()
    r = await client.delete(f"/api/workspaces/{slug}/decisions/{decision['id']}", headers=admin)
    assert r.status_code == 204
    assert (await client.get(f"/api/workspaces/{slug}/decisions", headers=admin)).json() == []


async def test_delete_decision_404(client, authed):
    slug, admin = authed
    r = await client.delete(f"/api/workspaces/{slug}/decisions/00000000-0000-0000-0000-000000000000", headers=admin)
    assert r.status_code == 404


async def test_delete_task_nulls_linked_decision(client, authed):
    slug, admin = authed
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "host"}, headers=admin)).json()
    decision = (
        await client.post(
            f"/api/workspaces/{slug}/decisions", json={"title": "informs", "task_id": task["id"]}, headers=admin
        )
    ).json()
    assert decision["task_id"] == task["id"]
    assert (await client.delete(f"/api/workspaces/{slug}/tasks/{task['id']}", headers=admin)).status_code == 204
    # The decision survives; its task_id is nulled (SET NULL).
    after = (await client.get(f"/api/workspaces/{slug}/decisions", headers=admin)).json()
    assert len(after) == 1
    assert after[0]["task_id"] is None


async def test_delete_workspace_cascades_and_requires_owner(client, authed):
    slug, admin = authed
    await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "t"}, headers=admin)
    await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "d"}, headers=admin)
    writer = await _create_actor(client, slug, admin, "dev", "writer")

    # A non-owner actor cannot delete the workspace.
    r = await client.delete(f"/api/workspaces/{slug}", headers=_key_headers(writer["api_key"]))
    assert r.status_code == 403

    assert (await client.delete(f"/api/workspaces/{slug}", headers=admin)).status_code == 204
    slugs = [w["slug"] for w in (await client.get("/api/workspaces")).json()]
    assert slug not in slugs


# --- #9: workspace management --------------------------------------------------


async def test_list_workspaces_public_directory(client, authed):
    slug, _ = authed
    await _create_open_workspace(client, "open-ws")
    r = await client.get("/api/workspaces")
    assert r.status_code == 200
    items = {w["slug"]: w for w in r.json()}
    assert items[slug]["secured"] is True
    assert items["open-ws"]["secured"] is False
    # No keys are ever exposed in the listing.
    assert all("api_key" not in w for w in r.json())


async def test_secure_open_workspace_discloses_key_once(client):
    await _create_open_workspace(client, "claim-me")
    # Open workspace: no auth required; the first caller takes the key (owner).
    r = await client.post("/api/workspaces/claim-me/secure")
    assert r.status_code == 200, r.text
    key = r.json()["api_key"]
    assert key and r.json()["secured"] is True

    # The key now secures the workspace (anonymous is rejected).
    assert (await client.get("/api/workspaces/claim-me/tasks")).status_code == 401
    assert (await client.get("/api/workspaces/claim-me/tasks", headers=_key_headers(key))).status_code == 200

    # Calling secure again on an already-secured workspace never re-discloses.
    r2 = await client.post("/api/workspaces/claim-me/secure")
    assert r2.status_code == 200
    assert r2.json()["api_key"] is None
    assert r2.json()["secured"] is True


async def test_secure_provisioned_workspace_not_rekeyed(client, authed):
    slug, _ = authed
    r = await client.post(f"/api/workspaces/{slug}/secure")
    assert r.status_code == 200
    assert r.json()["api_key"] is None
    assert r.json()["secured"] is True


async def test_secure_missing_workspace_404(client):
    assert (await client.post("/api/workspaces/nope/secure")).status_code == 404


async def test_rotate_key_owner_only_and_old_key_stops(client, authed):
    slug, admin = authed
    old_key = admin["X-API-Key"]
    r = await client.post(f"/api/workspaces/{slug}/rotate-key", headers=admin)
    assert r.status_code == 200, r.text
    new_key = r.json()["api_key"]
    assert new_key and new_key != old_key

    # Old key stops working; new key works.
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=_key_headers(old_key))).status_code == 403
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=_key_headers(new_key))).status_code == 200


async def test_rotate_key_forbidden_for_non_owner(client, authed):
    slug, admin = authed
    writer = await _create_actor(client, slug, admin, "dev", "writer")
    r = await client.post(f"/api/workspaces/{slug}/rotate-key", headers=_key_headers(writer["api_key"]))
    assert r.status_code == 403


async def test_rotate_key_open_workspace_allowed(client):
    # require_action resolves an open (keyless) workspace as a full-access
    # principal, so rotating it succeeds and secures it from then on.
    await _create_open_workspace(client, "rot-open")
    r = await client.post("/api/workspaces/rot-open/rotate-key")
    assert r.status_code == 200, r.text
    assert r.json()["api_key"]
