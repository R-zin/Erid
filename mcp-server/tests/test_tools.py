"""Integration tests for the MCP tools against a real API instance.

Stands up the actual FastAPI app (uvicorn subprocess, ephemeral SQLite file) on
a throwaway port, then drives the MCP ``APIClient`` — the exact code the
``server.py`` tools call — through a full read/write round trip over real HTTP.

To run against an already-running API instead, set ``ERID_LIVE_API`` (and
``ERID_LIVE_API_KEY``); the in-process server is then skipped.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from client import APIClient  # noqa: E402

LIVE_API = os.environ.get("ERID_LIVE_API", "")
LIVE_KEY = os.environ.get("ERID_LIVE_API_KEY", "")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def api_base():
    """Yield (base_url, api_key) for a live or freshly-spawned API."""
    if LIVE_API:
        yield LIVE_API, LIVE_KEY
        return

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        port = _free_port()
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
            "EVENT_BUS_BACKEND": "memory",
            "VIRTUAL_ENV": "",  # ensure uv targets the project env
            "PYTHONPATH": str(ROOT / "api"),
        }
        proc = subprocess.Popen(
            ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT / "api",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    httpx.get(f"{base}/health", timeout=0.3)
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(0.1)
            else:
                raise RuntimeError("API subprocess did not become healthy")
            yield base, ""
        finally:
            proc.terminate()
            proc.wait(timeout=10)


async def _round_trip(base: str, key: str) -> None:
    client = APIClient(base_url=base, api_key=key)
    slug = f"mcp-test-{uuid.uuid4().hex[:8]}"

    created = await client.create_task(slug, "integration task", created_by="pytest")
    assert created["title"] == "integration task"
    assert created["status"] == "todo"

    updated = await client.update_task(slug, created["id"], status="in_progress")
    assert updated["status"] == "in_progress"

    decision = await client.create_decision(slug, "test decision", reason="verify tools", made_by="pytest")
    assert decision["title"] == "test decision"

    await client.update_presence(slug, "pytest", current_task="integration test")

    tasks = await client.current_tasks(slug)
    assert any(t["id"] == created["id"] for t in tasks)

    open_tasks = await client.current_tasks(slug, status="in_progress")
    assert any(t["id"] == created["id"] for t in open_tasks)

    decisions = await client.recent_decisions(slug)
    assert any(d["id"] == decision["id"] for d in decisions)

    devs = await client.active_developers(slug)
    assert any(d["actor_name"] == "pytest" for d in devs)

    summary = await client.workspace_summary(slug)
    assert summary["task_count"] == 1
    assert summary["decision_count"] == 1
    assert "pytest" in summary["active_developers"]

    search = await client.search_context(slug, "integration")
    assert any(t["id"] == created["id"] for t in search["tasks"])

    await client.close()


@pytest.mark.asyncio
async def test_full_tool_round_trip(api_base):
    base, key = api_base
    await _round_trip(base, key)


@pytest.mark.asyncio
async def test_list_workspaces_index(api_base):
    """A workspace provisioned over the API shows up in the cross-workspace index."""
    base, key = api_base
    client = APIClient(base_url=base, api_key=key)
    slug = f"mcp-test-{uuid.uuid4().hex[:8]}"

    # Provision the workspace (first write materializes it on the hub).
    await client.create_task(slug, "index probe", created_by="pytest")

    workspaces = await client.list_workspaces()
    assert isinstance(workspaces, list)
    assert any(w["slug"] == slug for w in workspaces)

    await client.close()
