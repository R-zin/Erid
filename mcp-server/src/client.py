"""Async HTTP client for the AI Context Hub REST API.

Configuration comes from the environment so the same client works whether the
MCP server runs in Docker (against the ``api`` service) or is launched over
stdio by a local tool (against ``localhost``):

- ``API_BASE``      base URL of the REST API (default ``http://localhost:8000``)
- ``WORKSPACE_API_KEY``  workspace API key, sent as the ``X-API-Key`` header
"""

import os

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
API_KEY = os.environ.get("WORKSPACE_API_KEY", "")


class APIClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 15.0) -> None:
        base = (base_url or API_BASE).rstrip("/")
        self._root = f"{base}/api/workspaces"
        headers = {"X-API-Key": api_key if api_key is not None else API_KEY}
        self._client = httpx.AsyncClient(headers={k: v for k, v in headers.items() if v}, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    def _url(self, slug: str, path: str = "") -> str:
        return f"{self._root}/{slug}{path}"

    # -- reads ------------------------------------------------------------
    async def workspace_summary(self, slug: str):
        r = await self._client.get(self._url(slug, "/summary"))
        r.raise_for_status()
        return r.json()

    async def search_context(self, slug: str, q: str):
        r = await self._client.get(self._url(slug, "/search"), params={"q": q})
        r.raise_for_status()
        return r.json()

    async def current_tasks(self, slug: str, status: str | None = None):
        params = {"status": status} if status else None
        r = await self._client.get(self._url(slug, "/tasks"), params=params)
        r.raise_for_status()
        return r.json()

    async def recent_decisions(self, slug: str, limit: int = 20):
        r = await self._client.get(self._url(slug, "/decisions"), params={"limit": limit})
        r.raise_for_status()
        return r.json()

    async def active_developers(self, slug: str):
        r = await self._client.get(self._url(slug, "/presence"))
        r.raise_for_status()
        return r.json()

    # -- writes -----------------------------------------------------------
    async def create_task(self, slug: str, title: str, assigned_to: str | None = None, created_by: str | None = None):
        r = await self._client.post(
            self._url(slug, "/tasks"),
            json={"title": title, "assigned_to": assigned_to, "created_by": created_by},
        )
        r.raise_for_status()
        return r.json()

    async def update_task(
        self,
        slug: str,
        task_id: str,
        status: str | None = None,
        title: str | None = None,
        assigned_to: str | None = None,
    ):
        body = {
            k: v for k, v in {"status": status, "title": title, "assigned_to": assigned_to}.items() if v is not None
        }
        r = await self._client.put(self._url(slug, f"/tasks/{task_id}"), json=body)
        r.raise_for_status()
        return r.json()

    async def create_decision(
        self,
        slug: str,
        title: str,
        reason: str | None = None,
        related_files: str | None = None,
        made_by: str | None = None,
    ):
        r = await self._client.post(
            self._url(slug, "/decisions"),
            json={"title": title, "reason": reason, "related_files": related_files, "made_by": made_by},
        )
        r.raise_for_status()
        return r.json()

    async def update_presence(
        self,
        slug: str,
        actor_name: str,
        actor_type: str = "ai",
        current_file: str | None = None,
        current_task: str | None = None,
    ):
        r = await self._client.post(
            self._url(slug, "/presence"),
            json={
                "actor_name": actor_name,
                "actor_type": actor_type,
                "current_file": current_file,
                "current_task": current_task,
            },
        )
        r.raise_for_status()
        return r.json()
