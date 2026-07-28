"""Workspace event bus.

Publishes domain events (task created, decision recorded, presence changed,
...) so WebSocket subscribers can stream real-time updates to dashboards.

Two backends share one interface:

- ``InProcessEventBus``: delivers events to subscribers in the current process.
  Zero dependencies — used as a fallback when Redis is unavailable and in
  single-instance deployments.
- ``RedisEventBus``: pub/sub over Redis so events fan out across *multiple*
  API instances. Any instance that handles a mutation publishes; every
  instance's WebSocket subscribers receive it.

Selection lives in ``get_event_bus()``: Redis is preferred, with an automatic
fallback to the in-process bus if Redis can't be reached (so local dev and
tests run without a broker).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from app.core.settings import settings

logger = logging.getLogger("context_hub.event_bus")

CHANNEL_PREFIX = "context-hub:workspace:"


def _channel(workspace_slug: str) -> str:
    return f"{CHANNEL_PREFIX}{workspace_slug}"


class InProcessEventBus:
    """Simple fan-out bus confined to the current process."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def publish(self, workspace_slug: str, event: dict[str, Any]) -> None:
        payload = {"workspace": workspace_slug, **event}
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            # Deliver only to subscribers interested in this workspace (each
            # records the slug it cares about as an attribute on its queue).
            if getattr(queue, "workspace_slug", None) == workspace_slug:
                queue.put_nowait(payload)

    @contextlib.asynccontextmanager
    async def subscribe(self, workspace_slug: str) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        queue.workspace_slug = workspace_slug  # type: ignore[attr-defined]
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers.discard(queue)


class RedisEventBus:
    """Pub/sub fan-out backed by Redis, for multi-instance deployments."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None

    async def _conn(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def ping(self) -> bool:
        try:
            conn = await self._conn()
            return bool(await conn.ping())
        except Exception:  # noqa: BLE001 - any connection error triggers fallback
            return False

    async def publish(self, workspace_slug: str, event: dict[str, Any]) -> None:
        conn = await self._conn()
        payload = json.dumps({"workspace": workspace_slug, **event})
        await conn.publish(_channel(workspace_slug), payload)

    @contextlib.asynccontextmanager
    async def subscribe(self, workspace_slug: str) -> AsyncIterator[asyncio.Queue]:
        conn = await self._conn()
        pubsub = conn.pubsub()
        await pubsub.subscribe(_channel(workspace_slug))
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        listener = asyncio.create_task(self._pump(pubsub, queue))
        try:
            yield queue
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await pubsub.unsubscribe(_channel(workspace_slug))
            await pubsub.aclose()

    @staticmethod
    async def _pump(pubsub: aioredis.client.PubSub, queue: asyncio.Queue) -> None:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                try:
                    data = json.loads(message["data"])
                except (ValueError, TypeError):
                    continue
                queue.put_nowait(data)
            else:
                # Yield to the event loop so cancellation is responsive.
                await asyncio.sleep(0.01)


_bus: InProcessEventBus | RedisEventBus | None = None


async def get_event_bus() -> InProcessEventBus | RedisEventBus:
    """Return the shared event bus, choosing Redis with in-process fallback."""
    global _bus
    if _bus is not None:
        return _bus

    if settings.event_bus_backend == "redis":
        candidate = RedisEventBus(settings.redis_url)
        if await candidate.ping():
            logger.info("event bus: using Redis backend (%s)", settings.redis_url)
            _bus = candidate
            return _bus
        logger.warning("event bus: Redis unreachable; falling back to in-process bus")

    logger.info("event bus: using in-process backend")
    _bus = InProcessEventBus()
    return _bus


def reset_event_bus() -> None:
    """Reset the cached bus (used by tests)."""
    global _bus
    _bus = None
