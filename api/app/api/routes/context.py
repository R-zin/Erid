"""REST + WebSocket routes for workspaces and their shared context.

Handlers are thin: FastAPI resolves and authorizes the caller
(``require_action``), the matching function in :mod:`app.services` does the
work, and domain errors become HTTP statuses via the handler in ``app.main``.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    Principal,
    is_operator,
    operator_token,
    require_action,
    require_operator_if_configured,
    resolve_ws_principal,
)
from app.core.settings import settings
from app.db.session import get_db
from app.models.models import HandoffStatus, Permission, TaskStatus
from app.schemas.schemas import (
    ActorCreated,
    ActorIn,
    ActorOut,
    SLUG_PATTERN,
    ActorToken,
    DecisionIn,
    DecisionOut,
    HandoffIn,
    HandoffOut,
    PresenceIn,
    PresenceOut,
    TaskIn,
    TaskOut,
    TaskUpdate,
    TokenRequest,
    WorkspaceCreated,
    WorkspaceKeyRotated,
    WorkspaceListItem,
    WorkspaceSecured,
)
from app.services import context as svc
from app.services import events
from app.services import workspaces as ws_svc
from app.services.event_bus import get_event_bus

logger = logging.getLogger("context_hub.routes")

router = APIRouter()

# Idle keepalive for the /ws stream (app-level; Starlette exposes no server-side
# ping/control-frame API, so we send a JSON ``{"type": "ping"}`` frame instead).
# Dead/half-open clients raise on this send instead of blocking the loop forever.
WS_HEARTBEAT_SECS = 30

READ = require_action(Permission.read)
WRITE_TASKS = require_action(Permission.write_tasks)
WRITE_DECISIONS = require_action(Permission.write_decisions)
WRITE_HANDOFFS = require_action(Permission.write_handoffs)
PRESENCE = require_action(Permission.presence)
ADMIN = require_action(Permission.admin_keys)
OWNER = require_action(Permission.owner)


# ---------------------------------------------------------------------------
# Workspace provisioning
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces",
    response_model=WorkspaceCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operator_if_configured)],
)
async def provision_workspace(
    slug: str = Query(..., min_length=1, max_length=128, pattern=SLUG_PATTERN), db: AsyncSession = Depends(get_db)
) -> WorkspaceCreated:
    """Create a workspace and return its API key (shown only here; never re-disclosed).

    Requires ``X-Admin-Token`` when ``ERID_ADMIN_TOKEN`` is configured.
    """
    return await ws_svc.provision_workspace(db, slug)


@router.get("/workspaces", response_model=list[WorkspaceListItem])
async def list_workspaces(
    token: str | None = Depends(operator_token), db: AsyncSession = Depends(get_db)
) -> list[WorkspaceListItem]:
    """List every workspace (slug, name, secured flag).

    Unauthenticated by default: principals are per-workspace, a directory is
    needed to discover workspaces, and only non-secret metadata is exposed. With
    ``ERID_PUBLIC_WORKSPACE_DIRECTORY=0`` it needs the operator's admin token.
    """
    if not settings.public_workspace_directory and not is_operator(token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace directory is not public")
    return await ws_svc.list_workspaces(db)


@router.delete("/workspaces/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(principal: Principal = Depends(OWNER), db: AsyncSession = Depends(get_db)) -> None:
    """Delete an entire workspace and everything in it (owner only)."""
    await ws_svc.delete_workspace(db, principal)


@router.post("/workspaces/{slug}/secure", response_model=WorkspaceSecured)
async def secure_workspace(slug: str, db: AsyncSession = Depends(get_db)) -> WorkspaceSecured:
    """Claim an open workspace by minting its key (returned once).

    Unauthenticated by design (an open workspace has no admin to gate on), and
    refused when ``ERID_ALLOW_OPEN_WORKSPACES=0``.
    """
    return await ws_svc.secure_workspace(db, slug)


@router.post("/workspaces/{slug}/rotate-key", response_model=WorkspaceKeyRotated)
async def rotate_workspace_key(
    principal: Principal = Depends(OWNER), db: AsyncSession = Depends(get_db)
) -> WorkspaceKeyRotated:
    """Rotate the workspace key (owner only). Returns the new key once."""
    return await ws_svc.rotate_workspace_key(db, principal)


# ---------------------------------------------------------------------------
# Actors, access grants, and tokens
# ---------------------------------------------------------------------------


@router.post("/workspaces/{slug}/actors", response_model=ActorCreated, status_code=status.HTTP_201_CREATED)
async def create_actor(
    payload: ActorIn, principal: Principal = Depends(ADMIN), db: AsyncSession = Depends(get_db)
) -> ActorCreated:
    """Mint a new actor with its own API key (shown only here; stored hashed)."""
    return await ws_svc.create_actor(db, principal, payload)


@router.get("/workspaces/{slug}/actors", response_model=list[ActorOut])
async def list_actors(principal: Principal = Depends(ADMIN), db: AsyncSession = Depends(get_db)) -> list[ActorOut]:
    """List actors in the workspace (names, roles, status — never keys)."""
    return await ws_svc.list_actors(db, principal)


@router.delete("/workspaces/{slug}/actors/{actor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_actor(
    actor_id: uuid.UUID, principal: Principal = Depends(ADMIN), db: AsyncSession = Depends(get_db)
) -> None:
    """Revoke an actor (its keys and grants stop working)."""
    await ws_svc.delete_actor(db, principal, actor_id)


@router.post("/workspaces/{slug}/token", response_model=ActorToken)
async def login_for_token(payload: TokenRequest, slug: str, db: AsyncSession = Depends(get_db)) -> ActorToken:
    """Exchange an actor (or legacy workspace) API key for a short-lived JWT."""
    return await ws_svc.exchange_key_for_token(db, slug, payload.api_key)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/tasks", response_model=list[TaskOut])
async def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    return await svc.list_tasks(db, principal, status_filter)


@router.post("/workspaces/{slug}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskIn, principal: Principal = Depends(WRITE_TASKS), db: AsyncSession = Depends(get_db)
) -> TaskOut:
    return await svc.create_task(db, principal, payload)


@router.put("/workspaces/{slug}/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    principal: Principal = Depends(WRITE_TASKS),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    return await svc.update_task(db, principal, task_id, payload)


@router.delete("/workspaces/{slug}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID, principal: Principal = Depends(WRITE_TASKS), db: AsyncSession = Depends(get_db)
) -> None:
    """Delete a task. Decisions that link to it are kept (their task_id SET NULLs)."""
    await svc.delete_task(db, principal, task_id)


@router.get("/workspaces/{slug}/tasks/{task_id}/decisions", response_model=list[DecisionOut])
async def list_task_decisions(
    task_id: uuid.UUID, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> list[DecisionOut]:
    """List decisions linked to a task."""
    return await svc.list_task_decisions(db, principal, task_id)


@router.get("/workspaces/{slug}/tasks/{task_id}/handoffs", response_model=list[HandoffOut])
async def list_task_handoffs(
    task_id: uuid.UUID, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> list[HandoffOut]:
    """List handoffs that reference a task (newest first)."""
    return await svc.list_task_handoffs(db, principal, task_id)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/decisions", response_model=list[DecisionOut])
async def list_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    return await svc.list_decisions(db, principal, limit)


@router.post("/workspaces/{slug}/decisions", response_model=DecisionOut, status_code=status.HTTP_201_CREATED)
async def create_decision(
    payload: DecisionIn, principal: Principal = Depends(WRITE_DECISIONS), db: AsyncSession = Depends(get_db)
) -> DecisionOut:
    return await svc.create_decision(db, principal, payload)


@router.delete("/workspaces/{slug}/decisions/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decision(
    decision_id: uuid.UUID, principal: Principal = Depends(WRITE_DECISIONS), db: AsyncSession = Depends(get_db)
) -> None:
    await svc.delete_decision(db, principal, decision_id)


# ---------------------------------------------------------------------------
# Session handoffs
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/handoffs", response_model=list[HandoffOut])
async def list_handoffs(
    status_filter: HandoffStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> list[HandoffOut]:
    """List handoffs in a workspace (newest first), optionally filtered by status."""
    return await svc.list_handoffs(db, principal, status_filter, limit)


@router.get("/workspaces/{slug}/handoffs/{handoff_id}", response_model=HandoffOut)
async def get_handoff(
    handoff_id: uuid.UUID, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> HandoffOut:
    return await svc.get_handoff(db, principal, handoff_id)


@router.post("/workspaces/{slug}/handoffs", response_model=HandoffOut, status_code=status.HTTP_201_CREATED)
async def create_handoff(
    payload: HandoffIn, principal: Principal = Depends(WRITE_HANDOFFS), db: AsyncSession = Depends(get_db)
) -> HandoffOut:
    """Record a session handoff so another session can resume safely."""
    return await svc.create_handoff(db, principal, payload)


@router.post("/workspaces/{slug}/handoffs/{handoff_id}/acknowledge", response_model=HandoffOut)
async def acknowledge_handoff(
    handoff_id: uuid.UUID, principal: Principal = Depends(WRITE_HANDOFFS), db: AsyncSession = Depends(get_db)
) -> HandoffOut:
    """Mark a handoff as picked up (open → acknowledged). Idempotent; 409 once resolved."""
    return await svc.acknowledge_handoff(db, principal, handoff_id)


@router.post("/workspaces/{slug}/handoffs/{handoff_id}/resolve", response_model=HandoffOut)
async def resolve_handoff(
    handoff_id: uuid.UUID, principal: Principal = Depends(WRITE_HANDOFFS), db: AsyncSession = Depends(get_db)
) -> HandoffOut:
    """Mark a handoff as completed (→ resolved). Idempotent."""
    return await svc.resolve_handoff(db, principal, handoff_id)


@router.delete("/workspaces/{slug}/handoffs/{handoff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_handoff(
    handoff_id: uuid.UUID, principal: Principal = Depends(WRITE_HANDOFFS), db: AsyncSession = Depends(get_db)
) -> None:
    await svc.delete_handoff(db, principal, handoff_id)


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/presence", response_model=list[PresenceOut])
async def list_presence(principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)) -> list[PresenceOut]:
    return await svc.list_presence(db, principal)


@router.post("/workspaces/{slug}/presence", response_model=PresenceOut)
async def update_presence(
    payload: PresenceIn, principal: Principal = Depends(PRESENCE), db: AsyncSession = Depends(get_db)
) -> PresenceOut:
    """Upsert a presence heartbeat for an actor, keyed on (workspace, actor)."""
    return await svc.update_presence(db, principal, payload)


# ---------------------------------------------------------------------------
# Real-time stream
# ---------------------------------------------------------------------------


def _ws_db_dependency(websocket: WebSocket):
    """``get_db`` honouring app-level dependency overrides (tests swap the DB)."""
    return websocket.app.dependency_overrides.get(get_db, get_db)


@router.websocket("/workspaces/{slug}/ws")
async def workspace_events(websocket: WebSocket, slug: str):
    """Stream workspace events.

    Auth via ``?api_key=`` / ``?token=`` or the ``X-API-Key`` header (browsers
    can't set WS headers, so query params are accepted).

    Every stored event carries a ``seq``. Reconnect with ``?since=<last seq>`` to
    replay what you missed before the live stream resumes. If the server can't
    replay the gap (too far behind, or the outbox was pruned) it sends
    ``{"type": "resync_required"}`` first: reload a snapshot over REST.
    """
    await websocket.accept()
    since_raw = websocket.query_params.get("since")
    try:
        since = int(since_raw) if since_raw is not None else None
    except ValueError:
        await websocket.close(code=1008, reason="invalid 'since'")
        return

    bus = await get_event_bus()
    # Subscribe BEFORE reading the backlog, so nothing committed in between is
    # lost; anything seen in both is dropped below by seq.
    async with bus.subscribe(slug) as queue:
        db_gen = _ws_db_dependency(websocket)()
        db = await anext(db_gen)
        try:
            key = websocket.query_params.get("api_key") or websocket.headers.get(settings.api_key_header)
            token = websocket.query_params.get("token")
            principal = await resolve_ws_principal(slug, db, key=key, token=token)
            if principal is None or not principal.has(Permission.read):
                await websocket.close(code=1008, reason="invalid credentials")
                return
            backlog: list[dict] = []
            complete = True
            if since is not None:
                backlog, complete = await events.events_since(db, principal.workspace, since)
        finally:
            await db_gen.aclose()

        try:
            if not complete:
                await websocket.send_json({"type": "resync_required", "workspace": slug})
            for envelope in backlog:
                await websocket.send_json(envelope)
            # Only skip exact duplicates of the backlog. Don't drop "older" seqs:
            # transactions can commit out of seq order, so a lower seq may
            # legitimately arrive after a higher one.
            replayed = {envelope["seq"] for envelope in backlog}
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=WS_HEARTBEAT_SECS)
                except TimeoutError:
                    # Idle: probe with an app-level keepalive so a dead or half-open
                    # client fails the send rather than holding the socket forever.
                    await websocket.send_json({"type": "ping"})
                    continue
                if replayed and event.get("seq") in replayed:
                    continue
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        except (asyncio.CancelledError, RuntimeError) as exc:  # connection dropped
            logger.debug("workspace_events closed for %s: %s", slug, exc)
