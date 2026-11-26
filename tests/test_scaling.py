"""Scale-out behaviour: readiness, metrics, load shedding, pagination."""

import asyncio

import pytest
from app.core import observability
from app.core.settings import settings
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = (settings.max_inflight_requests, settings.max_websockets, settings.metrics_token)
    yield
    for name, value in zip(("max_inflight_requests", "max_websockets", "metrics_token"), saved, strict=True):
        object.__setattr__(settings, name, value)


async def test_ready_reports_checks(client: AsyncClient):
    r = await client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ready", "checks": {"database": "ok", "event_bus": "ok"}}


async def test_ready_is_503_when_event_bus_is_down(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(observability, "_bus_connected", lambda: False)
    r = await client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["event_bus"] == "disconnected"


async def test_metrics_exposes_route_templates_not_raw_paths(client: AsyncClient, authed):
    slug, headers = authed
    await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)
    body = (await client.get("/metrics")).text
    assert "erid_http_requests_total" in body
    assert 'route="/api/workspaces/{slug}/tasks"' in body
    assert f'route="/api/workspaces/{slug}/tasks"' not in body  # no per-slug cardinality
    assert "erid_events_emitted_total" in body


async def test_metrics_token(client: AsyncClient):
    object.__setattr__(settings, "metrics_token", "scrape-secret")
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})).status_code == 200


async def test_load_shedding_returns_503_with_retry_after(client: AsyncClient, authed):
    slug, headers = authed
    object.__setattr__(settings, "max_inflight_requests", 1)
    observability.state.inflight = 1  # simulate one request already in flight
    try:
        r = await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)
        assert r.status_code == 503
        assert r.headers["retry-after"] == "1"
        # Probes and the scrape are never shed.
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/ready")).status_code == 200
        assert (await client.get("/metrics")).status_code == 200
    finally:
        observability.state.inflight = 0
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 200


async def test_inflight_counter_returns_to_zero_after_concurrent_requests(client: AsyncClient, authed):
    slug, headers = authed
    await asyncio.gather(*(client.get(f"/api/workspaces/{slug}/tasks", headers=headers) for _ in range(25)))
    assert observability.state.inflight == 0


async def test_websocket_refused_when_at_capacity(client: AsyncClient):
    from app.main import app
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    object.__setattr__(settings, "max_websockets", 1)
    observability.state.websockets = 1
    try:
        with (
            TestClient(app) as tc,
            pytest.raises(WebSocketDisconnect) as exc,
            tc.websocket_connect("/api/workspaces/busy/ws"),
        ):
            pass
        assert exc.value.code == 1013
    finally:
        observability.state.websockets = 0


async def test_task_pagination(client: AsyncClient, authed):
    slug, headers = authed
    for i in range(5):
        await client.post(f"/api/workspaces/{slug}/tasks", json={"title": f"t{i}"}, headers=headers)
    page1 = (await client.get(f"/api/workspaces/{slug}/tasks", params={"limit": 2}, headers=headers)).json()
    page2 = (
        await client.get(f"/api/workspaces/{slug}/tasks", params={"limit": 2, "offset": 2}, headers=headers)
    ).json()
    rest = (await client.get(f"/api/workspaces/{slug}/tasks", params={"offset": 4}, headers=headers)).json()
    # Pages are disjoint and together cover every task exactly once. (Order is
    # created_at then id: SQLite timestamps have 1s resolution, so tasks made in
    # the same second tie and fall back to id order.)
    titles = [t["title"] for t in page1 + page2 + rest]
    assert len(page1) == 2 and len(page2) == 2 and len(rest) == 1
    assert sorted(titles) == ["t0", "t1", "t2", "t3", "t4"]
    too_big = await client.get(f"/api/workspaces/{slug}/tasks", params={"limit": 5000}, headers=headers)
    assert too_big.status_code == 422
