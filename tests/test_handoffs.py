"""Integration tests for session handoffs: REST CRUD, lifecycle, auth, and
summary/task-context wiring.

Run against an isolated SQLite DB via the fixtures in conftest.py.
"""

import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def _make_actor(client, slug, workspace_key, name, permissions):
    """Mint an actor with explicit permissions; return its API key."""
    r = await client.post(
        f"/api/workspaces/{slug}/actors",
        headers={"X-API-Key": workspace_key},
        json={"name": name, "role": "reader", "permissions": permissions},
    )
    assert r.status_code == 201
    return r.json()["api_key"]


# --- CRUD ---------------------------------------------------------------------


async def test_handoff_create_get_and_list(client):
    slug = "handoffs-ws"
    created = await client.post(
        f"/api/workspaces/{slug}/handoffs",
        json={
            "summary": "Built the handoffs API slice",
            "branch": "feature/handoffs",
            "files_changed": "api/app/models/models.py\napi/app/api/routes/context.py",
            "commands_run": "pytest tests/test_handoffs.py — 12 passed",
            "blockers": "none",
            "next_action": "Wire the MCP tools",
            "created_by": "claude",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "open"
    assert body["summary"] == "Built the handoffs API slice"
    assert body["created_by"] == "claude"
    assert body["acknowledged_at"] is None

    got = await client.get(f"/api/workspaces/{slug}/handoffs/{body['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]

    listed = (await client.get(f"/api/workspaces/{slug}/handoffs")).json()
    assert [h["id"] for h in listed] == [body["id"]]


async def test_handoff_requires_summary(client):
    r = await client.post("/api/workspaces/handoffs-val/handoffs", json={"summary": ""})
    assert r.status_code == 422


async def test_handoff_defaults_creator_to_actor(client, authed):
    slug, headers = authed  # legacy workspace key authenticates as the slug-named owner
    r = await client.post(f"/api/workspaces/{slug}/handoffs", headers=headers, json={"summary": "s"})
    assert r.status_code == 201
    assert r.json()["created_by"] == slug


async def test_handoff_missing_404(client):
    r = await client.get(f"/api/workspaces/handoffs-ws/handoffs/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_handoff_delete(client):
    slug = "handoffs-del"
    hid = (await client.post(f"/api/workspaces/{slug}/handoffs", json={"summary": "doomed"})).json()["id"]
    assert (await client.delete(f"/api/workspaces/{slug}/handoffs/{hid}")).status_code == 204
    assert (await client.get(f"/api/workspaces/{slug}/handoffs/{hid}")).status_code == 404


# --- lifecycle ----------------------------------------------------------------


async def test_handoff_lifecycle_and_status_filter(client):
    slug = "handoffs-life"
    hid = (await client.post(f"/api/workspaces/{slug}/handoffs", json={"summary": "pick me up"})).json()["id"]

    acked = await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/acknowledge")
    assert acked.status_code == 200
    assert acked.json()["status"] == "acknowledged"
    assert acked.json()["acknowledged_at"] is not None

    # Acknowledging twice is a no-op (idempotent).
    acked2 = await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/acknowledge")
    assert acked2.status_code == 200
    assert acked2.json()["acknowledged_at"] == acked.json()["acknowledged_at"]

    resolved = await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"] is not None

    # Resolving twice is a no-op; acknowledging a resolved handoff conflicts.
    assert (await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/resolve")).status_code == 200
    assert (await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/acknowledge")).status_code == 409

    # Status filter: resolved no longer shows up under open.
    open_list = (await client.get(f"/api/workspaces/{slug}/handoffs", params={"status": "open"})).json()
    assert open_list == []
    resolved_list = (await client.get(f"/api/workspaces/{slug}/handoffs", params={"status": "resolved"})).json()
    assert [h["id"] for h in resolved_list] == [hid]


# --- task linkage + summary ---------------------------------------------------


async def test_task_handoffs_and_workspace_summary(client):
    slug = "handoffs-task"
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "ship it"})).json()
    other = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "unrelated"})).json()

    r = await client.post(
        f"/api/workspaces/{slug}/handoffs",
        json={"summary": "half done", "task_id": task["id"]},
    )
    assert r.status_code == 201

    linked = (await client.get(f"/api/workspaces/{slug}/tasks/{task['id']}/handoffs")).json()
    assert [h["summary"] for h in linked] == ["half done"]
    assert (await client.get(f"/api/workspaces/{slug}/tasks/{other['id']}/handoffs")).json() == []

    # Open handoffs surface in the workspace summary.
    summary = (await client.get(f"/api/workspaces/{slug}/summary")).json()
    assert summary["open_handoff_count"] == 1

    # Handoffs survive their task being deleted (task_id SET NULL).
    assert (await client.delete(f"/api/workspaces/{slug}/tasks/{task['id']}")).status_code == 204
    still = (await client.get(f"/api/workspaces/{slug}/handoffs/{r.json()['id']}")).json()
    assert still["task_id"] is None


async def test_handoff_rejects_unknown_task(client):
    r = await client.post(
        "/api/workspaces/handoffs-badtask/handoffs",
        json={"summary": "s", "task_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


# --- authorization -------------------------------------------------------------


async def test_handoffs_require_auth_on_secured_workspace(client, authed):
    slug, _ = authed
    assert (await client.get(f"/api/workspaces/{slug}/handoffs")).status_code == 401
    assert (await client.post(f"/api/workspaces/{slug}/handoffs", json={"summary": "s"})).status_code == 401


async def test_handoffs_writer_can_write_reader_cannot(client, authed):
    slug, headers = authed
    workspace_key = headers["X-API-Key"]
    writer_key = await _make_actor(client, slug, workspace_key, "writer-bot", ["read", "write_handoffs"])
    reader_key = await _make_actor(client, slug, workspace_key, "reader-bot", ["read"])

    # Writer: create + lifecycle transitions succeed.
    r = await client.post(
        f"/api/workspaces/{slug}/handoffs",
        headers={"X-API-Key": writer_key},
        json={"summary": "writer's handoff"},
    )
    assert r.status_code == 201
    assert r.json()["created_by"] == "writer-bot"
    hid = r.json()["id"]
    assert (
        await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/acknowledge", headers={"X-API-Key": writer_key})
    ).status_code == 200
    assert (
        await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/resolve", headers={"X-API-Key": writer_key})
    ).status_code == 200

    # Reader: reads fine, every mutation is 403 with a precise message.
    assert (await client.get(f"/api/workspaces/{slug}/handoffs", headers={"X-API-Key": reader_key})).status_code == 200
    for method, url, kwargs in [
        ("post", f"/api/workspaces/{slug}/handoffs", {"json": {"summary": "s"}}),
        ("post", f"/api/workspaces/{slug}/handoffs/{hid}/acknowledge", {}),
        ("post", f"/api/workspaces/{slug}/handoffs/{hid}/resolve", {}),
        ("delete", f"/api/workspaces/{slug}/handoffs/{hid}", {}),
    ]:
        resp = await getattr(client, method)(url, headers={"X-API-Key": reader_key}, **kwargs)
        assert resp.status_code == 403, (method, url)
        assert "write_handoffs" in resp.json()["detail"]


# --- real-time -----------------------------------------------------------------


async def test_handoff_events_publish(client):
    from app.services.event_bus import get_event_bus

    slug = "handoffs-ws-events"
    bus = await get_event_bus()
    received = []

    import asyncio

    async def subscribe(n):
        async with bus.subscribe(slug) as queue:
            for _ in range(n):
                received.append(await asyncio.wait_for(queue.get(), timeout=2))

    task = asyncio.create_task(subscribe(2))
    await asyncio.sleep(0)
    hid = (await client.post(f"/api/workspaces/{slug}/handoffs", json={"summary": "evt"})).json()["id"]
    await client.post(f"/api/workspaces/{slug}/handoffs/{hid}/acknowledge")
    await task

    assert [e["type"] for e in received] == ["handoff_created", "handoff_updated"]
    assert received[0]["data"]["id"] == hid
    assert received[1]["data"]["status"] == "acknowledged"
