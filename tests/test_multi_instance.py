"""Several real API processes sharing one Postgres, as when scaled out.

Boots N uvicorn processes at the same moment against a brand-new database (so
they race to migrate it) and checks what only shows up across processes:
cross-instance realtime fan-out, tokens verified by any replica, rate limits
and lockouts shared through the database, claim races decided once, recovery
after the LISTEN connections are killed, and graceful shutdown.

Needs ERID_TEST_DATABASE_URL pointing at Postgres with rights to create
databases (the CI service and a local superuser both have them).
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import httpx
import pytest
import websockets
from conftest import IS_POSTGRES, TEST_DATABASE_URL
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not IS_POSTGRES, reason="needs ERID_TEST_DATABASE_URL pointing at Postgres"),
]

API_DIR = Path(__file__).resolve().parent.parent / "api"
REPLICAS = 3
AUTH_LIMIT = 6  # per client IP per minute, shared
FAILURE_LIMIT = 3  # rejected credentials per client IP per minute, shared


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _keypair() -> tuple[str, str]:
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def _server_dsn(database: str) -> str:
    base, _, _ = TEST_DATABASE_URL.rpartition("/")
    return f"{base}/{database}".replace("postgresql+asyncpg://", "postgresql://", 1)


async def _admin_exec(sql: str) -> None:
    conn = await asyncpg.connect(_server_dsn("postgres"))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


class Cluster:
    def __init__(self, database: str, env: dict[str, str]) -> None:
        self.database = database
        self.env = env
        self.procs: list[subprocess.Popen] = []
        self.urls: list[str] = []

    def start(self, n: int) -> list[str]:
        new = []
        for _ in range(n):
            port = _free_port()
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-level",
                    "warning",
                    "--timeout-graceful-shutdown",
                    "5",
                ],
                cwd=API_DIR,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.procs.append(proc)
            url = f"http://127.0.0.1:{port}"
            self.urls.append(url)
            new.append(url)
        deadline = time.time() + 90
        for url, proc in zip(self.urls[-n:], self.procs[-n:], strict=True):
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"replica exited during startup:\n{proc.stdout.read().decode()[-3000:]}")
                try:
                    if httpx.get(f"{url}/ready", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() > deadline:
                    raise RuntimeError(f"replica {url} never became ready")
                time.sleep(0.2)
        return new

    def stop(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="module")
def cluster():
    database = f"erid_mi_{uuid.uuid4().hex[:10]}"
    asyncio.run(_admin_exec(f'CREATE DATABASE "{database}"'))
    private, public = _keypair()
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ERID_", "DATABASE_URL", "EVENT_BUS", "CORS_")) and k != "FORWARDED_ALLOW_IPS"
    }
    env.update(
        DATABASE_URL=TEST_DATABASE_URL.rpartition("/")[0] + f"/{database}",
        EVENT_BUS_BACKEND="postgres",
        ERID_JWT_PRIVATE_KEY=private,
        ERID_JWT_PUBLIC_KEY=public,
        ERID_RATE_LIMIT_AUTH=f"{AUTH_LIMIT}/minute",
        ERID_RATE_LIMIT_AUTH_FAILURES=f"{FAILURE_LIMIT}/minute",
        # Tests stand in for many clients via X-Forwarded-For from localhost.
        FORWARDED_ALLOW_IPS="127.0.0.1",
        PYTHONUNBUFFERED="1",
    )
    c = Cluster(database, env)
    try:
        # All replicas start together against an empty database: they race to
        # run the migrations, which the advisory lock must serialize.
        c.start(REPLICAS)
        yield c
    finally:
        c.stop()
        asyncio.run(
            _admin_exec(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{database}' "
                "AND pid <> pg_backend_pid()"
            )
        )
        asyncio.run(_admin_exec(f'DROP DATABASE IF EXISTS "{database}"'))


def _ip() -> str:
    """A fresh client address per test, so shared limits don't bleed across tests."""
    return f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"


def _avoid_window_boundary(margin: float = 3.0) -> None:
    """Fixed one-minute windows reset on the minute; don't straddle one."""
    remaining = 60 - (time.time() % 60)
    if remaining < margin:
        time.sleep(remaining + 0.1)


def _provision(cluster, slug: str) -> dict[str, str]:
    r = httpx.post(f"{cluster.urls[0]}/api/workspaces", params={"slug": slug}, headers={"X-Forwarded-For": _ip()})
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["api_key"]}


def test_all_replicas_migrated_and_ready(cluster):
    for url in cluster.urls:
        body = httpx.get(f"{url}/ready").json()
        assert body == {"status": "ready", "checks": {"database": "ok", "event_bus": "ok"}}


async def _first_event(ws, wanted: str, timeout: float = 10) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=deadline - time.time()))
        if message.get("type") == wanted:
            return message
    raise TimeoutError(wanted)


async def test_events_written_on_one_replica_reach_websockets_on_another(cluster):
    slug = f"fanout-{uuid.uuid4().hex[:6]}"
    key = _provision(cluster, slug)
    a, b = cluster.urls[0], cluster.urls[1]
    ws_url = b.replace("http", "ws") + f"/api/workspaces/{slug}/ws?api_key={key['X-API-Key']}"
    async with websockets.connect(ws_url) as ws:
        async with httpx.AsyncClient() as http:
            r = await http.post(f"{a}/api/workspaces/{slug}/tasks", json={"title": "cross"}, headers=key)
            assert r.status_code == 201
        event = await _first_event(ws, "task_created")
    assert event["data"]["title"] == "cross" and event["seq"] > 0


def test_tokens_minted_on_one_replica_work_on_every_replica(cluster):
    slug = f"tok-{uuid.uuid4().hex[:6]}"
    key = _provision(cluster, slug)
    token = httpx.post(
        f"{cluster.urls[0]}/api/workspaces/{slug}/token",
        json={"api_key": key["X-API-Key"]},
        headers={"X-Forwarded-For": _ip()},
    ).json()["access_token"]
    for url in cluster.urls:
        r = httpx.get(f"{url}/api/workspaces/{slug}/tasks", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, (url, r.text)


def test_auth_rate_limit_is_shared_across_replicas(cluster):
    slug = f"rl-{uuid.uuid4().hex[:6]}"
    key = _provision(cluster, slug)
    ip = _ip()
    _avoid_window_boundary()
    statuses = []
    for i in range(AUTH_LIMIT + 2):
        url = cluster.urls[i % len(cluster.urls)]  # round-robin, like a load balancer
        r = httpx.post(
            f"{url}/api/workspaces/{slug}/token", json={"api_key": key["X-API-Key"]}, headers={"X-Forwarded-For": ip}
        )
        statuses.append(r.status_code)
    # A per-process limiter would allow AUTH_LIMIT per replica (18 here).
    assert statuses[:AUTH_LIMIT] == [200] * AUTH_LIMIT
    assert statuses[AUTH_LIMIT:] == [429, 429]


def test_lockout_reaches_every_replica(cluster):
    slug = f"lock-{uuid.uuid4().hex[:6]}"
    key = _provision(cluster, slug)
    ip = {"X-Forwarded-For": _ip()}
    a, b = cluster.urls[0], cluster.urls[1]
    _avoid_window_boundary()
    for _ in range(FAILURE_LIMIT):
        r = httpx.get(f"{a}/api/workspaces/{slug}/tasks", headers={**ip, "X-API-Key": "guess"})
        assert r.status_code == 403
    # Locked out on A, even with the right key.
    assert httpx.get(f"{a}/api/workspaces/{slug}/tasks", headers={**ip, **key}).status_code == 429
    # B refuses this client from its first further failure onwards (the shared
    # count is already over the limit), so guessing can't continue there either.
    assert httpx.get(f"{b}/api/workspaces/{slug}/tasks", headers={**ip, "X-API-Key": "guess"}).status_code == 403
    assert httpx.get(f"{b}/api/workspaces/{slug}/tasks", headers={**ip, **key}).status_code == 429


async def test_claim_race_across_replicas_has_one_winner(cluster):
    slug = f"race-{uuid.uuid4().hex[:6]}"
    owner = _provision(cluster, slug)
    agents = []
    for i in range(9):
        r = httpx.post(
            f"{cluster.urls[0]}/api/workspaces/{slug}/actors",
            json={"name": f"agent{i}", "role": "writer"},
            headers=owner,
        )
        agents.append({"X-API-Key": r.json()["api_key"]})
    async with httpx.AsyncClient() as http:
        results = await asyncio.gather(
            *(
                http.post(
                    f"{cluster.urls[i % REPLICAS]}/api/workspaces/{slug}/claims", json={"paths": ["hot.py"]}, headers=h
                )
                for i, h in enumerate(agents)
            )
        )
    assert sum(r.json()["ok"] for r in results) == 1


async def test_replicas_recover_after_losing_their_listen_connections(cluster):
    """Chaos: kill every LISTEN connection; replicas must reconnect and fan out again."""
    conn = await asyncpg.connect(_server_dsn(cluster.database))
    try:
        killed = await conn.fetchval(
            "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
            "WHERE datname = $1 AND query ILIKE 'LISTEN%'",
            cluster.database,
        )
    finally:
        await conn.close()
    assert killed >= REPLICAS
    deadline = time.time() + 30
    while time.time() < deadline:
        if all(httpx.get(f"{u}/ready").status_code == 200 for u in cluster.urls):
            break
        await asyncio.sleep(0.5)
    else:
        pytest.fail("replicas did not reconnect their LISTEN connections")
    await test_events_written_on_one_replica_reach_websockets_on_another(cluster)


async def test_graceful_shutdown_closes_websockets_with_1012(cluster):
    """Scale-in / rollout: a stopping replica tells clients to reconnect elsewhere."""
    slug = f"drain-{uuid.uuid4().hex[:6]}"
    key = _provision(cluster, slug)
    (url,) = cluster.start(1)
    proc = cluster.procs[-1]
    ws_url = url.replace("http", "ws") + f"/api/workspaces/{slug}/ws?api_key={key['X-API-Key']}"
    async with websockets.connect(ws_url) as ws:
        proc.terminate()  # SIGTERM, as Kubernetes sends
        with pytest.raises(websockets.ConnectionClosed) as closed:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=15)
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 1012
    # Uvicorn shuts down gracefully, then re-raises SIGTERM so the exit status
    # says "terminated by SIGTERM" (-15), the conventional result.
    assert proc.wait(timeout=15) in (0, -15)
