"""MCP over Streamable HTTP, served by the API itself at ``/mcp``.

AI clients connect by URL; no local process, repo checkout, or ``uv`` needed:

    claude mcp add --transport http erid http://localhost:8000/mcp \\
        --header "X-API-Key: $KEY" --header "X-Erid-Workspace: myproj"

Tools call :mod:`app.services` in-process (no HTTP hop back into the API), with
the same authorization as REST: each call resolves the caller from the MCP HTTP
request's ``X-API-Key`` / ``Authorization: Bearer`` / ``?api_key=`` credentials
and checks the permission the matching REST route requires. The default
workspace comes from ``X-Erid-Workspace`` (or ``?workspace=``); every tool also
takes an explicit ``slug``.

The tool, resource, and prompt names match the stdio server in
``mcp-server/src/server.py`` (a test keeps them in sync), so prompts and
instructions written for one work with the other.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi.security import HTTPAuthorizationCredentials
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from app.core import ratelimit
from app.core.security import Principal, resolve_principal
from app.core.settings import settings
from app.db.session import get_db
from app.models.models import HandoffStatus, Permission, TaskStatus
from app.schemas.schemas import (
    ClaimCheckIn,
    ClaimIn,
    DecisionIn,
    HandoffIn,
    PresenceIn,
    ReleaseIn,
    TaskIn,
    TaskUpdate,
)
from app.services import claims as claims_svc
from app.services import context as svc
from app.services import workspaces as ws_svc

WORKSPACE_HEADER = "X-Erid-Workspace"

mcp = FastMCP(
    "erid",
    instructions=(
        "Erid is the shared context hub for this project. Call workspace_summary (or the catch_up prompt) "
        "when you start, search_context before re-deciding something, create_decision when you make a "
        "notable choice, and create_handoff when you wrap up so the next session can resume."
    ),
)

# ---------------------------------------------------------------------------
# Per-call auth + DB session
# ---------------------------------------------------------------------------


def _request(ctx: Context):
    request = ctx.request_context.request
    if request is None:  # pragma: no cover - only reachable over a non-HTTP transport
        raise RuntimeError("the in-API MCP endpoint only serves Streamable HTTP")
    return request


def _resolve_slug(ctx: Context, slug: str | None) -> str:
    request = _request(ctx)
    resolved = slug or request.headers.get(WORKSPACE_HEADER) or request.query_params.get("workspace")
    if not resolved:
        raise ValueError(f"no workspace: pass `slug`, or configure the {WORKSPACE_HEADER} header on this MCP server")
    return resolved


@contextlib.asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    """A DB session from ``get_db``, honouring the app's dependency overrides (tests)."""
    from app.main import app as fastapi_app  # runtime import: app.main mounts this module

    factory = fastapi_app.dependency_overrides.get(get_db, get_db)
    gen = factory()
    try:
        yield await anext(gen)
    finally:
        await gen.aclose()


async def _as[T](
    ctx: Context, slug: str | None, permission: Permission, op: Callable[[AsyncSession, Principal], Awaitable[T]]
) -> T:
    """Authenticate the MCP request against ``slug``, require ``permission``, run ``op``."""
    request = _request(ctx)
    resolved = _resolve_slug(ctx, slug)
    auth = request.headers.get("authorization", "")
    bearer = (
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth[7:].strip())
        if auth.lower().startswith("bearer ")
        else None
    )
    async with _session() as db:
        try:
            ip = ratelimit.client_ip(request)
            principal = await resolve_principal(
                resolved,
                db,
                request.headers.get(settings.api_key_header),
                request.query_params.get("api_key"),
                bearer,
                ip=ip,
            )
            caller = ratelimit.credential_fingerprint(
                request.headers.get(settings.api_key_header) or request.query_params.get("api_key"),
                bearer.credentials if bearer else None,
            )
            ratelimit.enforce_api_limit(resolved, caller or ip)
        except Exception as exc:  # HTTPException from the shared resolver
            detail = getattr(exc, "detail", None) or str(exc)
            raise PermissionError(f"workspace '{resolved}': {detail}") from None
        if not principal.has(permission):
            raise PermissionError(f"credential lacks permission '{permission.value}' in workspace '{resolved}'")
        return await op(db, principal)


def _fmt(data: Any) -> str:
    if isinstance(data, list):
        data = [d.model_dump(mode="json") if hasattr(d, "model_dump") else d for d in data]
    elif hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return json.dumps(data, indent=2, default=str)


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ValueError(f"{what} must be a UUID, got {value!r}") from None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def workspace_summary(ctx: Context, slug: str | None = None) -> str:
    """Get a shared workspace summary: task/decision counts, open handoffs, and who's active."""
    return _fmt(await _as(ctx, slug, Permission.read, svc.summary))


@mcp.tool()
async def search_context(q: str, ctx: Context, slug: str | None = None) -> str:
    """Search decisions and tasks in a workspace by free-text query."""
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: svc.search(db, p, q)))


@mcp.tool()
async def current_tasks(ctx: Context, status: str | None = None, slug: str | None = None) -> str:
    """List tasks in the workspace, optionally filtered by status (todo, in_progress, done, blocked)."""
    wanted = TaskStatus(status) if status else None
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: svc.list_tasks(db, p, wanted)))


@mcp.tool()
async def create_task(
    title: str, ctx: Context, assigned_to: str | None = None, created_by: str | None = None, slug: str | None = None
) -> str:
    """Create a task in the shared workspace."""
    payload = TaskIn(title=title, assigned_to=assigned_to, created_by=created_by)
    return _fmt(await _as(ctx, slug, Permission.write_tasks, lambda db, p: svc.create_task(db, p, payload)))


@mcp.tool()
async def update_task(
    task_id: str,
    ctx: Context,
    status: str | None = None,
    title: str | None = None,
    assigned_to: str | None = None,
    slug: str | None = None,
) -> str:
    """Update a task's status, title, or assignee."""
    payload = TaskUpdate(status=TaskStatus(status) if status else None, title=title, assigned_to=assigned_to)
    tid = _uuid(task_id, "task_id")
    return _fmt(await _as(ctx, slug, Permission.write_tasks, lambda db, p: svc.update_task(db, p, tid, payload)))


@mcp.tool()
async def delete_task(task_id: str, ctx: Context, slug: str | None = None) -> str:
    """Delete a task from the workspace."""
    tid = _uuid(task_id, "task_id")
    await _as(ctx, slug, Permission.write_tasks, lambda db, p: svc.delete_task(db, p, tid))
    return _fmt({"deleted": task_id})


@mcp.tool()
async def create_decision(
    title: str,
    ctx: Context,
    reason: str | None = None,
    related_files: str | None = None,
    made_by: str | None = None,
    task_id: str | None = None,
    slug: str | None = None,
) -> str:
    """Record an architectural/implementation decision so every tool can see it.

    Optionally link it to a task by passing that task's id as ``task_id``."""
    payload = DecisionIn(
        title=title,
        reason=reason,
        related_files=related_files,
        made_by=made_by,
        task_id=_uuid(task_id, "task_id") if task_id else None,
    )
    return _fmt(await _as(ctx, slug, Permission.write_decisions, lambda db, p: svc.create_decision(db, p, payload)))


@mcp.tool()
async def delete_decision(decision_id: str, ctx: Context, slug: str | None = None) -> str:
    """Delete a decision from the workspace."""
    did = _uuid(decision_id, "decision_id")
    await _as(ctx, slug, Permission.write_decisions, lambda db, p: svc.delete_decision(db, p, did))
    return _fmt({"deleted": decision_id})


@mcp.tool()
async def task_decisions(task_id: str, ctx: Context, slug: str | None = None) -> str:
    """List the decisions linked to a task."""
    tid = _uuid(task_id, "task_id")
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: svc.list_task_decisions(db, p, tid)))


@mcp.tool()
async def recent_decisions(ctx: Context, limit: int = 20, slug: str | None = None) -> str:
    """List the most recent decisions in the workspace."""
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: svc.list_decisions(db, p, limit)))


@mcp.tool()
async def active_developers(ctx: Context, slug: str | None = None) -> str:
    """List developers/agents currently active in the workspace."""
    return _fmt(await _as(ctx, slug, Permission.read, svc.list_presence))


@mcp.tool()
async def update_presence(
    actor_name: str,
    ctx: Context,
    current_file: str | None = None,
    current_task: str | None = None,
    actor_type: str = "ai",
    slug: str | None = None,
) -> str:
    """Report what you're working on so collaborators (human & AI) can see it."""
    payload = PresenceIn(
        actor_name=actor_name, actor_type=actor_type, current_file=current_file, current_task=current_task
    )
    return _fmt(await _as(ctx, slug, Permission.presence, lambda db, p: svc.update_presence(db, p, payload)))


# ---------------------------------------------------------------------------
# File claims — advisory leases so agents don't edit the same files at once.
# ---------------------------------------------------------------------------


@mcp.tool()
async def claim_files(
    paths: list[str],
    ctx: Context,
    ttl_seconds: int = 3600,
    exclusive: bool = True,
    reason: str | None = None,
    task_id: str | None = None,
    holder: str | None = None,
    slug: str | None = None,
) -> str:
    """Claim files before editing them so other agents and humans don't collide with you.

    ``paths`` are repo-relative files, directories (``src/auth/``) or globs
    (``src/**/*.py``). Paths nobody else holds are granted; any that overlap
    someone else's claim come back under ``conflicts`` with who holds them and
    why: pick other work or coordinate before editing those. Claims expire
    after ``ttl_seconds`` (default 1h); claim again to renew. Release them with
    ``release_files`` when done. Use ``exclusive=False`` for read-only work."""
    payload = ClaimIn(
        paths=paths,
        ttl_seconds=ttl_seconds,
        exclusive=exclusive,
        reason=reason,
        task_id=_uuid(task_id, "task_id") if task_id else None,
        holder=holder,
    )
    return _fmt(await _as(ctx, slug, Permission.presence, lambda db, p: claims_svc.claim(db, p, payload)))


@mcp.tool()
async def release_files(
    ctx: Context, paths: list[str] | None = None, holder: str | None = None, slug: str | None = None
) -> str:
    """Release your file claims on ``paths`` (or all of them if omitted) once you're done editing."""
    payload = ReleaseIn(paths=paths, holder=holder)
    return _fmt(await _as(ctx, slug, Permission.presence, lambda db, p: claims_svc.release(db, p, payload)))


@mcp.tool()
async def list_claims(ctx: Context, path: str | None = None, slug: str | None = None) -> str:
    """List active file claims (who is editing what), optionally only those overlapping ``path``."""
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: claims_svc.list_claims(db, p, path)))


@mcp.tool()
async def check_files(paths: list[str], ctx: Context, holder: str | None = None, slug: str | None = None) -> str:
    """Check whether anyone else has claimed these files, without claiming them."""
    payload = ClaimCheckIn(paths=paths, holder=holder)
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: claims_svc.check(db, p, payload)))


@mcp.tool()
async def list_workspaces() -> str:
    """List every workspace on the hub (slug, name, created_at, secured)."""
    async with _session() as db:
        return _fmt(await ws_svc.list_workspaces(db))


@mcp.tool()
async def create_handoff(
    summary: str,
    ctx: Context,
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
    (and their outcome), what's blocked, and the recommended next action."""
    payload = HandoffIn(
        summary=summary,
        task_id=_uuid(task_id, "task_id") if task_id else None,
        recipient=recipient,
        branch=branch,
        worktree=worktree,
        files_changed=files_changed,
        commands_run=commands_run,
        blockers=blockers,
        next_action=next_action,
        created_by=created_by,
    )
    return _fmt(await _as(ctx, slug, Permission.write_handoffs, lambda db, p: svc.create_handoff(db, p, payload)))


@mcp.tool()
async def recent_handoffs(
    ctx: Context, status: str | None = None, limit: int | None = None, slug: str | None = None
) -> str:
    """List handoffs in the workspace (newest first). Pass status='open' to see what still needs a pickup."""
    wanted = HandoffStatus(status) if status else None
    return _fmt(await _as(ctx, slug, Permission.read, lambda db, p: svc.list_handoffs(db, p, wanted, limit or 20)))


@mcp.tool()
async def acknowledge_handoff(handoff_id: str, ctx: Context, slug: str | None = None) -> str:
    """Mark a handoff as picked up (open → acknowledged)."""
    hid = _uuid(handoff_id, "handoff_id")
    return _fmt(await _as(ctx, slug, Permission.write_handoffs, lambda db, p: svc.acknowledge_handoff(db, p, hid)))


@mcp.tool()
async def resolve_handoff(handoff_id: str, ctx: Context, slug: str | None = None) -> str:
    """Mark a handoff as completed (open/acknowledged → resolved)."""
    hid = _uuid(handoff_id, "handoff_id")
    return _fmt(await _as(ctx, slug, Permission.write_handoffs, lambda db, p: svc.resolve_handoff(db, p, hid)))


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def _resource_ctx() -> Context:
    return mcp.get_context()


@mcp.resource(
    "workspace://{slug}/summary",
    name="workspace_summary_resource",
    description="Counts and active developers for a workspace.",
    mime_type="application/json",
)
async def summary_resource(slug: str) -> str:
    return _fmt(await _as(_resource_ctx(), slug, Permission.read, svc.summary))


@mcp.resource(
    "workspace://{slug}/tasks",
    name="workspace_tasks_resource",
    description="All tasks in a workspace (todo, in_progress, done, blocked).",
    mime_type="application/json",
)
async def tasks_resource(slug: str) -> str:
    return _fmt(await _as(_resource_ctx(), slug, Permission.read, svc.list_tasks))


@mcp.resource(
    "workspace://{slug}/decisions",
    name="workspace_decisions_resource",
    description="The most recent architectural/implementation decisions in a workspace.",
    mime_type="application/json",
)
async def decisions_resource(slug: str) -> str:
    return _fmt(await _as(_resource_ctx(), slug, Permission.read, svc.list_decisions))


@mcp.resource(
    "workspace://{slug}/handoffs",
    name="workspace_handoffs_resource",
    description="Session handoffs in a workspace: what was done, what's blocked, and what to do next.",
    mime_type="application/json",
)
async def handoffs_resource(slug: str) -> str:
    return _fmt(await _as(_resource_ctx(), slug, Permission.read, svc.list_handoffs))


@mcp.resource(
    "workspace://{slug}/presence",
    name="workspace_presence_resource",
    description="Developers/agents currently active in a workspace and what they're editing.",
    mime_type="application/json",
)
async def presence_resource(slug: str) -> str:
    return _fmt(await _as(_resource_ctx(), slug, Permission.read, svc.list_presence))


@mcp.resource(
    "workspace://index",
    name="workspace_index_resource",
    description="Every workspace on the hub (slug, name, created_at, secured).",
    mime_type="application/json",
)
async def index_resource() -> str:
    return await list_workspaces()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@mcp.prompt(name="summarize_workspace", description="Summarize the current state of a workspace.")
async def summarize_workspace_prompt(slug: str | None = None) -> str:
    where = f"workspace '{slug}'" if slug else "the workspace"
    return (
        f"Use the workspace_summary, current_tasks, and recent_decisions tools for {where}, "
        "then write a concise summary: overall health, open vs. done tasks, what was decided recently, "
        "and anything that looks blocked or stale."
    )


@mcp.prompt(name="standup_report", description="Draft a standup-style report of work in a workspace.")
async def standup_report_prompt(slug: str | None = None) -> str:
    where = f"workspace '{slug}'" if slug else "the workspace"
    return (
        f"Build a standup report for {where}. Pull current_tasks and active_developers, then group by "
        "who's working on what: what each developer has in progress, what's done since, and any blockers."
    )


@mcp.prompt(name="catch_up", description="Catch up an agent that just joined a workspace.")
async def catch_up_prompt(slug: str | None = None) -> str:
    where = f"workspace '{slug}'" if slug else "the workspace"
    return (
        f"I just joined {where} and need to catch up. Call workspace_summary, "
        "recent_handoffs (status 'open' first, then all), and recent_decisions, then brief me on: "
        "the project's goal as implied by open tasks, any open handoffs waiting to be picked up "
        "(their next_action and blockers), the key decisions already made (so I don't re-litigate "
        "them), who's active, and where I could pick up work."
    )


# ---------------------------------------------------------------------------
# ASGI mount
# ---------------------------------------------------------------------------


class MCPEndpoint:
    """ASGI app mounted at ``/mcp``.

    A ``StreamableHTTPSessionManager`` can only be ``run()`` once, but the API
    lifespan may run several times in one process (tests, reloads). So each
    lifespan gets a fresh stateless manager around the same MCP server.
    Stateless + JSON responses means no server-side MCP session state, so the
    endpoint scales across API instances like the REST routes do.
    """

    def __init__(self) -> None:
        # One manager per running lifespan, newest last. Lifespans can overlap
        # (a server still shutting down while the next one starts, as in the
        # live-server tests), so each removes only its own manager; clearing a
        # single shared slot let a late shutdown wipe out the newer server's
        # manager and turn /mcp into a 503.
        self._managers: list[StreamableHTTPSessionManager] = []

    def _active_manager(self) -> StreamableHTTPSessionManager | None:
        return self._managers[-1] if self._managers else None

    @contextlib.asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,
            json_response=True,
            stateless=True,
            # Auth is per-request credentials, never ambient (cookies), so DNS-
            # rebinding protection adds nothing here; CORS still applies.
            security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        async with manager.run():
            self._managers.append(manager)
            try:
                yield
            finally:
                self._managers.remove(manager)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        manager = self._active_manager()
        if manager is None:
            from starlette.responses import JSONResponse

            await JSONResponse({"detail": "MCP endpoint is not running"}, status_code=503)(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)


endpoint = MCPEndpoint()
