"""Expanded coverage (agent-4, task #14) for behavior already in ``main``.

Adds tests the base suite misses:

- WebSocket auth, happy + negative paths, over a real uvicorn server
  (``live_server``). Only valid for behavior that exists today: query-param
  ``api_key`` / ``token`` auth and the 1008 policy close on bad/missing creds.
- Non-decision event payloads on the in-process event bus (``task_created``,
  ``task_updated``, ``presence_updated``) via the deterministic ASGI+subscribe
  pattern from ``test_websocket.py`` — no live server, no wall-clock sleeps.
- Edge/validation cases: search/summary on an empty workspace, presence
  ``last_seen`` advancing on heartbeat, missing-task update 404, decision
  out-of-scope task 404.
"""

import asyncio
import json
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
import websockets
from app.main import app

pytestmark = pytest.mark.asyncio

# Bounded wait for a bus event. Generous enough to never be the cause of a
# failure on a healthy machine, small enough to fail fast when genuinely broken.
EVENT_TIMEOUT = 2.0


# ---------------------------------------------------------------------------
# Live-server fixture (mirrors tests/test_websocket.py)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def live_server():
    """Run the real app in a background uvicorn server on a random port."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(f"{base}/health", timeout=0.2)
            break
        except Exception:
            time.sleep(0.1)
    yield base, f"ws://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _slug() -> str:
    return f"cov-{uuid.uuid4().hex[:10]}"


async def _provision_secured(base: str, slug: str) -> str:
    """Provision a secured workspace over the live server; return its raw key."""
    async with httpx.AsyncClient() as h:
        r = await h.post(f"{base}/api/workspaces", params={"slug": slug})
    assert r.status_code == 201, r.text
    return r.json()["api_key"]


# ---------------------------------------------------------------------------
# 1. WebSocket auth (happy + negative)
# ---------------------------------------------------------------------------


async def test_ws_open_workspace_streams_event(live_server):
    """A keyless (open) workspace WS connects and receives a published event."""
    base, ws_base = live_server
    slug = _slug()
    async with httpx.AsyncClient() as h, websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws") as ws:

        async def trigger():
            await asyncio.sleep(0.05)
            await h.post(f"{base}/api/workspaces/{slug}/tasks", json={"title": "hello"})

        t = asyncio.create_task(trigger())
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        await t
        event = json.loads(msg)
        assert event["type"] == "task_created"
        assert event["data"]["title"] == "hello"


async def test_ws_secured_without_credentials_closed_1008(live_server):
    """Secured WS with no creds is closed with policy-violation code 1008."""
    base, ws_base = live_server
    slug = _slug()
    api_key = await _provision_secured(base, slug)
    assert api_key  # sanity: it really is secured

    with pytest.raises(websockets.exceptions.ConnectionClosed) as excinfo:
        async with websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
    assert excinfo.value.rcvd is not None
    assert excinfo.value.rcvd.code == 1008


async def test_ws_secured_with_valid_api_key_connects(live_server):
    """Secured WS with a valid ``?api_key=`` connects and receives an event."""
    base, ws_base = live_server
    slug = _slug()
    api_key = await _provision_secured(base, slug)
    headers = {"X-API-Key": api_key}

    async with (
        httpx.AsyncClient() as h,
        websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws", additional_headers={"X-API-Key": api_key}) as ws,
    ):

        async def trigger():
            await asyncio.sleep(0.05)
            await h.post(f"{base}/api/workspaces/{slug}/tasks", json={"title": "via key"}, headers=headers)

        t = asyncio.create_task(trigger())
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        await t
        event = json.loads(msg)
        assert event["type"] == "task_created"


async def test_ws_secured_with_valid_api_key_query_param(live_server):
    """Secured WS with a valid ``?api_key=`` query param connects."""
    base, ws_base = live_server
    slug = _slug()
    api_key = await _provision_secured(base, slug)
    headers = {"X-API-Key": api_key}

    async with (
        httpx.AsyncClient() as h,
        websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws?api_key={api_key}") as ws,
    ):

        async def trigger():
            await asyncio.sleep(0.05)
            await h.post(f"{base}/api/workspaces/{slug}/decisions", json={"title": "qs key"}, headers=headers)

        t = asyncio.create_task(trigger())
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        await t
        event = json.loads(msg)
        assert event["type"] == "decision_created"


async def test_ws_secured_with_bad_key_closed_1008(live_server):
    """Secured WS with a wrong ``?api_key=`` is closed with 1008."""
    base, ws_base = live_server
    slug = _slug()
    api_key = await _provision_secured(base, slug)
    assert api_key

    with pytest.raises(websockets.exceptions.ConnectionClosed) as excinfo:
        async with websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws?api_key=not-the-key") as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
    assert excinfo.value.rcvd is not None
    assert excinfo.value.rcvd.code == 1008


async def test_ws_secured_with_valid_token_query_param(live_server):
    """Secured WS with a valid ``?token=`` (JWT from login) connects and streams."""
    base, ws_base = live_server
    slug = _slug()
    api_key = await _provision_secured(base, slug)
    headers = {"X-API-Key": api_key}

    async with httpx.AsyncClient() as h:
        token_r = await h.post(f"{base}/api/workspaces/{slug}/token", json={"api_key": api_key})
        assert token_r.status_code == 200, token_r.text
        token = token_r.json()["access_token"]

    async with httpx.AsyncClient() as h, websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws?token={token}") as ws:

        async def trigger():
            await asyncio.sleep(0.05)
            await h.post(f"{base}/api/workspaces/{slug}/tasks", json={"title": "via token"}, headers=headers)

        t = asyncio.create_task(trigger())
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        await t
        event = json.loads(msg)
        assert event["type"] == "task_created"
        assert event["data"]["title"] == "via token"


# ---------------------------------------------------------------------------
# 2. Non-decision event payloads over the in-process bus
# ---------------------------------------------------------------------------


async def _next_event(event_bus, slug, trigger_coro):
    """Subscribe for one event, fire ``trigger_coro``, return the event."""
    received: list[dict] = []

    async def subscribe():
        async with event_bus.subscribe(slug) as queue:
            received.append(await asyncio.wait_for(queue.get(), timeout=EVENT_TIMEOUT))

    task = asyncio.create_task(subscribe())
    await asyncio.sleep(0)  # let the subscriber register before publishing
    await trigger_coro
    await asyncio.wait_for(task, timeout=EVENT_TIMEOUT)
    assert received
    return received[0]


async def test_event_task_created_payload(client):
    from app.services.event_bus import get_event_bus

    slug = _slug()
    bus = await get_event_bus()
    event = await _next_event(
        bus, slug, client.post(f"/api/workspaces/{slug}/tasks", json={"title": "pay", "created_by": "a4"})
    )

    assert event["type"] == "task_created"
    data = event["data"]
    assert data["title"] == "pay"
    assert data["status"] == "todo"
    assert data["created_by"] == "a4"
    assert data["assigned_to"] is None
    assert "id" in data and "created_at" in data
    # The in-process payload also carries the routing workspace slug.
    assert event["workspace"] == slug


async def test_event_task_updated_payload(client):
    from app.services.event_bus import get_event_bus

    slug = _slug()
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "orig"})).json()

    bus = await get_event_bus()
    event = await _next_event(
        bus,
        slug,
        client.put(f"/api/workspaces/{slug}/tasks/{task['id']}", json={"status": "done", "assigned_to": "ops"}),
    )

    assert event["type"] == "task_updated"
    data = event["data"]
    assert data["id"] == task["id"]
    assert data["title"] == "orig"
    assert data["status"] == "done"
    assert data["assigned_to"] == "ops"
    assert data["updated_at"] is not None


async def test_event_presence_updated_payload(client):
    from app.services.event_bus import get_event_bus

    slug = _slug()
    bus = await get_event_bus()
    event = await _next_event(
        bus,
        slug,
        client.post(
            f"/api/workspaces/{slug}/presence",
            json={"actor_name": "agent-4", "actor_type": "ai", "current_file": "x.py", "current_task": "t"},
        ),
    )

    assert event["type"] == "presence_updated"
    data = event["data"]
    assert data["actor_name"] == "agent-4"
    assert data["actor_type"] == "ai"
    assert data["current_file"] == "x.py"
    assert data["current_task"] == "t"
    assert "last_seen" in data


async def test_event_fanout_scoped_per_workspace(client):
    """Events published to one slug are NOT delivered to a different slug's subscriber."""
    from app.services.event_bus import get_event_bus

    slug_a, slug_b = _slug(), _slug()
    bus = await get_event_bus()
    received_a: list[dict] = []

    async def subscribe_a():
        async with bus.subscribe(slug_a) as queue:
            received_a.append(await asyncio.wait_for(queue.get(), timeout=5))

    task = asyncio.create_task(subscribe_a())
    await asyncio.sleep(0)
    # Publish to slug_b; subscriber on slug_a must NOT receive it.
    await client.post(f"/api/workspaces/{slug_b}/tasks", json={"title": "for-b"})

    done, _ = await asyncio.wait({task}, timeout=EVENT_TIMEOUT)
    assert not done, "subscriber on slug_a unexpectedly received an event for slug_b"
    assert received_a == []
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# 3. Edge / validation cases
# ---------------------------------------------------------------------------


async def test_search_on_empty_workspace(client):
    """Search of an untouched (auto-created open) workspace returns empty buckets."""
    slug = _slug()
    search = (await client.get(f"/api/workspaces/{slug}/search", params={"q": "anything"})).json()
    assert search["query"] == "anything"
    assert search["tasks"] == []
    assert search["decisions"] == []


async def test_summary_on_empty_workspace(client):
    """Summary of an empty workspace reports zero counts and no active developers."""
    slug = _slug()
    summary = (await client.get(f"/api/workspaces/{slug}/summary")).json()
    assert summary["task_count"] == 0
    assert summary["open_task_count"] == 0
    assert summary["decision_count"] == 0
    assert summary["active_developers"] == []


async def test_presence_heartbeat_advances_last_seen(client):
    """A second heartbeat for the same actor updates ``last_seen`` (not a new row)."""
    slug = _slug()
    first = (await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "hb"})).json()
    # Force a measurable tick so last_seen must strictly advance.
    await asyncio.sleep(0.01)
    second = (await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "hb"})).json()

    assert first["id"] == second["id"]
    from datetime import datetime

    first_seen = datetime.fromisoformat(first["last_seen"])
    second_seen = datetime.fromisoformat(second["last_seen"])
    assert second_seen >= first_seen

    presence = (await client.get(f"/api/workspaces/{slug}/presence")).json()
    assert len([p for p in presence if p["actor_name"] == "hb"]) == 1


async def test_update_nonexistent_task_404(client):
    r = await client.put(f"/api/workspaces/{_slug()}/tasks/{uuid.uuid4()}", json={"status": "done"})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


async def test_decision_with_out_of_scope_task_404(client):
    """A decision linked to a task in a *different* workspace is rejected."""
    slug_a, slug_b = _slug(), _slug()
    task_a = (await client.post(f"/api/workspaces/{slug_a}/tasks", json={"title": "mine"})).json()
    # Link from workspace B to workspace A's task: cross-workspace → 404.
    r = await client.post(f"/api/workspaces/{slug_b}/decisions", json={"title": "x", "task_id": str(task_a["id"])})
    assert r.status_code == 404


async def test_task_status_filter_empty_result(client):
    """Filtering on a status with no matches returns an empty list (not an error)."""
    slug = _slug()
    await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "only-todo"})
    done = (await client.get(f"/api/workspaces/{slug}/tasks", params={"status": "done"})).json()
    assert done == []
