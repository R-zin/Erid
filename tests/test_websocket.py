"""Event-bus + WebSocket integration tests.

- ``test_event_bus_fanout`` exercises the publish→subscribe path directly
  against the app's bus (REST mutation publishes; a subscriber receives it).
- ``test_websocket_endpoint_live`` stands up a real uvicorn server on a throwaway
  port and reads an event over an actual WebSocket connection.

Both run against the in-memory event bus (EVENT_BUS_BACKEND=memory set in
conftest) and the app's SQLite engine.
"""

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
import websockets
from app.main import app

pytestmark = pytest.mark.asyncio


async def test_event_bus_fanout(client):
    from app.services.event_bus import get_event_bus

    slug = "ws-int"
    bus = await get_event_bus()
    received = []

    async def subscribe():
        async with bus.subscribe(slug) as queue:
            received.append(await asyncio.wait_for(queue.get(), timeout=2))

    task = asyncio.create_task(subscribe())
    await asyncio.sleep(0)  # let the subscriber register before publishing
    await client.post(f"/api/workspaces/{slug}/decisions", json={"title": "ws event", "made_by": "test"})
    await task

    assert received and received[0]["type"] == "decision_created"
    assert received[0]["data"]["title"] == "ws event"


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
    # wait for startup
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


async def test_websocket_endpoint_live(live_server):
    base, ws_base = live_server
    slug = "ws-live"
    async with httpx.AsyncClient() as h, websockets.connect(f"{ws_base}/api/workspaces/{slug}/ws") as ws:

        async def trigger():
            await asyncio.sleep(0.1)
            await h.post(f"{base}/api/workspaces/{slug}/decisions", json={"title": "live ws"})

        t = asyncio.create_task(trigger())
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        await t
        event = json.loads(msg)
        assert event["type"] == "decision_created"
        assert event["data"]["title"] == "live ws"
