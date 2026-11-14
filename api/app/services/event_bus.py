"""Workspace event bus: fans committed domain events out to WebSocket subscribers.

Two backends share one interface (``publish`` / ``subscribe``):

- ``InProcessEventBus``: delivers events to subscribers in the current process.
  Zero dependencies; used with SQLite, in tests, and as the fallback.
- ``PostgresEventBus``: cross-instance fan-out over Postgres ``LISTEN/NOTIFY``.
  Producers call ``pg_notify`` *inside* the transaction that makes the change
  (see :mod:`app.services.events`), and Postgres only delivers a notification
  when that transaction commits. So a subscriber never sees an event for a change
  that rolled back, and a committed change can't lose its event to a crash
  between "commit" and "publish". Each API process holds one listening
  connection and fans notifications out to its own subscribers in-process.

This replaces the earlier Redis pub/sub backend: Postgres is already a hard
dependency, so Redis was a second stateful service that bought nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.core.settings import settings

logger = logging.getLogger("context_hub.event_bus")

# One channel for every workspace; the payload names the workspace. Channel
# names are identifiers in Postgres, so keep it simple and lowercase.
NOTIFY_CHANNEL = "erid_events"
# pg_notify payloads must be < 8000 bytes. Larger envelopes are sent as a
# reference ({"workspace", "ref": seq}) and the listener loads the outbox row.
NOTIFY_INLINE_LIMIT = 7000

# Reconnect backoff for the LISTEN connection.
_BACKOFF_MIN = 1.0
_BACKOFF_MAX = 30.0


def _offer(queue: asyncio.Queue, payload: dict[str, Any]) -> None:
    """Hand an event to one subscriber, dropping it if that subscriber is behind.

    A subscriber that stops draining its queue (a WebSocket client on a slow or
    half-open connection) must not be able to break anyone else: an unguarded
    ``put_nowait`` raises ``QueueFull`` and would abort delivery to the remaining
    subscribers mid-publish. Dropping the event for the one slow subscriber,
    loudly, is the containable failure; that client can resync with ``?since=``.
    """
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        logger.warning(
            "event bus: subscriber queue full (%s); dropping '%s' event",
            getattr(queue, "workspace_slug", "unknown workspace"),
            payload.get("type", "?"),
        )


class InProcessEventBus:
    """Simple fan-out bus confined to the current process."""

    #: Producers must call :meth:`publish` after commit (no transactional hook).
    transactional = False

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, workspace_slug: str, event: dict[str, Any]) -> None:
        self.deliver(workspace_slug, {"workspace": workspace_slug, **event})

    def deliver(self, workspace_slug: str, payload: dict[str, Any]) -> None:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for queue in list(self._subscribers.get(workspace_slug, ())):
            loop = queue.loop  # type: ignore[attr-defined]
            if loop is current:
                _offer(queue, payload)
            elif not loop.is_closed():
                # asyncio.Queue isn't thread-safe: a put from another thread's
                # loop wouldn't wake this subscriber's loop, so the event would
                # sit until something else did. Hand it over on the owner loop.
                loop.call_soon_threadsafe(_offer, queue, payload)

    @contextlib.asynccontextmanager
    async def subscribe(self, workspace_slug: str) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        queue.workspace_slug = workspace_slug  # type: ignore[attr-defined]  # for _offer's log line
        queue.loop = asyncio.get_running_loop()  # type: ignore[attr-defined]  # owner loop, for deliver()
        self._subscribers.setdefault(workspace_slug, set()).add(queue)
        try:
            yield queue
        finally:
            subs = self._subscribers.get(workspace_slug)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subscribers.pop(workspace_slug, None)


def asyncpg_dsn(database_url: str) -> str:
    """Turn a SQLAlchemy ``postgresql+asyncpg://`` URL into a plain asyncpg DSN."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class PostgresEventBus(InProcessEventBus):
    """Cross-instance fan-out over Postgres ``LISTEN/NOTIFY``.

    ``publish`` is only used for events that are not tied to a transaction; the
    normal path is :func:`app.services.events.emit`, which issues ``pg_notify``
    in the producer's own transaction. Every instance (including the producer)
    receives the notification on its listener and delivers it locally.
    """

    transactional = True

    def __init__(self, database_url: str) -> None:
        super().__init__()
        self._dsn = asyncpg_dsn(database_url)
        self._conn = None
        self._supervisor: asyncio.Task | None = None
        self._ready = asyncio.Event()

    async def start(self, timeout: float = 5.0) -> bool:
        """Start the listener; return ``False`` if Postgres can't be reached."""
        import asyncpg

        try:
            await self._connect(asyncpg)
        except Exception as exc:  # noqa: BLE001 - any connect failure means fallback
            logger.warning("event bus: Postgres listener could not connect (%s)", exc)
            return False
        self._supervisor = asyncio.create_task(self._supervise(asyncpg))
        return True

    async def _connect(self, asyncpg) -> None:
        conn = await asyncpg.connect(self._dsn)
        await conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
        lost = asyncio.Event()
        conn.add_termination_listener(lambda _c: lost.set())
        self._conn = conn
        self._lost = lost
        self._ready.set()

    async def _supervise(self, asyncpg) -> None:
        """Reconnect the LISTEN connection with backoff whenever it drops."""
        backoff = _BACKOFF_MIN
        while True:
            await self._lost.wait()
            self._ready.clear()
            logger.warning("event bus: lost Postgres listener connection; reconnecting")
            while True:
                await asyncio.sleep(backoff)
                try:
                    await self._connect(asyncpg)
                    backoff = _BACKOFF_MIN
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("event bus: reconnect failed (%s)", exc)
                    backoff = min(backoff * 2, _BACKOFF_MAX)

    async def close(self) -> None:
        if self._supervisor is not None:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
        if self._conn is not None:
            with contextlib.suppress(Exception):
                await self._conn.close()

    def _on_notify(self, _conn, _pid: int, _channel: str, payload: str) -> None:
        try:
            message = json.loads(payload)
        except ValueError:
            return
        slug = message.get("workspace")
        if not slug or slug not in self._subscribers:
            return  # nobody here cares; skip the outbox read for referenced events
        if "ref" in message:
            asyncio.get_running_loop().create_task(self._deliver_ref(slug, int(message["ref"])))
        else:
            self.deliver(slug, message)

    async def _deliver_ref(self, slug: str, seq: int) -> None:
        from app.services.events import load_envelope

        envelope = await load_envelope(slug, seq)
        if envelope is not None:
            self.deliver(slug, envelope)

    async def publish(self, workspace_slug: str, event: dict[str, Any]) -> None:
        payload = notify_payload({"workspace": workspace_slug, **event})
        await self._ready.wait()
        await self._conn.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, payload)


def notify_payload(envelope: dict[str, Any]) -> str:
    """Serialize an envelope for ``pg_notify``, by reference if it's too large."""
    raw = json.dumps(envelope, separators=(",", ":"), default=str)
    if len(raw.encode()) <= NOTIFY_INLINE_LIMIT or envelope.get("seq") is None:
        return raw
    return json.dumps({"workspace": envelope["workspace"], "ref": envelope["seq"]})


_bus: InProcessEventBus | None = None


def _wanted_backend() -> str:
    backend = settings.event_bus_backend.strip().lower()
    if backend in ("postgres", "memory"):
        return backend
    if backend not in ("", "auto"):
        logger.warning("event bus: unknown EVENT_BUS_BACKEND=%r; choosing automatically", backend)
    return "postgres" if settings.database_url.startswith("postgresql") else "memory"


async def get_event_bus() -> InProcessEventBus:
    """Return the shared event bus, choosing Postgres with in-process fallback."""
    global _bus
    if _bus is not None:
        return _bus

    if _wanted_backend() == "postgres":
        candidate = PostgresEventBus(settings.database_url)
        if await candidate.start():
            logger.info("event bus: using Postgres LISTEN/NOTIFY")
            _bus = candidate
            return _bus
        logger.warning("event bus: falling back to in-process bus (single instance only)")

    logger.info("event bus: using in-process backend")
    _bus = InProcessEventBus()
    return _bus


async def close_event_bus() -> None:
    """Stop the Postgres bus's LISTEN connection on app shutdown.

    The in-process bus holds no resources and is left in place: dropping it
    would strand subscribers still attached to it (e.g. another server's
    lifespan ending in the same process while sockets are open).
    """
    global _bus
    if isinstance(_bus, PostgresEventBus):
        await _bus.close()
        _bus = None


def reset_event_bus() -> None:
    """Forget the cached bus (used by tests)."""
    global _bus
    _bus = None
