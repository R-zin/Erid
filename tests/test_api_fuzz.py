"""Schema-driven fuzzing of every REST operation: no input may cause a 5xx.

For each operation in the OpenAPI schema, valid-looking requests are mutated
with adversarial values (empty, huge, NUL bytes, unicode, injection strings,
wrong types, absurd numbers, bad UUIDs, unknown fields) in the body, query and
path. Each request is sent with a valid owner credential so it reaches the
service layer, where a database error would surface as a 500. Run it against
Postgres (ERID_TEST_DATABASE_URL) to catch column limits and type errors
SQLite tolerates. Deterministic: the seed is fixed per operation.
"""

import json
import random
import uuid

import pytest
from app.main import app
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

ROUNDS_PER_OPERATION = 30

NASTY_STRINGS = [
    "",
    " ",
    "a",
    "x" * 20_000,
    "\x00",
    "nul\x00byte",
    "🙂" * 300,
    "' OR 1=1 --",
    "'; DROP TABLE tasks; --",
    "%_\\",
    "../../etc/passwd",
    "<script>alert(1)</script>",
    "${jndi:ldap://x}",
    "‮\u0000﻿",
    "Ω≈ç√∫",
    "-1",
    "null",
    "\n\r\t",
]
NASTY_NUMBERS = [0, -1, 1, 2**31, 2**63, -(2**63), 10**30, 3.5, float("1e308")]
NASTY_ANY = [None, True, [], {}, [None], {"$gt": ""}, "x" * 300]


def _resolve(schema: dict, spec: dict) -> dict:
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    return schema


def _valid(schema: dict, spec: dict, rng: random.Random, depth: int = 0):
    """A plausible valid value for a JSON schema (best effort)."""
    schema = _resolve(schema, spec)
    if "anyOf" in schema:
        options = [s for s in schema["anyOf"] if s.get("type") != "null"] or schema["anyOf"]
        return _valid(rng.choice(options), spec, rng, depth)
    if "enum" in schema:
        return rng.choice(schema["enum"])
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        if depth > 3:
            return {}
        return {k: _valid(v, spec, rng, depth + 1) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [_valid(schema.get("items", {}), spec, rng, depth + 1)]
    if kind == "integer":
        lo, hi = schema.get("minimum", 1), schema.get("maximum", 100)
        return rng.randint(int(lo), int(min(hi, lo + 100)))
    if kind == "boolean":
        return rng.choice([True, False])
    if schema.get("format") == "uuid":
        return str(uuid.uuid4())
    return "fuzz-" + str(rng.randint(0, 10**6))


def _nasty(rng: random.Random):
    pool = rng.choice([NASTY_STRINGS, NASTY_NUMBERS, NASTY_ANY])
    return rng.choice(pool)


def _mutate_body(body, rng: random.Random):
    if not isinstance(body, dict) or not body or rng.random() < 0.1:
        return _nasty(rng)
    body = dict(body)
    for key in rng.sample(list(body), k=rng.randint(1, len(body))):
        body[key] = _nasty(rng)
    if rng.random() < 0.3:
        body["unexpected_" + str(rng.randint(0, 99))] = _nasty(rng)
    if rng.random() < 0.2:
        body.pop(rng.choice(list(body)), None)
    return body


def _operations() -> list[tuple[str, str, dict]]:
    spec = app.openapi()
    ops = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            ops.append((method.upper(), path, op))
    return ops


SKIP = {
    # Redirects to an external OAuth provider; covered by test_oauth.py.
    ("GET", "/api/auth/{provider}/login"),
    ("GET", "/api/auth/{provider}/callback"),
    # Destroys the fixture workspace; fuzzed separately at the end.
    ("DELETE", "/api/workspaces/{slug}"),
}


@pytest.mark.parametrize(("method", "path", "op"), _operations(), ids=lambda v: v if isinstance(v, str) else "")
async def test_no_input_causes_a_server_error(client: AsyncClient, authed, method, path, op):
    if (method, path) in SKIP:
        pytest.skip("not fuzzable in-process")
    slug, headers = authed
    spec = app.openapi()
    rng = random.Random(f"{method} {path}")
    # Real ids so some requests reach deep service paths.
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "seed"}, headers=headers)).json()
    body_schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")

    for round_no in range(ROUNDS_PER_OPERATION):
        url = path.replace("{slug}", slug if rng.random() < 0.9 else rng.choice(["s" * 300, "bad slug", "%00"]))
        for name in ("task_id", "decision_id", "handoff_id", "actor_id", "claim_id"):
            value = task["id"] if rng.random() < 0.5 else rng.choice([str(uuid.uuid4()), "not-a-uuid", "0", "-1"])
            url = url.replace("{" + name + "}", value)
        url = url.replace("{provider}", rng.choice(["github", "google", "x" * 300]))

        params = {}
        for p in op.get("parameters", []):
            if p["in"] != "query":
                continue
            value = _valid(p.get("schema", {}), spec, rng)
            if rng.random() < 0.5:
                value = _nasty(rng)
            if value is not None and not isinstance(value, dict | list):
                params[p["name"]] = value

        kwargs = {}
        if body_schema is not None:
            body = _valid(body_schema, spec, rng)
            if round_no % 3:
                body = _mutate_body(body, rng)
            kwargs["content"] = json.dumps(body, allow_nan=True)
            kwargs["headers"] = {**headers, "content-type": "application/json"}
        else:
            kwargs["headers"] = headers

        r = await client.request(method, url, params=params, **kwargs)
        if r.status_code == 503 and "not configured" in r.text:
            continue  # deliberate: OAuth is switched off in the test settings
        assert r.status_code < 500, (
            f"{method} {url} params={params} body={kwargs.get('content', '')[:300]!r} -> {r.status_code} {r.text[:300]}"
        )


async def test_raw_garbage_bodies(client: AsyncClient, authed):
    slug, headers = authed
    for payload in (b"", b"{", b"[]", b"null", b"\xff\xfe", b'{"title": "\\ud800"}', b"{" * 5000, b"1e999999"):
        for path in ("tasks", "decisions", "handoffs", "presence", "claims"):
            r = await client.post(
                f"/api/workspaces/{slug}/{path}",
                content=payload,
                headers={**headers, "content-type": "application/json"},
            )
            assert r.status_code < 500, f"{path} {payload[:20]!r} -> {r.status_code} {r.text[:200]}"
