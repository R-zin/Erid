"""AI Context Hub — MCP server.

Exposes the shared workspace context (tasks, decisions, presence) as MCP tools
so Claude Code, Cursor, Codex CLI, etc. all read from and write to the same
project state instead of starting each session from zero.

Runs over stdio (launched by an AI tool) or streamable-http. Configuration via
environment variables — see ``client.py`` and ``clients/README.md``:

- ``API_BASE``           REST API base URL
- ``WORKSPACE_API_KEY``  workspace API key (sent as ``X-API-Key``)
- ``WORKSPACE_SLUG``     default workspace so tools don't need a slug each call
"""

import json
import os
import sys
from pathlib import Path

# Allow running both as ``python mcp-server/src/server.py`` (script) and as a
# module; ensure the src/ dir is importable for the ``client`` module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import APIClient
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ai-context-hub")

DEFAULT_SLUG = os.environ.get("WORKSPACE_SLUG", "")


def _slug(slug: str | None) -> str:
    resolved = slug or DEFAULT_SLUG
    if not resolved:
        raise ValueError("no workspace slug provided and WORKSPACE_SLUG is not set")
    return resolved


def _fmt(data) -> str:
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def workspace_summary(slug: str | None = None) -> str:
    """Get a shared workspace summary: task/decision counts and who's active."""
    client = APIClient()
    try:
        return _fmt(await client.workspace_summary(_slug(slug)))
    finally:
        await client.close()


@mcp.tool()
async def search_context(q: str, slug: str | None = None) -> str:
    """Search decisions and tasks in a workspace by free-text query."""
    client = APIClient()
    try:
        return _fmt(await client.search_context(_slug(slug), q))
    finally:
        await client.close()


@mcp.tool()
async def current_tasks(status: str | None = None, slug: str | None = None) -> str:
    """List tasks in the workspace, optionally filtered by status
    (todo, in_progress, done, blocked)."""
    client = APIClient()
    try:
        return _fmt(await client.current_tasks(_slug(slug), status=status))
    finally:
        await client.close()


@mcp.tool()
async def create_task(
    title: str, assigned_to: str | None = None, created_by: str | None = None, slug: str | None = None
) -> str:
    """Create a task in the shared workspace."""
    client = APIClient()
    try:
        return _fmt(await client.create_task(_slug(slug), title, assigned_to=assigned_to, created_by=created_by))
    finally:
        await client.close()


@mcp.tool()
async def update_task(
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    assigned_to: str | None = None,
    slug: str | None = None,
) -> str:
    """Update a task's status, title, or assignee."""
    client = APIClient()
    try:
        return _fmt(await client.update_task(_slug(slug), task_id, status=status, title=title, assigned_to=assigned_to))
    finally:
        await client.close()


@mcp.tool()
async def create_decision(
    title: str,
    reason: str | None = None,
    related_files: str | None = None,
    made_by: str | None = None,
    slug: str | None = None,
) -> str:
    """Record an architectural/implementation decision so every tool can see it."""
    client = APIClient()
    try:
        return _fmt(
            await client.create_decision(
                _slug(slug), title, reason=reason, related_files=related_files, made_by=made_by
            )
        )
    finally:
        await client.close()


@mcp.tool()
async def recent_decisions(limit: int = 20, slug: str | None = None) -> str:
    """List the most recent decisions in the workspace."""
    client = APIClient()
    try:
        return _fmt(await client.recent_decisions(_slug(slug), limit=limit))
    finally:
        await client.close()


@mcp.tool()
async def active_developers(slug: str | None = None) -> str:
    """List developers/agents currently active in the workspace."""
    client = APIClient()
    try:
        return _fmt(await client.active_developers(_slug(slug)))
    finally:
        await client.close()


@mcp.tool()
async def update_presence(
    actor_name: str,
    current_file: str | None = None,
    current_task: str | None = None,
    actor_type: str = "ai",
    slug: str | None = None,
) -> str:
    """Report what you're working on so collaborators (human & AI) can see it."""
    client = APIClient()
    try:
        return _fmt(
            await client.update_presence(
                _slug(slug), actor_name, actor_type=actor_type, current_file=current_file, current_task=current_task
            )
        )
    finally:
        await client.close()


if __name__ == "__main__":
    transport = "stdio"
    if "--transport" in sys.argv:
        transport = sys.argv[sys.argv.index("--transport") + 1]
    mcp.run(transport=transport)
