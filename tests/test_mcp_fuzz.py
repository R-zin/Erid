"""Fuzz every MCP tool over Streamable HTTP: bad arguments must come back as
tool errors (or results), never crash the endpoint or leave it unhealthy."""

import random

import httpx
import pytest
from app.mcp_server import mcp
from test_mcp_http import _call, live_server  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

NASTY = ["", "x" * 20_000, "nul\x00", "🙂" * 50, "' OR 1=1 --", "../../etc", "not-a-uuid", "-1", "null"]


async def test_every_tool_survives_hostile_arguments(live_server, authed):  # noqa: F811
    slug, key = authed
    headers = {**key, "X-Erid-Workspace": slug}
    tools = await mcp.list_tools()
    rng = random.Random("mcp-fuzz")
    calls = 0
    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        for _ in range(4):
            args = {}
            for name, schema in props.items():
                if name == "slug":
                    continue
                kind = schema.get("type") or next(
                    (s.get("type") for s in schema.get("anyOf", []) if s.get("type") != "null"), "string"
                )
                if kind == "array":
                    args[name] = [rng.choice(NASTY) for _ in range(rng.randint(0, 3))]
                elif kind == "integer":
                    args[name] = rng.choice([0, -5, 10**12])
                elif kind == "boolean":
                    args[name] = rng.choice([True, False])
                else:
                    args[name] = rng.choice(NASTY)
            result = await _call(live_server, headers, tool.name, args)
            calls += 1
            # Either a normal result or a tool error; both are fine, a transport
            # failure would have raised above.
            assert result.content, (tool.name, args)
            text = result.content[0].text
            # Errors must never leak driver or SQL internals.
            for leak in ("sqlalchemy", "asyncpg", "psycopg", "SELECT ", "INSERT ", "Traceback"):
                assert leak not in text, (tool.name, args, text[:300])
    assert calls >= 4 * len(tools)
    assert httpx.get(f"{live_server}/health").status_code == 200
