"""Tests for the stdio hub bridge (``mcp-server/src/bridge.py``).

Covers the spec's cases 1-7:

1. Method→endpoint mapping (offline, ``httpx.MockTransport`` injected).
2. JSON-RPC round-trip / framing (matching ``id``; unknown method → ``-32601``).
3. NDJSON no-interleave (concurrent ``_notify`` + ``_respond`` stay parseable).
4. WS ``event`` notification (live server; REST create → ``decision_created``).
5. Reconnect/backoff (drop → ``status{connected:false}`` → re-``snapshot``
   → ``status{connected:true}``; backoff doubles and caps).
6. Presence payload round-trip + actor-keyed upsert.
7. ``*_deleted`` passthrough (REST DELETE → ``task_deleted`` carries ``data.id``).

The live tests reuse the same in-memory-SQLite + uvicorn-thread pattern as
``tests/test_websocket.py``: conftest's ``client`` fixture overrides ``get_db``
process-wide, so the background uvicorn server and the ASGI calls hit the same
DB and share the in-process event bus.
"""

import asyncio
import io
import json
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

# Point the app at in-memory SQLite + the in-process event bus BEFORE importing
# it (the engine binds at import time), mirroring ``tests/conftest.py``.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("EVENT_BUS_BACKEND", "memory")
sys.path.insert(0, str(ROOT / "api"))

from bridge import HubBridge  # noqa: E402
from client import APIClient  # noqa: E402

pytestmark = pytest.mark.asyncio

from collections.abc import AsyncGenerator  # noqa: E402

from app.db.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@pytest.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(db_engine) -> AsyncGenerator:
    """ASGI REST client over a shared in-memory DB (dependency-overridden ``get_db``).

    The override is process-global, so the background uvicorn server in
    ``live_server`` serves the same DB rows and event bus as these ASGI calls."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _default_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "DELETE":
        return httpx.Response(204)
    if request.url.path.endswith("/summary"):
        return httpx.Response(200, json={"slug": "ws", "task_count": 0})
    return httpx.Response(200, json=[])


def _make_bridge(handler=None, base_url="http://test", api_key="", token="", slug="ws"):
    """A HubBridge whose client hits a MockTransport, writing protocol to a buffer."""
    client = APIClient(base_url=base_url, api_key=api_key, token=token)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler or _default_handler), headers=dict(client._client.headers)
    )
    out = io.StringIO()
    return HubBridge(client=client, default_slug=slug, out=out), out


def _lines(out: io.StringIO) -> list[dict]:
    return [json.loads(ln) for ln in out.getvalue().splitlines() if ln.strip()]


async def _call(bridge: HubBridge, method: str, params: dict | None = None, request_id=1):
    await bridge._run_one({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})


# ---------------------------------------------------------------------------
# Case 1: method → endpoint mapping (offline)
# ---------------------------------------------------------------------------


async def test_method_endpoint_mapping():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(204)
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, json={"slug": "ws", "task_count": 0})
        if request.url.path == "/api/workspaces":
            return httpx.Response(200, json=[{"slug": "a", "name": "A"}])
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"query": "q", "decisions": [], "tasks": []})
        return httpx.Response(200, json=[])

    bridge, out = _make_bridge(handler)
    await _call(bridge, "getSummary")
    await _call(bridge, "listTasks", {"status": "todo"})
    await _call(bridge, "deleteTask", {"task_id": "T1"})
    await _call(bridge, "deleteDecision", {"decision_id": "D1"})
    await _call(bridge, "listDecisions")
    await _call(bridge, "listWorkspaces")
    await _call(bridge, "search", {"q": "q"})

    methods_paths = {(m, p) for m, p in seen}
    assert ("GET", "/api/workspaces/ws/summary") in methods_paths
    assert ("GET", "/api/workspaces/ws/tasks") in methods_paths
    assert ("DELETE", "/api/workspaces/ws/tasks/T1") in methods_paths
    assert ("DELETE", "/api/workspaces/ws/decisions/D1") in methods_paths
    assert ("GET", "/api/workspaces/ws/decisions") in methods_paths
    assert ("GET", "/api/workspaces") in methods_paths  # no slug (list workspaces)
    assert ("GET", "/api/workspaces/ws/search") in methods_paths
    await bridge.client.close()


async def test_delete_returns_null_on_204():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    bridge, out = _make_bridge(handler)
    await _call(bridge, "deleteTask", {"task_id": "T9"}, request_id=42)
    resp = _lines(out)[0]
    assert resp["id"] == 42
    assert resp["result"] is None  # 204 No Content → null result
    assert "error" not in resp
    await bridge.client.close()


async def test_workspaces_list_hits_no_slug_root():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=[{"slug": "a"}])

    bridge, _ = _make_bridge(handler)
    result = await bridge.client.list_workspaces()
    assert seen["path"] == "/api/workspaces"  # no {slug} segment
    assert result == [{"slug": "a"}]
    await bridge.client.close()


async def test_http_error_maps_to_minus_32000_with_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "forbidden"})

    bridge, out = _make_bridge(handler)
    await _call(bridge, "getSummary", request_id=7)
    resp = _lines(out)[0]
    assert resp["error"]["code"] == -32000
    assert resp["error"]["data"]["status"] == 403
    await bridge.client.close()


# ---------------------------------------------------------------------------
# Case 2: JSON-RPC round-trip / framing
# ---------------------------------------------------------------------------


async def test_jsonrpc_round_trip_matching_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"slug": "ws", "task_count": 3})

    bridge, out = _make_bridge(handler)
    await _call(bridge, "getSummary", request_id="abc-123")
    lines = _lines(out)
    assert len(lines) == 1
    resp = lines[0]
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == "abc-123"
    assert resp["result"]["task_count"] == 3
    await bridge.client.close()


async def test_unknown_method_minus_32601():
    bridge, out = _make_bridge(lambda r: httpx.Response(200, json={}))
    await _call(bridge, "noSuchMethod", request_id=5)
    resp = _lines(out)[0]
    assert resp["id"] == 5
    assert resp["error"]["code"] == -32601
    await bridge.client.close()


async def test_shutdown_returns_null_and_sets_shutdown():
    bridge, out = _make_bridge(lambda r: httpx.Response(200, json={}))
    # m_shutdown spawns a detached teardown task; run_one should respond null.
    await bridge._run_one({"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": {}})
    await asyncio.sleep(0)  # let the detached teardown run
    resp = _lines(out)[0]
    assert resp["id"] == 99
    assert resp["result"] is None
    assert bridge._shutdown.is_set()
    await bridge.client.close()


async def test_parse_error_minus_32700():
    """Malformed JSON on the wire → -32700 (drive _run_one-free path directly)."""
    bridge, out = _make_bridge()
    # Simulate what run() does with a bad line.
    await bridge._respond_error(None, -32700, "parse error: invalid JSON")
    resp = _lines(out)[0]
    assert resp["id"] is None
    assert resp["error"]["code"] == -32700
    await bridge.client.close()


# ---------------------------------------------------------------------------
# Case 3: NDJSON no-interleave under concurrency
# ---------------------------------------------------------------------------


async def test_ndjson_no_interleave():
    bridge, out = _make_bridge()
    big = {"blob": "x" * 4096}

    async def spam_respond(i):
        await bridge._respond(i, big)

    async def spam_notify(i):
        await bridge._notify("event", {"event": big, "i": i})

    await asyncio.gather(*[spam_respond(i) for i in range(50)], *[spam_notify(i) for i in range(50)])
    lines = out.getvalue().splitlines()
    assert len(lines) == 100
    for ln in lines:  # every line is a whole, independently-parseable message
        parsed = json.loads(ln)
        assert parsed["jsonrpc"] == "2.0"
        assert ("result" in parsed) or ("method" in parsed)
    await bridge.client.close()


# ---------------------------------------------------------------------------
# Live-server plumbing (cases 4, 5, 7)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def live_server():
    """Run the real app in a background uvicorn thread (same pattern as
    ``tests/test_websocket.py``). The conftest ``client`` fixture shares the DB
    and the in-process event bus, so REST writes reach this server's sockets."""
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
    yield base
    server.should_exit = True
    thread.join(timeout=5)


class _Collector:
    """Capture every bridge notification (written to a StringIO) so tests can
    await specific ones via ``wait_for``."""

    def __init__(self):
        self.out = io.StringIO()

    def parse(self) -> list[dict]:
        return [json.loads(ln) for ln in self.out.getvalue().splitlines() if ln.strip()]

    async def wait_for(self, predicate, timeout=8.0):
        """Poll the buffer until a message matching ``predicate`` appears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for msg in self.parse():
                if predicate(msg):
                    return msg
            await asyncio.sleep(0.02)
        raise TimeoutError("timed out waiting for bridge message")


async def _provision(slug: str, client) -> None:
    """Prime the workspace via the ASGI client (pytest event loop).

    A ``GET /summary`` auto-creates the workspace *open* (keyless) on the pytest
    loop and warms the shared in-memory connection, so the bridge's subsequent
    live-server (uvicorn-thread) requests reuse the row without an auth key.
    (We don't ``POST /api/workspaces`` — that mints a *secured* workspace.)"""
    r = await client.get(f"/api/workspaces/{slug}/summary")
    assert r.status_code == 200


async def test_ws_connect_and_event(live_server, client):
    """Case 4 (and the connect handshake): connect returns a snapshot, goes live,
    and a REST decision create is pushed as a ``decision_created`` event."""
    slug = f"bridge-{uuid.uuid4().hex[:8]}"
    await _provision(slug, client)
    bridge_client = APIClient(base_url=live_server)
    collector = _Collector()
    bridge = HubBridge(client=bridge_client, default_slug=slug, out=collector.out)

    snap = await bridge.m_connect({})
    assert "summary" in snap and "tasks" in snap and "decisions" in snap and "presence" in snap

    # The supervisor should signal it's connected.
    await collector.wait_for(lambda m: m.get("method") == "status" and m["params"]["connected"] is True)

    # Creating a decision over REST should surface as an `event` notification.
    await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "from-bridge", "made_by": "pytest"})
    evt = await collector.wait_for(
        lambda m: m.get("method") == "event" and m["params"]["event"]["type"] == "decision_created"
    )
    assert evt["params"]["event"]["data"]["title"] == "from-bridge"
    assert evt["params"]["event"]["workspace"] == slug

    await bridge._teardown()
    await bridge.client.close()


async def test_task_deleted_passthrough(live_server, client):
    """Case 7: REST DELETE /tasks/{id} → bridge emits ``task_deleted`` with data.id."""
    slug = f"bridge-{uuid.uuid4().hex[:8]}"
    await _provision(slug, client)
    bridge_client = APIClient(base_url=live_server)
    collector = _Collector()
    bridge = HubBridge(client=bridge_client, default_slug=slug, out=collector.out)
    await bridge.m_connect({})
    await collector.wait_for(lambda m: m.get("method") == "status" and m["params"]["connected"] is True)

    created = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "doomed"})).json()
    # Wait for the create event (so we know the socket is active post-create).
    await collector.wait_for(lambda m: m.get("method") == "event" and m["params"]["event"]["type"] == "task_created")
    await client.delete(f"/api/workspaces/{slug}/tasks/{created['id']}")
    evt = await collector.wait_for(
        lambda m: m.get("method") == "event" and m["params"]["event"]["type"] == "task_deleted"
    )
    assert evt["params"]["event"]["data"]["id"] == created["id"]

    await bridge._teardown()
    await bridge.client.close()


# ---------------------------------------------------------------------------
# Case 5: reconnect / backoff
# ---------------------------------------------------------------------------


async def test_reconnect_emits_offline_then_snapshot_then_online(live_server, client, monkeypatch):
    """Drop the WS → status(false) → re-snapshot → status(true)."""
    slug = f"bridge-{uuid.uuid4().hex[:8]}"
    await _provision(slug, client)
    bridge_client = APIClient(base_url=live_server)
    collector = _Collector()
    bridge = HubBridge(client=bridge_client, default_slug=slug, out=collector.out)

    # Shrink backoff so the reconnect loop is observable in-test.
    monkeypatch.setattr("bridge.BACKOFF_MIN", 0.05)
    monkeypatch.setattr("bridge.BACKOFF_MAX", 0.2)

    await bridge.m_connect({})
    await collector.wait_for(lambda m: m.get("method") == "status" and m["params"]["connected"] is True)

    # Kill the active websocket (server-side close) to force a drop + reconnect.
    while bridge._ws is None:
        await asyncio.sleep(0.02)
    await bridge._ws.close()

    # Expect offline, then a fresh snapshot, then back online.
    await collector.wait_for(lambda m: m.get("method") == "status" and m["params"]["connected"] is False)
    await collector.wait_for(lambda m: m.get("method") == "snapshot")
    await collector.wait_for(lambda m: m.get("method") == "status" and m["params"]["connected"] is True)

    await bridge._teardown()
    await bridge.client.close()


async def test_backoff_doubles_and_caps(monkeypatch):
    """Backoff sequence: BACKOFF_MIN → ×2 → ×2 … capped at BACKOFF_MAX."""
    import bridge as bridge_mod

    sleeps: list[float] = []

    async def spy_sleep_or_shutdown(shutdown, seconds):
        sleeps.append(seconds)
        return False  # never shut down during backoff; keep looping

    monkeypatch.setattr(bridge_mod, "_sleep_or_shutdown", spy_sleep_or_shutdown)

    class _FailingConnect:
        """Mimics websockets.connect(): an async CM whose entry always raises."""

        async def __aenter__(self):
            raise OSError("no server")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(bridge_mod.websockets, "connect", lambda *a, **k: _FailingConnect())

    bridge, _ = _make_bridge()
    task = asyncio.create_task(bridge.ws_supervisor("ws"))
    # Let several failed attempts accrue, then stop.
    for _ in range(400):
        await asyncio.sleep(0)
        if len(sleeps) >= 8:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(sleeps) >= 5
    assert sleeps[0] == bridge_mod.BACKOFF_MIN
    # Each subsequent delay doubles the previous, capped at BACKOFF_MAX.
    for prev, cur in zip(sleeps, sleeps[1:], strict=False):
        assert cur == min(prev * 2, bridge_mod.BACKOFF_MAX)
        assert cur <= bridge_mod.BACKOFF_MAX
    assert sleeps == sorted(sleeps)  # monotonic non-decreasing before the cap
    await bridge.client.close()


# ---------------------------------------------------------------------------
# Case 6: presence payload round-trip + actor-keyed upsert
# ---------------------------------------------------------------------------


async def test_presence_round_trip_and_upsert(live_server, client):
    slug = f"bridge-{uuid.uuid4().hex[:8]}"
    await _provision(slug, client)
    bridge_client = APIClient(base_url=live_server)
    bridge = HubBridge(client=bridge_client, default_slug=slug, out=io.StringIO())

    await bridge.m_postPresence(
        {"actor_name": "razin", "actor_type": "human", "current_file": "mcp-server/src/bridge.py"}
    )
    presence = await bridge.m_listPresence({})
    match = [p for p in presence if p["actor_name"] == "razin"]
    assert len(match) == 1
    assert match[0]["actor_type"] == "human"
    assert match[0]["current_file"] == "mcp-server/src/bridge.py"

    # A second post for the same actor upserts (still one row, updated file).
    await bridge.m_postPresence({"actor_name": "razin", "actor_type": "human", "current_file": "other.py"})
    presence = await bridge.m_listPresence({})
    match = [p for p in presence if p["actor_name"] == "razin"]
    assert len(match) == 1
    assert match[0]["current_file"] == "other.py"

    await bridge._teardown()
    await bridge.client.close()
