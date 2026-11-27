"""Event outbox, WebSocket replay, attribution, hashed keys, and the Postgres bus."""

import asyncio
import hashlib
import json
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
import websockets
from app.core.settings import settings
from app.main import app
from app.models.models import Event, Workspace
from app.services import event_bus, events
from app.services.event_bus import NOTIFY_CHANNEL, PostgresEventBus, get_event_bus
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# conftest points DATABASE_URL at the test database before the app is imported.
TEST_DATABASE_URL = settings.database_url
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")
pg_only = pytest.mark.skipif(not IS_POSTGRES, reason="needs ERID_TEST_DATABASE_URL pointing at Postgres")


def _slug() -> str:
    return f"outbox-{uuid.uuid4().hex[:10]}"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def live_server():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
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


async def _recv(ws) -> dict:
    """Next non-keepalive frame."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if msg.get("type") != "ping":
            return msg


# ---------------------------------------------------------------------------
# Outbox rows + seq
# ---------------------------------------------------------------------------


async def test_mutations_write_outbox_rows_with_seq(client, db_engine):
    slug = _slug()
    bus = await get_event_bus()
    async with bus.subscribe(slug) as queue:
        await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "t1"})
        await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "d1"})
        first = await asyncio.wait_for(queue.get(), timeout=2)
        second = await asyncio.wait_for(queue.get(), timeout=2)

    assert [first["type"], second["type"]] == ["task_created", "decision_created"]
    assert second["seq"] > first["seq"]
    assert first["workspace"] == slug and "ts" in first

    session = async_sessionmaker(db_engine, class_=AsyncSession)
    async with session() as db:
        rows = (await db.execute(select(Event).order_by(Event.id))).scalars().all()
    assert [(r.id, r.type) for r in rows][-2:] == [(first["seq"], "task_created"), (second["seq"], "decision_created")]


async def test_presence_events_are_live_only(client, db_engine):
    slug = _slug()
    bus = await get_event_bus()
    async with bus.subscribe(slug) as queue:
        r = await client.post(f"/api/workspaces/{slug}/presence", json={"actor_name": "a"})
        assert r.status_code == 200, r.text
        event = await asyncio.wait_for(queue.get(), timeout=2)
    assert event["type"] == "presence_updated"
    assert "seq" not in event
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as db:
        assert (await db.execute(select(func.count()).select_from(Event))).scalar_one() == 0


async def test_failed_write_emits_nothing(client, db_engine):
    """A write that fails validation inside the service leaves no event behind."""
    slug = _slug()
    bus = await get_event_bus()
    async with bus.subscribe(slug) as queue:
        r = await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "x", "task_id": str(uuid.uuid4())})
        assert r.status_code == 404
        await asyncio.sleep(0.05)
        assert queue.empty()
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as db:
        assert (await db.execute(select(func.count()).select_from(Event))).scalar_one() == 0


# ---------------------------------------------------------------------------
# Replay (events_since + /ws?since=)
# ---------------------------------------------------------------------------


async def _workspace(db: AsyncSession, slug: str) -> Workspace:
    return (await db.execute(select(Workspace).where(Workspace.slug == slug))).scalars().one()


async def test_events_since_replays_only_this_workspace(client, db_engine):
    slug, other = _slug(), _slug()
    t1 = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "a"})).json()
    await client.post(f"/api/workspaces/{other}/tasks", json={"title": "noise"})
    await client.put(f"/api/workspaces/{slug}/tasks/{t1['id']}", json={"status": "done"})

    async with async_sessionmaker(db_engine, class_=AsyncSession)() as db:
        ws = await _workspace(db, slug)
        replay, complete = await events.events_since(db, ws, 0)
        assert complete
        assert [e["type"] for e in replay] == ["task_created", "task_updated"]
        # Resuming from the first event returns only what followed.
        tail, complete = await events.events_since(db, ws, replay[0]["seq"])
        assert complete and [e["seq"] for e in tail] == [replay[1]["seq"]]
        # Fully caught up.
        assert await events.events_since(db, ws, replay[1]["seq"]) == ([], True)


async def test_events_since_requires_resync_after_prune(client, db_engine):
    slug = _slug()
    for i in range(3):
        await client.post(f"/api/workspaces/{slug}/tasks", json={"title": f"t{i}"})
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as db:
        ws = await _workspace(db, slug)
        replay, _ = await events.events_since(db, ws, 0)
        first_seq = replay[0]["seq"]
        # Simulate retention removing the two oldest rows.
        await db.execute(delete(Event).where(Event.id <= replay[1]["seq"]))
        await db.commit()
        assert await events.events_since(db, ws, first_seq - 1) == ([], False)


async def test_events_since_requires_resync_when_too_far_behind(client, db_engine, monkeypatch):
    monkeypatch.setattr(events, "REPLAY_LIMIT", 2)
    slug = _slug()
    for i in range(3):
        await client.post(f"/api/workspaces/{slug}/tasks", json={"title": f"t{i}"})
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as db:
        assert await events.events_since(db, await _workspace(db, slug), 0) == ([], False)


async def test_ws_since_replays_missed_events_then_streams(live_server):
    base, ws_base = live_server
    slug = _slug()
    async with httpx.AsyncClient() as h:
        async with websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws") as ws:
            await asyncio.sleep(0.05)
            await h.post(f"{base}/api/workspaces/{slug}/decisions", json={"title": "seen"})
            seen = await _recv(ws)
        # Disconnected: these two are missed.
        await h.post(f"{base}/api/workspaces/{slug}/decisions", json={"title": "missed-1"})
        await h.post(f"{base}/api/workspaces/{slug}/decisions", json={"title": "missed-2"})

        async with websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws?since={seen['seq']}") as ws:
            replayed = [await _recv(ws), await _recv(ws)]
            await h.post(f"{base}/api/workspaces/{slug}/decisions", json={"title": "live"})
            live = await _recv(ws)

    assert [e["data"]["title"] for e in replayed] == ["missed-1", "missed-2"]
    assert live["data"]["title"] == "live"
    assert seen["seq"] < replayed[0]["seq"] < replayed[1]["seq"] < live["seq"]


async def test_ws_rejects_non_integer_since(live_server):
    _, ws_base = live_server
    async with websockets.connect(f"{ws_base}/api/workspaces/{_slug()}/ws?since=abc") as ws:
        with pytest.raises(websockets.ConnectionClosed) as exc:
            await asyncio.wait_for(ws.recv(), timeout=5)
    assert exc.value.rcvd.code == 1008


# ---------------------------------------------------------------------------
# Attribution + hashed workspace keys
# ---------------------------------------------------------------------------


async def test_actor_credentials_cannot_spoof_authorship(client, authed):
    slug, admin = authed
    actor = (
        await client.post(f"/api/workspaces/{slug}/actors", json={"name": "claude", "role": "writer"}, headers=admin)
    ).json()
    as_actor = {"X-API-Key": actor["api_key"]}

    d = await client.post(
        f"/api/workspaces/{slug}/decisions", json={"title": "x", "made_by": "someone-else"}, headers=as_actor
    )
    t = await client.post(
        f"/api/workspaces/{slug}/tasks", json={"title": "x", "created_by": "someone-else"}, headers=as_actor
    )
    h = await client.post(
        f"/api/workspaces/{slug}/handoffs", json={"summary": "x", "created_by": "someone-else"}, headers=as_actor
    )
    assert d.json()["made_by"] == "claude"
    assert t.json()["created_by"] == "claude"
    assert h.json()["created_by"] == "claude"


async def test_shared_credentials_keep_claimed_author(client, authed):
    slug, admin = authed  # legacy workspace key: identifies no one in particular
    d = await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "x", "made_by": "alice"}, headers=admin)
    assert d.json()["made_by"] == "alice"
    open_slug = _slug()
    t = await client.post(f"/api/workspaces/{open_slug}/tasks", json={"title": "x", "created_by": "bob"})
    assert t.json()["created_by"] == "bob"


async def test_workspace_key_is_stored_hashed(client, db_engine):
    slug = _slug()
    raw = (await client.post("/api/workspaces", params={"slug": slug})).json()["api_key"]
    async with async_sessionmaker(db_engine, class_=AsyncSession)() as db:
        ws = await _workspace(db, slug)
    assert ws.api_key_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in {getattr(ws, c.key) for c in Workspace.__table__.columns}
    # The raw key still authenticates; rotation invalidates it.
    headers = {"X-API-Key": raw}
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 200
    new = (await client.post(f"/api/workspaces/{slug}/rotate-key", headers=headers)).json()["api_key"]
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 403
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers={"X-API-Key": new})).status_code == 200


# ---------------------------------------------------------------------------
# Postgres LISTEN/NOTIFY bus
# ---------------------------------------------------------------------------


@pg_only
async def test_pg_bus_delivers_on_commit_only(db_engine):
    bus = PostgresEventBus(TEST_DATABASE_URL)
    assert await bus.start()
    try:
        async with bus.subscribe("pg-bus") as queue:
            payload = json.dumps({"workspace": "pg-bus", "type": "rolled_back", "data": {}})
            async with db_engine.connect() as conn:
                trans = await conn.begin()
                await conn.execute(text("SELECT pg_notify(:c, :p)"), {"c": NOTIFY_CHANNEL, "p": payload})
                await trans.rollback()
            payload = json.dumps({"workspace": "pg-bus", "type": "committed", "data": {}})
            async with db_engine.begin() as conn:
                await conn.execute(text("SELECT pg_notify(:c, :p)"), {"c": NOTIFY_CHANNEL, "p": payload})
            event = await asyncio.wait_for(queue.get(), timeout=5)
            assert event["type"] == "committed"
            assert queue.empty()
    finally:
        await bus.close()


@pg_only
async def test_pg_bus_end_to_end_with_oversize_event(client, monkeypatch):
    """A write fans out via pg_notify; an oversize event travels by reference."""
    bus = PostgresEventBus(TEST_DATABASE_URL)
    assert await bus.start()
    monkeypatch.setattr(event_bus, "_bus", bus)
    slug = _slug()
    try:
        async with bus.subscribe(slug) as queue:
            await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "small"})
            big_reason = "x" * 12_000  # past pg_notify's 8000-byte payload limit, under the 16k field cap
            await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "big", "reason": big_reason})
            small = await asyncio.wait_for(queue.get(), timeout=5)
            big = await asyncio.wait_for(queue.get(), timeout=5)
        assert small["data"]["title"] == "small"
        assert big["data"]["reason"] == big_reason and big["seq"] > small["seq"]
    finally:
        await bus.close()


@pg_only
async def test_hash_migration_converts_existing_raw_keys(db_engine):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    api_root = Path(__file__).resolve().parent.parent / "api"
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)

    await asyncio.to_thread(command.downgrade, cfg, "f7a8b9c0d1e2")
    try:
        async with db_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO workspaces (id, slug, name, api_key) VALUES (:id, 'legacy', 'legacy', 'raw-key')"),
                {"id": uuid.uuid4()},
            )
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")
    async with db_engine.connect() as conn:
        stored = (await conn.execute(text("SELECT api_key_hash FROM workspaces WHERE slug = 'legacy'"))).scalar_one()
    assert stored == hashlib.sha256(b"raw-key").hexdigest()
