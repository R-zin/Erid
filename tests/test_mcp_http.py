"""The in-API MCP endpoint (/mcp, Streamable HTTP)."""

import importlib.util
import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn
from app import mcp_server
from app.main import app
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent


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
    yield base
    server.should_exit = True
    thread.join(timeout=5)


async def _call(base: str, headers: dict, tool: str, args: dict | None = None):
    async with (
        streamable_http_client(f"{base}/mcp", http_client=httpx.AsyncClient(headers=headers)) as (
            read,
            write,
            _,
        ),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(tool, args or {})


def _payload(result) -> object:
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


async def test_mcp_round_trip_uses_services_and_auth(live_server):
    slug = f"mcp-{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient() as h:
        key = (await h.post(f"{live_server}/api/workspaces", params={"slug": slug})).json()["api_key"]
        reader = (
            await h.post(
                f"{live_server}/api/workspaces/{slug}/actors",
                json={"name": "ro", "role": "reader"},
                headers={"X-API-Key": key},
            )
        ).json()["api_key"]

    owner = {"X-API-Key": key, "X-Erid-Workspace": slug}
    created = _payload(await _call(live_server, owner, "create_task", {"title": "via mcp"}))
    assert created["title"] == "via mcp"

    tasks = _payload(await _call(live_server, owner, "current_tasks"))
    assert [t["id"] for t in tasks] == [created["id"]]

    summary = _payload(await _call(live_server, owner, "workspace_summary"))
    assert summary["task_count"] == 1

    # Same rows over REST: one implementation behind both front ends.
    async with httpx.AsyncClient() as h:
        rest = (await h.get(f"{live_server}/api/workspaces/{slug}/tasks", headers={"X-API-Key": key})).json()
    assert [t["id"] for t in rest] == [created["id"]]

    # No credential → refused; a reader can read but not write.
    anon = await _call(live_server, {"X-Erid-Workspace": slug}, "current_tasks")
    assert anon.isError and "missing credentials" in anon.content[0].text
    ro = {"X-API-Key": reader, "X-Erid-Workspace": slug}
    assert len(_payload(await _call(live_server, ro, "current_tasks"))) == 1
    denied = await _call(live_server, ro, "create_task", {"title": "nope"})
    assert denied.isError and "write_tasks" in denied.content[0].text


async def test_mcp_slug_argument_overrides_header_and_is_required(live_server):
    slug = f"mcp-open-{uuid.uuid4().hex[:8]}"
    made = _payload(await _call(live_server, {}, "create_decision", {"title": "open ws", "slug": slug}))
    assert made["title"] == "open ws"
    missing = await _call(live_server, {}, "current_tasks")
    assert missing.isError and "X-Erid-Workspace" in missing.content[0].text


def _load_stdio_server():
    src = ROOT / "mcp-server" / "src"
    sys.path.insert(0, str(src))
    spec = importlib.util.spec_from_file_location("erid_stdio_server", src / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


async def test_http_and_stdio_servers_expose_the_same_surface():
    stdio = _load_stdio_server()
    http = mcp_server.mcp

    async def surface(server):
        tools = {t.name: set(t.inputSchema.get("properties", {})) for t in await server.list_tools()}
        templates = {r.uriTemplate for r in await server.list_resource_templates()}
        resources = {str(r.uri) for r in await server.list_resources()}
        prompts = {p.name for p in await server.list_prompts()}
        return tools, templates | resources, prompts

    assert await surface(http) == await surface(stdio)
