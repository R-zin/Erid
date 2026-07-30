"""Integration tests for the Context Hub REST API (routes + auth + validation).

Run against an isolated SQLite DB via the fixtures in conftest.py.
"""

import pytest

pytestmark = pytest.mark.asyncio


# --- meta ------------------------------------------------------------------


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_docs_available(client):
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/openapi.json")).status_code == 200


# --- workspace provisioning + auth -----------------------------------------


async def test_provision_mints_key_once(client):
    r = await client.post("/api/workspaces", params={"slug": "ws-a"})
    assert r.status_code == 201
    assert r.json()["api_key"]

    # Re-provisioning must not re-disclose the key.
    r2 = await client.post("/api/workspaces", params={"slug": "ws-a"})
    assert r2.json()["api_key"] is None


async def test_secured_workspace_requires_key(client, authed):
    slug, headers = authed
    assert (await client.get(f"/api/workspaces/{slug}/tasks")).status_code == 401
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 200


async def test_wrong_key_forbidden(client, authed):
    slug, _ = authed
    r = await client.get(f"/api/workspaces/{slug}/tasks", headers={"X-API-Key": "wrong"})
    assert r.status_code == 403


async def test_open_workspace_no_key_needed(client):
    # First touch on a write/secured route auto-creates an open workspace.
    r = await client.post("/api/workspaces/open-ws/tasks", json={"title": "t1"})
    assert r.status_code == 201
    assert (await client.get("/api/workspaces/open-ws/tasks")).status_code == 200


async def test_auth_via_query_param(client, authed):
    slug, headers = authed
    r = await client.get(f"/api/workspaces/{slug}/tasks", params={"api_key": headers["X-API-Key"]})
    assert r.status_code == 200


# --- tasks ------------------------------------------------------------------


async def test_task_crud_and_filter(client):
    slug = "tasks-ws"
    created = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "build", "created_by": "me"})).json()
    assert created["status"] == "todo"

    other = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "ship"})).json()

    updated = await client.put(f"/api/workspaces/{slug}/tasks/{created['id']}", json={"status": "in_progress"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"

    in_prog = (await client.get(f"/api/workspaces/{slug}/tasks", params={"status": "in_progress"})).json()
    assert [t["id"] for t in in_prog] == [created["id"]]

    all_tasks = (await client.get(f"/api/workspaces/{slug}/tasks")).json()
    assert {t["id"] for t in all_tasks} == {created["id"], other["id"]}


async def test_update_missing_task_404(client):
    import uuid

    r = await client.put(f"/api/workspaces/ws-x/tasks/{uuid.uuid4()}", json={"status": "done"})
    assert r.status_code == 404


async def test_task_requires_title(client):
    r = await client.post("/api/workspaces/ws-y/tasks", json={"title": ""})
    assert r.status_code == 422


# --- decisions ---------------------------------------------------------------


async def test_decision_create_and_list(client):
    slug = "decisions-ws"
    for i in range(3):
        await client.post(f"/api/workspaces/{slug}/decisions", json={"title": f"decision {i}", "made_by": "me"})
    decisions = (await client.get(f"/api/workspaces/{slug}/decisions", params={"limit": 2})).json()
    assert len(decisions) == 2  # limit is applied
    all_decisions = (await client.get(f"/api/workspaces/{slug}/decisions")).json()
    assert {d["title"] for d in all_decisions} == {"decision 0", "decision 1", "decision 2"}
    assert all(d["made_by"] == "me" for d in all_decisions)


async def test_decision_task_linking(client):
    slug = "link-ws"
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "migrate db"})).json()

    decision = (
        await client.post(
            f"/api/workspaces/{slug}/decisions",
            json={"title": "use alembic", "reason": "versioned schema", "task_id": task["id"]},
        )
    ).json()
    assert decision["task_id"] == task["id"]

    # The task now exposes its linked decisions.
    linked = (await client.get(f"/api/workspaces/{slug}/tasks/{task['id']}/decisions")).json()
    assert [d["id"] for d in linked] == [decision["id"]]

    # An unlinked decision has task_id null.
    other = (await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "standalone"})).json()
    assert other["task_id"] is None


async def test_decision_link_requires_existing_task(client):
    import uuid

    slug = "link-ws2"
    r = await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "dangling", "task_id": str(uuid.uuid4())})
    assert r.status_code == 404


# --- presence ---------------------------------------------------------------


async def test_presence_upsert_and_active(client):
    slug = "presence-ws"
    await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "alice", "current_task": "a"})
    # same actor updates rather than duplicating
    await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "alice", "current_task": "b"})
    await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "bot", "actor_type": "ai"})

    presence = (await client.get(f"/api/workspaces/{slug}/presence")).json()
    names = {p["actor_name"] for p in presence}
    assert names == {"alice", "bot"}
    alice = next(p for p in presence if p["actor_name"] == "alice")
    assert alice["current_task"] == "b"


# --- search + summary ---------------------------------------------------------


async def test_search_and_summary(client):
    slug = "search-ws"
    await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "implement redis bus"})
    await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "chose redis", "reason": "fan-out"})
    await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "carol"})

    search = (await client.get(f"/api/workspaces/{slug}/search", params={"q": "redis"})).json()
    assert len(search["tasks"]) == 1
    assert len(search["decisions"]) == 1

    summary = (await client.get(f"/api/workspaces/{slug}/summary")).json()
    assert summary["task_count"] == 1
    assert summary["open_task_count"] == 1
    assert summary["decision_count"] == 1
    assert "carol" in summary["active_developers"]


async def test_summary_autocreates_open_workspace(client):
    # Reading the summary of a brand-new slug creates it open with zero counts.
    summary = (await client.get("/api/workspaces/brand-new/summary")).json()
    assert summary["slug"] == "brand-new"
    assert summary["task_count"] == 0
