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

# One process-wide API client, shared by every tool/resource so HTTP connections
# are pooled instead of being built and torn down per call. The FastMCP server's
# lifetime is the process lifetime (stdio or streamable-http), so the loop exits
# with it and no explicit close is needed.
_client: APIClient | None = None


def _get_client() -> APIClient:
    """Lazily build (once) and return the shared client. Kept as a module-level
    getter so tests can reset ``_client`` or monkeypatch ``APIClient`` before
    first use."""
    global _client
    if _client is None:
        _client = APIClient()
    return _client


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
    return _fmt(await _get_client().workspace_summary(_slug(slug)))


@mcp.tool()
async def search_context(q: str, slug: str | None = None) -> str:
    """Search decisions and tasks in a workspace by free-text query."""
    return _fmt(await _get_client().search_context(_slug(slug), q))


@mcp.tool()
async def current_tasks(status: str | None = None, slug: str | None = None) -> str:
    """List tasks in the workspace, optionally filtered by status
    (todo, in_progress, done, blocked)."""
    return _fmt(await _get_client().current_tasks(_slug(slug), status=status))


@mcp.tool()
async def create_task(
    title: str, assigned_to: str | None = None, created_by: str | None = None, slug: str | None = None
) -> str:
    """Create a task in the shared workspace."""
    return _fmt(await _get_client().create_task(_slug(slug), title, assigned_to=assigned_to, created_by=created_by))


@mcp.tool()
async def update_task(
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    assigned_to: str | None = None,
    slug: str | None = None,
) -> str:
    """Update a task's status, title, or assignee."""
    return _fmt(
        await _get_client().update_task(_slug(slug), task_id, status=status, title=title, assigned_to=assigned_to)
    )


@mcp.tool()
async def delete_task(task_id: str, slug: str | None = None) -> str:
    """Delete a task from the workspace."""
    return _fmt(await _get_client().delete_task(_slug(slug), task_id))


@mcp.tool()
async def create_decision(
    title: str,
    reason: str | None = None,
    related_files: str | None = None,
    made_by: str | None = None,
    task_id: str | None = None,
    slug: str | None = None,
) -> str:
    """Record an architectural/implementation decision so every tool can see it.

    Optionally link it to a task by passing that task's id as ``task_id``."""
    return _fmt(
        await _get_client().create_decision(
            _slug(slug), title, reason=reason, related_files=related_files, made_by=made_by, task_id=task_id
        )
    )


@mcp.tool()
async def delete_decision(decision_id: str, slug: str | None = None) -> str:
    """Delete a decision from the workspace."""
    return _fmt(await _get_client().delete_decision(_slug(slug), decision_id))


@mcp.tool()
async def task_decisions(task_id: str, slug: str | None = None) -> str:
    """List the decisions linked to a task (decision ↔ task linking)."""
    return _fmt(await _get_client().task_decisions(_slug(slug), task_id))


@mcp.tool()
async def recent_decisions(limit: int = 20, slug: str | None = None) -> str:
    """List the most recent decisions in the workspace."""
    return _fmt(await _get_client().recent_decisions(_slug(slug), limit=limit))


@mcp.tool()
async def active_developers(slug: str | None = None) -> str:
    """List developers/agents currently active in the workspace."""
    return _fmt(await _get_client().active_developers(_slug(slug)))


@mcp.tool()
async def update_presence(
    actor_name: str,
    current_file: str | None = None,
    current_task: str | None = None,
    actor_type: str = "ai",
    slug: str | None = None,
) -> str:
    """Report what you're working on so collaborators (human & AI) can see it."""
    return _fmt(
        await _get_client().update_presence(
            _slug(slug), actor_name, actor_type=actor_type, current_file=current_file, current_task=current_task
        )
    )


@mcp.tool()
async def list_workspaces() -> str:
    """List every workspace on the hub (slug, name, created_at, secured).

    Use this to discover workspace slugs before auditing more than one.
    Tool-only counterpart of the ``workspace://index`` resource."""
    return _fmt(await _get_client().list_workspaces())


# ---------------------------------------------------------------------------
# Session handoffs — durable state of play so another session can resume safely.
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_handoff(
    summary: str,
    task_id: str | None = None,
    recipient: str | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    files_changed: str | None = None,
    commands_run: str | None = None,
    blockers: str | None = None,
    next_action: str | None = None,
    created_by: str | None = None,
    slug: str | None = None,
) -> str:
    """Leave a durable session handoff so the next agent/developer can resume safely.

    Record what you finished, which files changed, which commands/tests you ran
    (and their outcome), what's blocked, and the recommended next action. ``summary``
    is required; the rest is optional context. ``created_by`` defaults to your
    authenticated actor name — set it only to attribute the handoff to someone else."""
    return _fmt(
        await _get_client().create_handoff(
            _slug(slug),
            summary,
            task_id=task_id,
            recipient=recipient,
            branch=branch,
            worktree=worktree,
            files_changed=files_changed,
            commands_run=commands_run,
            blockers=blockers,
            next_action=next_action,
            created_by=created_by,
        )
    )


@mcp.tool()
async def recent_handoffs(
    status: str | None = None,
    limit: int | None = None,
    slug: str | None = None,
) -> str:
    """List handoffs in the workspace (newest first).

    Filter by ``status`` (open, acknowledged, resolved) — pass ``open`` to see
    what still needs a pickup."""
    return _fmt(await _get_client().list_handoffs(_slug(slug), status=status, limit=limit))


@mcp.tool()
async def acknowledge_handoff(handoff_id: str, slug: str | None = None) -> str:
    """Mark a handoff as picked up (open → acknowledged).

    Call this when you start working from a handoff so others know it's in flight."""
    return _fmt(await _get_client().acknowledge_handoff(_slug(slug), handoff_id))


@mcp.tool()
async def resolve_handoff(handoff_id: str, slug: str | None = None) -> str:
    """Mark a handoff as completed (open/acknowledged → resolved).

    Call this once the follow-up work the handoff described is done."""
    return _fmt(await _get_client().resolve_handoff(_slug(slug), handoff_id))


# ---------------------------------------------------------------------------
# Resources — read-only snapshots a client can pull into context directly.
# ---------------------------------------------------------------------------


@mcp.resource(
    "workspace://{slug}/summary",
    name="workspace_summary_resource",
    description="Counts and active developers for a workspace: tasks/decisions totals and who's online.",
    mime_type="application/json",
)
async def summary_resource(slug: str) -> str:
    return _fmt(await _get_client().workspace_summary(_slug(slug)))


@mcp.resource(
    "workspace://{slug}/tasks",
    name="workspace_tasks_resource",
    description="All tasks in a workspace (todo, in_progress, done, blocked).",
    mime_type="application/json",
)
async def tasks_resource(slug: str) -> str:
    return _fmt(await _get_client().current_tasks(_slug(slug)))


@mcp.resource(
    "workspace://{slug}/decisions",
    name="workspace_decisions_resource",
    description="The most recent architectural/implementation decisions in a workspace.",
    mime_type="application/json",
)
async def decisions_resource(slug: str) -> str:
    return _fmt(await _get_client().recent_decisions(_slug(slug)))


@mcp.resource(
    "workspace://{slug}/handoffs",
    name="workspace_handoffs_resource",
    description="Session handoffs in a workspace: what was done, what's blocked, and what to do next.",
    mime_type="application/json",
)
async def handoffs_resource(slug: str) -> str:
    return _fmt(await _get_client().list_handoffs(_slug(slug)))


@mcp.resource(
    "workspace://{slug}/presence",
    name="workspace_presence_resource",
    description="Developers/agents currently active in a workspace and what they're editing.",
    mime_type="application/json",
)
async def presence_resource(slug: str) -> str:
    return _fmt(await _get_client().active_developers(_slug(slug)))


@mcp.resource(
    "workspace://index",
    name="workspace_index_resource",
    description="Every workspace on the hub (slug, name, created_at, secured) so clients can discover slugs to audit.",
    mime_type="application/json",
)
async def index_resource() -> str:
    return _fmt(await _get_client().list_workspaces())


# ---------------------------------------------------------------------------
# Prompts — ready-made conversation starters over the shared workspace state.
# ---------------------------------------------------------------------------


@mcp.prompt(name="summarize_workspace", description="Summarize the current state of a workspace.")
async def summarize_workspace_prompt(slug: str | None = None) -> str:
    resolved = _slug(slug)
    return (
        f"Use the workspace_summary, current_tasks, and recent_decisions tools for workspace '{resolved}', "
        "then write a concise summary: overall health, open vs. done tasks, what was decided recently, "
        "and anything that looks blocked or stale."
    )


@mcp.prompt(name="standup_report", description="Draft a standup-style report of work in a workspace.")
async def standup_report_prompt(slug: str | None = None) -> str:
    resolved = _slug(slug)
    return (
        f"Build a standup report for workspace '{resolved}'. Pull current_tasks and update_presence/"
        "active_developers, then group by who's working on what: what each developer has in progress, "
        "what's done since, and any blockers."
    )


@mcp.prompt(name="catch_up", description="Catch up an agent that just joined a workspace.")
async def catch_up_prompt(slug: str | None = None) -> str:
    resolved = _slug(slug)
    return (
        f"I just joined workspace '{resolved}' and need to catch up. Call workspace_summary, "
        "recent_handoffs (status 'open' first, then all), and recent_decisions, then brief me on: "
        "the project's goal as implied by open tasks, any open handoffs waiting to be picked up "
        "(their next_action and blockers), the key decisions already made (so I don't re-litigate "
        "them), who's active, and where I could pick up work."
    )


if __name__ == "__main__":
    transport = "stdio"
    if "--transport" in sys.argv:
        transport = sys.argv[sys.argv.index("--transport") + 1]
    mcp.run(transport=transport)
