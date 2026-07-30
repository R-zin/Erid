"""Unit tests (agent-4, task #14) for the APIClient header selection + HTTP error paths.

Fully offline: no real server. HTTP is stubbed with ``httpx.MockTransport``,
so these exercise the client's own logic (auth-header precedence, request
targeting, ``raise_for_status`` propagation) without any network I/O.

Mirrors ``test_watcher.py``'s ``sys.path`` bootstrap so ``client`` imports the
same way the MCP server does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from client import APIClient  # noqa: E402

pytestmark = pytest.mark.asyncio


def _client(token: str = "", api_key: str = "", base_url: str = "http://test") -> APIClient:
    # Empty strings are falsy in the client and also override any ambient
    # WORKSPACE_TOKEN / WORKSPACE_API_KEY env vars, keeping tests hermetic.
    return APIClient(base_url=base_url, api_key=api_key, token=token)


def _install_mock_transport(c: APIClient, handler) -> None:
    """Swap the client's inner transport for an offline mock.

    The client bakes its auth headers into the original ``AsyncClient`` at
    construction time, so they must be carried over to the mocked one — this is
    exactly what ``test_auth_header_reaches_server_on_request`` verifies.
    """
    c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=dict(c._client.headers))


# ---------------------------------------------------------------------------
# Header selection / auth precedence
# ---------------------------------------------------------------------------


async def test_bearer_token_preferred_over_api_key():
    """When both are set, only the Bearer header is sent (token wins)."""
    c = _client(token="tok-123", api_key="key-abc")
    headers = c._client.headers
    assert headers["Authorization"] == "Bearer tok-123"
    assert "X-API-Key" not in headers
    await c.close()


async def test_api_key_only_when_no_token():
    c = _client(api_key="key-abc")
    headers = c._client.headers
    assert headers["X-API-Key"] == "key-abc"
    assert "Authorization" not in headers
    await c.close()


async def test_no_auth_header_when_neither_set():
    c = _client()
    headers = c._client.headers
    assert "Authorization" not in headers
    assert "X-API-Key" not in headers
    await c.close()


async def test_empty_token_falls_back_to_api_key():
    """An empty-string token is falsy, so the api_key header is used."""
    c = _client(token="", api_key="key-abc")
    headers = c._client.headers
    assert headers["X-API-Key"] == "key-abc"
    assert "Authorization" not in headers
    await c.close()


# ---------------------------------------------------------------------------
# HTTP error propagation (stubbed transport, offline)
# ---------------------------------------------------------------------------


async def test_get_raises_for_4xx():
    """A 4xx from the server propagates as HTTPStatusError from a read."""
    c = _client(api_key="k")
    _install_mock_transport(c, lambda req: httpx.Response(403, json={"detail": "forbidden"}))
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await c.current_tasks("ws")
    assert excinfo.value.response.status_code == 403
    await c.close()


async def test_get_raises_for_5xx():
    """A 5xx from the server propagates as HTTPStatusError from a read."""
    c = _client(api_key="k")
    _install_mock_transport(c, lambda req: httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await c.workspace_summary("ws")
    assert excinfo.value.response.status_code == 500
    await c.close()


async def test_write_raises_for_422():
    """A 422 validation error on a write propagates."""
    c = _client(api_key="k")
    _install_mock_transport(c, lambda req: httpx.Response(422, json={"detail": "invalid"}))
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        await c.create_task("ws", title="")
    assert excinfo.value.response.status_code == 422
    await c.close()


async def test_auth_header_reaches_server_on_request():
    """The configured bearer header is actually sent on an outbound request."""
    seen: dict[str, str] = {}
    c = _client(token="tok-xyz")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization", "")
        seen["x-api-key"] = request.headers.get("X-API-Key", "")
        return httpx.Response(200, json={"slug": "ws", "task_count": 0})

    _install_mock_transport(c, handler)
    await c.workspace_summary("ws")
    assert seen["authorization"] == "Bearer tok-xyz"
    assert seen["x-api-key"] == ""
    await c.close()


async def test_request_targets_workspace_root_and_path():
    """Requests are built against ``/api/workspaces/{slug}/<path>``."""
    seen: dict[str, str] = {}
    c = _client(api_key="k", base_url="http://api.example")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json=[{"title": "t"}])

    _install_mock_transport(c, handler)
    await c.current_tasks("my-slug")
    assert seen["path"] == "/api/workspaces/my-slug/tasks"
    await c.close()
