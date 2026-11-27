"""Load test: simulated agents against one or more Erid API instances.

    uv run python scripts/loadtest.py --urls http://127.0.0.1:8001,http://127.0.0.1:8002 \\
        --workspaces 10 --agents-per-workspace 5 --duration 30

Each virtual agent loops over a weighted mix of what coding agents do against
Erid: read the summary and task list, search, send presence heartbeats,
create tasks and decisions, update tasks, claim and release files. Requests
are spread round-robin across --urls, the way a load balancer would. One
WebSocket subscriber per workspace (on a different instance than most writes)
measures realtime fan-out: how many created events arrive and how fast.

Reports throughput, latency percentiles per operation, status codes, shed
(503) and rate-limited (429) responses, and event delivery.

Setup provisions workspaces with POST /api/workspaces; pass --admin-token if
ERID_ADMIN_TOKEN is set on the servers. Disable ERID_RATE_LIMIT_API (or raise
it) when measuring raw capacity, or it is the limit you measure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
import uuid
from collections import Counter, defaultdict

import httpx
import websockets

MIX = [
    ("summary", 25),
    ("list_tasks", 20),
    ("search", 10),
    ("presence", 15),
    ("create_task", 10),
    ("create_decision", 5),
    ("update_task", 5),
    ("claim_release", 10),
]


class Stats:
    def __init__(self) -> None:
        self.latency: dict[str, list[float]] = defaultdict(list)
        self.status: Counter = Counter()
        self.errors: Counter = Counter()
        self.created_events = 0
        self.received_events = 0
        self.fanout_latency: list[float] = []
        self.success_latency: list[float] = []

    def record(self, op: str, status: int, seconds: float) -> None:
        self.latency[op].append(seconds)
        self.status[status] += 1
        if 200 <= status < 300:
            self.success_latency.append(seconds)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))] * 1000


async def _post_retrying(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """POST, honouring 503/429 Retry-After like a well-behaved client."""
    for _ in range(60):
        r = await client.post(url, **kwargs)
        if r.status_code not in (429, 503):
            r.raise_for_status()
            return r
        await asyncio.sleep(float(r.headers.get("retry-after", "1")))
    r.raise_for_status()
    return r


async def setup(args, client: httpx.AsyncClient) -> list[dict]:
    """Provision workspaces with one actor key per agent."""
    workspaces = []
    admin = {"X-Admin-Token": args.admin_token} if args.admin_token else {}
    base = args.urls[0]
    for w in range(args.workspaces):
        slug = f"load-{uuid.uuid4().hex[:8]}-{w}"
        r = await _post_retrying(client, f"{base}/api/workspaces", params={"slug": slug}, headers=admin)
        owner = {"X-API-Key": r.json()["api_key"]}
        keys = []
        for a in range(args.agents_per_workspace):
            r = await _post_retrying(
                client,
                f"{base}/api/workspaces/{slug}/actors",
                json={"name": f"agent-{a}", "role": "writer"},
                headers=owner,
            )
            keys.append({"X-API-Key": r.json()["api_key"]})
        workspaces.append({"slug": slug, "owner": owner, "agents": keys})
    return workspaces


async def agent(args, client, stats: Stats, ws: dict, headers: dict, idx: int, stop_at: float) -> None:
    rng = random.Random(idx)
    ops, weights = zip(*MIX, strict=True)
    tasks: list[str] = []
    n = idx
    while time.time() < stop_at:
        op = rng.choices(ops, weights)[0]
        base = args.urls[n % len(args.urls)]
        n += 1
        root = f"{base}/api/workspaces/{ws['slug']}"
        start = time.perf_counter()
        try:
            if op == "summary":
                r = await client.get(f"{root}/summary", headers=headers)
            elif op == "list_tasks":
                r = await client.get(f"{root}/tasks", params={"limit": 100}, headers=headers)
            elif op == "search":
                r = await client.get(
                    f"{root}/search", params={"q": rng.choice(["auth", "deploy", "cache"])}, headers=headers
                )
            elif op == "presence":
                r = await client.post(
                    f"{root}/presence",
                    json={
                        "actor_name": f"agent-{idx}",
                        "actor_type": "ai",
                        "current_file": f"src/f{rng.randint(1, 50)}.py",
                    },
                    headers=headers,
                )
            elif op == "create_task":
                r = await client.post(
                    f"{root}/tasks", json={"title": f"fix auth cache {rng.random()}"}, headers=headers
                )
                if r.status_code == 201:
                    tasks.append(r.json()["id"])
                    stats.created_events += 1
            elif op == "create_decision":
                r = await client.post(
                    f"{root}/decisions",
                    json={"title": "use deploy cache", "reason": "load test " * 20},
                    headers=headers,
                )
                if r.status_code == 201:
                    stats.created_events += 1
            elif op == "update_task" and tasks:
                r = await client.put(
                    f"{root}/tasks/{rng.choice(tasks)}", json={"status": "in_progress"}, headers=headers
                )
            elif op == "claim_release":
                path = f"src/module{rng.randint(1, 30)}/"
                r = await client.post(f"{root}/claims", json={"paths": [path], "ttl_seconds": 120}, headers=headers)
                if r.status_code == 200 and r.json()["granted"]:
                    await client.post(f"{root}/claims/release", json={"paths": [path]}, headers=headers)
            else:
                continue
            stats.record(op, r.status_code, time.perf_counter() - start)
        except httpx.HTTPError as exc:
            stats.errors[type(exc).__name__] += 1
            stats.record(op, 0, time.perf_counter() - start)


async def subscriber(args, stats: Stats, ws_info: dict, url: str, stop_at: float, ready: asyncio.Event) -> None:
    ws_url = (
        url.replace("http", "ws", 1) + f"/api/workspaces/{ws_info['slug']}/ws?api_key={ws_info['owner']['X-API-Key']}"
    )
    try:
        async with websockets.connect(ws_url, max_queue=None) as sock:
            ready.set()
            while time.time() < stop_at + 3:
                try:
                    message = json.loads(await asyncio.wait_for(sock.recv(), timeout=1))
                except TimeoutError:
                    continue
                if message.get("type") in ("task_created", "decision_created"):
                    stats.received_events += 1
                    ts = message.get("ts")
                    if ts:
                        from datetime import datetime

                        sent = datetime.fromisoformat(ts).timestamp()
                        stats.fanout_latency.append(max(0.0, time.time() - sent))
    except Exception as exc:  # noqa: BLE001
        ready.set()
        stats.errors[f"ws:{type(exc).__name__}"] += 1


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--urls", required=True, help="comma-separated API base URLs")
    p.add_argument("--workspaces", type=int, default=10)
    p.add_argument("--agents-per-workspace", type=int, default=5)
    p.add_argument("--duration", type=float, default=30)
    p.add_argument("--admin-token", default="")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = p.parse_args()
    args.urls = [u.rstrip("/") for u in args.urls.split(",")]

    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=1000)
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:
        workspaces = await setup(args, client)
        stats = Stats()
        stop_at = time.time() + args.duration
        readies = []
        subs = []
        for ws_info in workspaces:
            ready = asyncio.Event()
            readies.append(ready)
            # Subscribe on the last instance; most writes land elsewhere.
            subs.append(asyncio.create_task(subscriber(args, stats, ws_info, args.urls[-1], stop_at, ready)))
        await asyncio.gather(*(r.wait() for r in readies))
        started = time.time()
        await asyncio.gather(
            *(
                agent(args, client, stats, ws_info, headers, i * 100 + j, stop_at)
                for i, ws_info in enumerate(workspaces)
                for j, headers in enumerate(ws_info["agents"])
            )
        )
        elapsed = time.time() - started
        await asyncio.gather(*subs)

    total = sum(len(v) for v in stats.latency.values())
    all_lat = [x for v in stats.latency.values() for x in v]
    ok = sum(c for s, c in stats.status.items() if 200 <= s < 300)
    summary = {
        "instances": len(args.urls),
        "agents": args.workspaces * args.agents_per_workspace,
        "duration_s": round(elapsed, 1),
        "requests": total,
        "throughput_rps": round(total / elapsed, 1),
        "success_rate": round(ok / total, 4) if total else 0,
        "latency_ms": {
            "p50": round(_pct(all_lat, 0.5), 1),
            "p95": round(_pct(all_lat, 0.95), 1),
            "p99": round(_pct(all_lat, 0.99), 1),
        },
        "success_latency_ms": {
            "p50": round(_pct(stats.success_latency, 0.5), 1),
            "p95": round(_pct(stats.success_latency, 0.95), 1),
            "p99": round(_pct(stats.success_latency, 0.99), 1),
        },
        "status_codes": dict(sorted(stats.status.items())),
        "client_errors": dict(stats.errors),
        "per_operation_p95_ms": {op: round(_pct(v, 0.95), 1) for op, v in sorted(stats.latency.items())},
        "realtime": {
            "events_created": stats.created_events,
            "events_received": stats.received_events,
            "delivery_rate": round(stats.received_events / stats.created_events, 4) if stats.created_events else None,
            "fanout_p95_ms": round(_pct(stats.fanout_latency, 0.95), 1),
        },
    }
    if args.json:
        print(json.dumps(summary))
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
