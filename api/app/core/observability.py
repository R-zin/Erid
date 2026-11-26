"""Metrics, load shedding and readiness for running many API replicas.

* :class:`TrafficMiddleware` (pure ASGI, so it sees WebSockets too) records
  Prometheus metrics per route template and sheds load: past
  ``ERID_MAX_INFLIGHT_REQUESTS`` concurrent HTTP requests it answers 503 with
  ``Retry-After``, and past ``ERID_MAX_WEBSOCKETS`` open streams it refuses new
  ones with close code 1013 ("try again later"). An overloaded replica then
  degrades predictably while the autoscaler adds capacity, instead of queueing
  until every request times out.
* ``/metrics`` exposes the counters, histograms and gauges below. The HPA can
  scale on CPU alone; ``erid_http_inflight_requests`` and
  ``erid_websocket_connections`` are the custom metrics worth scaling on when a
  Prometheus adapter is installed (see deploy/k8s/README.md).
* :func:`readiness` backs ``/ready``: the database answers and, when the
  Postgres event bus is in use, its LISTEN connection is up. A replica that
  can't fan events out to its WebSocket clients is taken out of rotation
  rather than silently serving stale streams.
"""

from __future__ import annotations

import asyncio
import json
import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.settings import settings

# Paths that must keep answering even when the replica is saturated: the
# orchestrator's probes and the metrics scrape.
UNSHED_PATHS = frozenset({"/health", "/ready", "/metrics"})

HTTP_REQUESTS = Counter("erid_http_requests_total", "HTTP requests handled", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "erid_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_INFLIGHT = Gauge("erid_http_inflight_requests", "HTTP requests currently being handled")
SHED = Counter("erid_load_shed_total", "Requests or connections refused because the replica is saturated", ["kind"])
WEBSOCKETS = Gauge("erid_websocket_connections", "Open WebSocket connections")
EVENTS = Counter("erid_events_emitted_total", "Workspace events emitted", ["type"])
RATE_LIMITED = Counter("erid_rate_limited_total", "Requests rejected by a rate limit", ["scope"])
AUTH_FAILURES = Counter("erid_auth_failures_total", "Requests rejected for bad or missing credentials")
DB_POOL_IN_USE = Gauge("erid_db_pool_connections_in_use", "Database connections checked out of the pool")
EVENT_BUS_UP = Gauge("erid_event_bus_connected", "1 when the Postgres LISTEN connection is up (or the bus is local)")


class _State:
    inflight = 0
    websockets = 0


state = _State()


def _route_label(scope: Scope) -> str:
    """The matched route *template* (bounded cardinality), not the raw path."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    raw = scope.get("path", "")
    if path:
        # Routes in an included router report their path without the router's
        # prefix ("/workspaces/{slug}/tasks" for "/api/workspaces/..."). Put the
        # prefix back from the leading segments of the concrete path.
        if ":path}" not in path:
            extra = raw.count("/") - path.count("/")
            if extra > 0:
                return "/".join(raw.split("/")[: extra + 1]) + path
        return path
    if raw in UNSHED_PATHS or raw == "/mcp":
        return raw
    return "unmatched"


async def _send_json(send: Send, status: int, body: dict, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
            + (headers or []),
        }
    )
    await send({"type": "http.response.body", "body": payload})


class TrafficMiddleware:
    """Per-route metrics plus in-flight request and WebSocket admission control."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    async def _websocket(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = settings.max_websockets
        if limit and state.websockets >= limit:
            SHED.labels("websocket").inc()
            # Refuse before accepting: the client sees the handshake fail with
            # 1013 semantics and reconnects (ideally to another replica).
            await send({"type": "websocket.close", "code": 1013, "reason": "server busy"})
            return
        state.websockets += 1
        WEBSOCKETS.set(state.websockets)
        try:
            await self.app(scope, receive, send)
        finally:
            state.websockets -= 1
            WEBSOCKETS.set(state.websockets)

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        exempt = path in UNSHED_PATHS
        limit = settings.max_inflight_requests
        if not exempt and limit and state.inflight >= limit:
            SHED.labels("http").inc()
            await _send_json(send, 503, {"detail": "server busy, retry shortly"}, [(b"retry-after", b"1")])
            return

        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        if not exempt:
            state.inflight += 1
            HTTP_INFLIGHT.set(state.inflight)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if not exempt:
                state.inflight -= 1
                HTTP_INFLIGHT.set(state.inflight)
            route = _route_label(scope)
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method, route, str(status_holder["status"])).inc()
            HTTP_LATENCY.labels(method, route).observe(time.perf_counter() - start)


def render_metrics() -> tuple[bytes, str]:
    """Current Prometheus exposition, refreshing the sampled gauges first."""
    from app.db import session as db_session

    pool = db_session.engine.pool
    checked_out = getattr(pool, "checkedout", None)
    if callable(checked_out):
        DB_POOL_IN_USE.set(checked_out())
    EVENT_BUS_UP.set(1 if _bus_connected() else 0)
    return generate_latest(), CONTENT_TYPE_LATEST


def _bus_connected() -> bool:
    from app.services import event_bus

    bus = event_bus._bus  # noqa: SLF001 - read-only peek; None until first use
    if bus is None:
        return True  # nothing to be connected yet
    return getattr(bus, "connected", True)


async def readiness(timeout: float = 2.0) -> tuple[bool, dict[str, str]]:
    """Check what this replica needs to serve traffic; return ``(ready, checks)``."""
    from app.db import session as db_session

    checks: dict[str, str] = {}
    try:
        async with asyncio.timeout(timeout):
            async with db_session.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        checks["database"] = f"unavailable: {type(exc).__name__}"
    checks["event_bus"] = "ok" if _bus_connected() else "disconnected"
    ready = all(v == "ok" for v in checks.values())
    return ready, checks
