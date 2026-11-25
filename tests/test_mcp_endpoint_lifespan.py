"""Overlapping API lifespans must not leave ``/mcp`` without a session manager.

The ``/mcp`` endpoint is a process-wide singleton, while each API lifespan (one
per uvicorn server, e.g. one per live-server test) gives it a fresh session
manager. If an older server finishes shutting down after a newer one has
started, its teardown must not clear the newer server's manager — that left
``/mcp`` answering 503 "MCP endpoint is not running" intermittently in CI.

Each lifespan runs in its own task, as each server does in practice.
"""

import asyncio

import pytest
from app.mcp_server import MCPEndpoint

pytestmark = pytest.mark.asyncio


class _Lifespan:
    """Hold ``ep.lifespan()`` open in a dedicated task until ``stop()``."""

    def __init__(self, ep: MCPEndpoint) -> None:
        self._ep = ep
        self._started = asyncio.Event()
        self._release = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        async with self._ep.lifespan():
            self._started.set()
            await self._release.wait()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await self._started.wait()

    async def stop(self) -> None:
        self._release.set()
        await self._task


async def test_late_shutdown_of_old_lifespan_keeps_new_manager():
    ep = MCPEndpoint()
    old, new = _Lifespan(ep), _Lifespan(ep)

    await old.start()
    await new.start()
    new_manager = ep._active_manager()

    await old.stop()  # the old server finishes shutting down last
    assert ep._active_manager() is new_manager

    await new.stop()
    assert ep._active_manager() is None


async def test_newest_lifespan_wins_and_older_one_resumes():
    ep = MCPEndpoint()
    old, new = _Lifespan(ep), _Lifespan(ep)

    await old.start()
    old_manager = ep._active_manager()
    await new.start()
    assert ep._active_manager() is not old_manager

    await new.stop()
    assert ep._active_manager() is old_manager

    await old.stop()
    assert ep._active_manager() is None
