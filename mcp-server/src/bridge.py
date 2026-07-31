"""AI Context Hub — stdio "hub bridge" for editor plugins.

A single-asyncio-loop JSON-RPC 2.0 server over **NDJSON** (one message per
``\\n``-terminated line) that owns *all* hub I/O on behalf of an editor frontend
(VS Code-family now; JetBrains later). It reuses the async :class:`APIClient`
(``client.py``) for REST, and maintains a WebSocket subscription so the editor
gets live ``event`` pushes.

Spawn it from a repo checkout so ``uv run`` resolves the project env:

    API_BASE=... WORKSPACE_SLUG=... WORKSPACE_API_KEY=... \\
        uv run python mcp-server/src/bridge.py

Wire protocol (both directions are JSON-RPC 2.0 over stdio, compact separators,
no embedded newlines):

- Requests carry ``id``; responses echo it with ``result`` or
  ``error{code,message,data}``. Handlers run concurrently, so responses may
  arrive out of order (correlate by ``id``).
- Bridge→editor pushes are *notifications* (no ``id``): ``event`` (a raw
  ``{workspace,type,data}`` WS frame), ``snapshot`` (authoritative resync), and
  ``status`` (``{connected: bool}``).

Error codes: ``httpx.HTTPStatusError`` → ``-32000`` with ``data.status=<http
status>`` (so the editor distinguishes 401/403 from 5xx); ``-32601`` unknown
method, ``-32602`` bad params, ``-32700`` parse error. All logging goes to
**stderr only** — stdout is the protocol channel.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from pathlib import Path

import httpx
import websockets

# Allow running both as ``python mcp-server/src/bridge.py`` (script) and as a
# module; ensure src/ is importable for ``client`` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import APIClient  # noqa: E402

logger = logging.getLogger("hub-bridge")

DEFAULT_SLUG = os.environ.get("WORKSPACE_SLUG", "")

# WS keepalive + reconnect-backoff bounds (mirror web/src/useWorkspace.js).
WS_PING_INTERVAL = 20
WS_PING_TIMEOUT = 20
BACKOFF_MIN = 1.0
BACKOFF_MAX = 30.0


class BadParams(Exception):
    """Raised by handlers when params are missing/malformed → JSON-RPC -32602."""


async def _sleep_or_shutdown(shutdown: asyncio.Event, seconds: float) -> bool:
    """Sleep ``seconds`` but wake early if ``shutdown`` fires.

    Returns True if shutdown was requested, False on a full timeout. Factored
    out so tests can spy on the backoff schedule without touching asyncio.
    """
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)
        return True
    except TimeoutError:
        return False


class HubBridge:
    def __init__(self, client: APIClient | None = None, default_slug: str | None = None, out=None) -> None:
        self.client = client or APIClient()
        # ``default_slug`` falls back to the WORKSPACE_SLUG env var when not given.
        self._default_slug = DEFAULT_SLUG if default_slug is None else default_slug
        self._out = out if out is not None else sys.stdout  # protocol sink (stdio by default)
        self._write_lock = asyncio.Lock()  # guards ALL stdout writes
        self._shutdown = asyncio.Event()
        self._ws_task: asyncio.Task | None = None
        self._ws_slug: str | None = None  # slug the WS supervisor is following
        self._ws = None  # currently-open websocket (None when disconnected)

    # -- stdout framing (NDJSON) ----------------------------------------------
    async def _write(self, message: dict) -> None:
        line = json.dumps(message, separators=(",", ":"), default=str)
        async with self._write_lock:
            self._out.write(line + "\n")
            self._out.flush()

    async def _respond(self, request_id, result) -> None:
        await self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _respond_error(self, request_id, code: int, message: str, data=None) -> None:
        error: dict = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        await self._write({"jsonrpc": "2.0", "id": request_id, "error": error})

    async def _notify(self, method: str, params) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # -- helpers --------------------------------------------------------------
    def _slug(self, params: dict) -> str:
        slug = params.get("slug") or self._default_slug
        if not slug:
            raise BadParams("no workspace slug provided and WORKSPACE_SLUG is not set")
        return slug

    # -- snapshot + WS supervisor ----------------------------------------------
    async def snapshot(self, slug: str) -> dict:
        """Authoritative workspace state: summary + tasks + decisions + presence."""
        summary, tasks, decisions, presence = await asyncio.gather(
            self.client.workspace_summary(slug),
            self.client.current_tasks(slug),
            self.client.recent_decisions(slug),
            self.client.active_developers(slug),
        )
        return {"summary": summary, "tasks": tasks, "decisions": decisions, "presence": presence}

    def _ws_url(self, slug: str) -> str:
        base = self.client._base  # http(s) base URL, e.g. http://localhost:8000
        ws_scheme = "wss" if base.startswith("https") else "ws"
        rest = base.split("://", 1)[1] if "://" in base else base
        url = f"{ws_scheme}://{rest}/api/workspaces/{slug}/ws"
        # Credential via query param (WS clients often can't set headers); token wins.
        token, key = self.client._resolve_credentials()
        if token:
            url += f"?token={token}"
        elif key:
            url += f"?api_key={key}"
        return url

    async def ws_supervisor(self, slug: str) -> None:
        """Maintain a WS subscription to ``slug`` forever, reconnecting with
        exponential backoff. Forwards every frame 1:1 as an ``event`` and, after
        a drop, re-syncs via a fresh ``snapshot`` (the authoritative resync)."""
        self._ws_slug = slug
        backoff = BACKOFF_MIN
        url = self._ws_url(slug)
        while not self._shutdown.is_set():
            try:
                async with websockets.connect(url, ping_interval=WS_PING_INTERVAL, ping_timeout=WS_PING_TIMEOUT) as ws:
                    self._ws = ws  # exposed for clean shutdown + tests
                    backoff = BACKOFF_MIN  # healthy connect resets backoff
                    await self._emit_status(True)
                    async for raw in ws:
                        frame = json.loads(raw)
                        await self._notify("event", {"event": frame})
                        if frame.get("type") == "workspace_deleted":
                            logger.info("workspace_deleted for %s; stopping WS supervisor", slug)
                            return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # connect failed, dropped, or protocol error
                logger.warning("WS connection to %s lost: %s", slug, exc)
            finally:
                self._ws = None

            if self._shutdown.is_set():
                return
            # Connection dropped (or never established): tell the editor, resync, back off.
            await self._emit_status(False)
            try:
                await self._emit_snapshot(slug)
            except Exception as exc:  # noqa: BLE001 — best-effort resync
                logger.warning("snapshot resync failed for %s: %s", slug, exc)
            if await _sleep_or_shutdown(self._shutdown, backoff):
                return  # shutdown requested during backoff
            backoff = min(backoff * 2, BACKOFF_MAX)

    async def _emit_status(self, connected: bool) -> None:
        await self._notify("status", {"connected": connected})

    async def _emit_snapshot(self, slug: str) -> None:
        await self._notify("snapshot", await self.snapshot(slug))

    def _restart_ws(self, slug: str) -> None:
        """(Re)start the WS supervisor for ``slug``, cancelling any prior one."""
        if self._ws_task is not None and not self._ws_task.done():
            self._ws_task.cancel()
        self._ws_task = asyncio.create_task(self.ws_supervisor(slug))

    # -- JSON-RPC method handlers ----------------------------------------------
    async def m_connect(self, params: dict):
        slug = self._slug(params)
        snap = await self.snapshot(slug)
        self._restart_ws(slug)
        return snap

    async def m_getSummary(self, params: dict):
        return await self.client.workspace_summary(self._slug(params))

    async def m_listTasks(self, params: dict):
        return await self.client.current_tasks(self._slug(params), status=params.get("status"))

    async def m_createTask(self, params: dict):
        title = params.get("title")
        if not title:
            raise BadParams("createTask requires 'title'")
        return await self.client.create_task(
            self._slug(params), title, assigned_to=params.get("assigned_to"), created_by=params.get("created_by")
        )

    async def m_updateTask(self, params: dict):
        task_id = params.get("task_id") or params.get("id")
        if not task_id:
            raise BadParams("updateTask requires 'task_id'")
        return await self.client.update_task(
            self._slug(params),
            task_id,
            status=params.get("status"),
            title=params.get("title"),
            assigned_to=params.get("assigned_to"),
        )

    async def m_deleteTask(self, params: dict):
        task_id = params.get("task_id") or params.get("id")
        if not task_id:
            raise BadParams("deleteTask requires 'task_id'")
        await self.client.delete_task(self._slug(params), task_id)
        return None

    async def m_taskDecisions(self, params: dict):
        task_id = params.get("task_id") or params.get("id")
        if not task_id:
            raise BadParams("taskDecisions requires 'task_id'")
        return await self.client.task_decisions(self._slug(params), task_id)

    async def m_listDecisions(self, params: dict):
        return await self.client.recent_decisions(self._slug(params), limit=params.get("limit", 20))

    async def m_createDecision(self, params: dict):
        title = params.get("title")
        if not title:
            raise BadParams("createDecision requires 'title'")
        return await self.client.create_decision(
            self._slug(params),
            title,
            reason=params.get("reason"),
            related_files=params.get("related_files"),
            made_by=params.get("made_by"),
            task_id=params.get("task_id"),
        )

    async def m_deleteDecision(self, params: dict):
        decision_id = params.get("decision_id") or params.get("id")
        if not decision_id:
            raise BadParams("deleteDecision requires 'decision_id'")
        await self.client.delete_decision(self._slug(params), decision_id)
        return None

    async def m_listPresence(self, params: dict):
        return await self.client.active_developers(self._slug(params))

    async def m_postPresence(self, params: dict):
        actor_name = params.get("actor_name")
        if not actor_name:
            raise BadParams("postPresence requires 'actor_name'")
        return await self.client.update_presence(
            self._slug(params),
            actor_name,
            actor_type=params.get("actor_type", "ai"),
            current_file=params.get("current_file"),
            current_task=params.get("current_task"),
        )

    async def m_search(self, params: dict):
        q = params.get("q") or params.get("query")
        if not q:
            raise BadParams("search requires 'q'")
        return await self.client.search_context(self._slug(params), q, limit=params.get("limit"))

    async def m_listWorkspaces(self, params: dict):
        return await self.client.list_workspaces()

    async def m_shutdown(self, params: dict):
        # Respond first (run() cancels remaining tasks after run_one returns),
        # then tear down in a detached task so we can still send the response.
        asyncio.create_task(self._teardown())
        return None

    METHODS = {
        "connect": m_connect,
        "getSummary": m_getSummary,
        "listTasks": m_listTasks,
        "createTask": m_createTask,
        "updateTask": m_updateTask,
        "deleteTask": m_deleteTask,
        "taskDecisions": m_taskDecisions,
        "listDecisions": m_listDecisions,
        "createDecision": m_createDecision,
        "deleteDecision": m_deleteDecision,
        "listPresence": m_listPresence,
        "postPresence": m_postPresence,
        "search": m_search,
        "listWorkspaces": m_listWorkspaces,
        "shutdown": m_shutdown,
    }

    # -- dispatch --------------------------------------------------------------
    async def _run_one(self, request: dict) -> None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        handler = self.METHODS.get(method)
        if handler is None:
            await self._respond_error(request_id, -32601, f"method not found: {method!r}")
            return
        try:
            result = await handler(self, params)
            await self._respond(request_id, result)
        except BadParams as exc:
            await self._respond_error(request_id, -32602, str(exc))
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            await self._respond_error(request_id, -32000, f"hub returned HTTP {status}", data={"status": status})
        except TypeError as exc:  # unexpected/mistyped params reaching the client
            await self._respond_error(request_id, -32602, f"invalid params: {exc}")
        except Exception as exc:  # noqa: BLE001 — never let one request kill the loop
            logger.exception("handler for %s failed", method)
            await self._respond_error(request_id, -32603, f"internal error: {exc}")

    # -- lifecycle ---------------------------------------------------------------
    async def _teardown(self) -> None:
        self._shutdown.set()
        if self._ws_task is not None:
            self._ws_task.cancel()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        await self.client.close()

    def request_shutdown(self) -> None:
        """Signal-safe shutdown trigger (SIGTERM/SIGINT handlers)."""
        self._shutdown.set()

    def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            # e.g. add_signal_handler unsupported on Windows / non-main thread
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, self.request_shutdown)

    async def run(self) -> int:
        self._install_signal_handlers(asyncio.get_running_loop())
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        pending: set[asyncio.Task] = set()
        try:
            while not self._shutdown.is_set():
                line = await reader.readline()
                if not line:  # EOF on stdin ⇒ editor closed the pipe ⇒ shutdown
                    logger.info("stdin EOF; shutting down")
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    await self._respond_error(None, -32700, "parse error: invalid JSON")
                    continue
                task = asyncio.create_task(self._run_one(request))
                pending.add(task)
                task.add_done_callback(pending.discard)
        finally:
            if not self._shutdown.is_set():
                await self._teardown()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        return 0


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[hub-bridge] %(levelname)s %(message)s")
    sys.exit(asyncio.run(HubBridge().run()))


if __name__ == "__main__":
    main()
