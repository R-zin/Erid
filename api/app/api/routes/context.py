import asyncio
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import Column, select
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.keys import generate_api_key
from app.core.security import Principal, _find_actor_by_key, hash_api_key, require_action, resolve_ws_principal
from app.core.settings import settings
from app.core.tokens import issue_token
from app.db.session import get_db
from app.models.models import (
    ROLE_GRANTS,
    Actor,
    ActorRole,
    Decision,
    Grant,
    Permission,
    Presence,
    Task,
    TaskStatus,
    Workspace,
)
from app.schemas.schemas import (
    ActorCreated,
    ActorIn,
    ActorOut,
    ActorToken,
    DecisionIn,
    DecisionOut,
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
from app.services.event_bus import get_event_bus
from app.services.workspace_service import get_workspace_by_slug

logger = logging.getLogger("context_hub.routes")

router = APIRouter()

# A presence record is considered active if seen within this window.
STALE_AFTER = timedelta(minutes=10)


async def _publish(slug: str, event_type: str, data: dict) -> None:
    bus = await get_event_bus()
    await bus.publish(slug, {"type": event_type, "data": data})


def _search_vector(model: type) -> ColumnElement:
    """Reference the generated ``search_vector`` tsvector column on a model's table.

    The column exists only in Postgres (added by the FTS migration) and is not
    ORM-mapped, so it is attached to the model's ``Table`` for query use. Queries
    never SELECT it, so its presence in metadata does not affect ORM loading.
    """
    table = model.__table__
    if "search_vector" not in table.c:
        table.append_column(Column("search_vector", TSVECTOR))
    return table.c.search_vector


# ---------------------------------------------------------------------------
# Workspace provisioning
# ---------------------------------------------------------------------------


@router.post("/workspaces", response_model=WorkspaceCreated, status_code=status.HTTP_201_CREATED)
async def provision_workspace(
    slug: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceCreated:
    """Create a workspace and return its API key (shown only here).

    Provisioning is open so a brand-new workspace can be secured; if the
    workspace already exists its key is never re-disclosed.
    """
    existing = await get_workspace_by_slug(db, slug)
    if existing is not None:
        # Do not leak the key for an existing workspace.
        return WorkspaceCreated(slug=existing.slug, name=existing.name, created_at=existing.created_at, api_key=None)
    workspace = Workspace(slug=slug, name=slug, api_key=generate_api_key())
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return WorkspaceCreated(
        slug=workspace.slug, name=workspace.name, created_at=workspace.created_at, api_key=workspace.api_key
    )


@router.delete("/workspaces/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    principal: Principal = Depends(require_action(Permission.owner)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an entire workspace (owner only).

    Cascades its tasks, decisions, presences, and actors/grants. Tasks/decisions/
    presences/actors are removed via the ORM ``delete-orphan`` cascade on the
    workspace relationships (the ORM loads and bulk-deletes them); grants are
    removed by the DB-level ``ON DELETE CASCADE`` on their actor FK.
    """
    workspace = principal.workspace
    await db.delete(workspace)
    await db.commit()
    await _publish(workspace.slug, "workspace_deleted", {"slug": workspace.slug})


@router.get("/workspaces", response_model=list[WorkspaceListItem])
async def list_workspaces(db: AsyncSession = Depends(get_db)) -> list[WorkspaceListItem]:
    """List every workspace (slug, name, secured flag).

    Deliberately unauthenticated: there is no instance-wide principal to gate on
    (principals are per-workspace), a directory is needed to discover workspaces,
    and only non-secret metadata is exposed — keys are never returned. A keyless
    workspace must remain discoverable so it can later be secured.
    """
    result = await db.execute(select(Workspace).order_by(Workspace.slug))
    return [
        WorkspaceListItem(slug=w.slug, name=w.name, created_at=w.created_at, secured=bool(w.api_key))
        for w in result.scalars().all()
    ]


@router.post("/workspaces/{slug}/secure", response_model=WorkspaceSecured)
async def secure_workspace(slug: str, db: AsyncSession = Depends(get_db)) -> WorkspaceSecured:
    """Secure an open workspace by minting its workspace key (returned once).

    An open workspace (``api_key`` NULL) has no admin at all, so there is no
    credential to gate this on: anyone can claim it. That matches the existing
    provisioning model (``POST /workspaces`` is likewise open). The first caller
    becomes the de-facto owner by taking the disclosed key. If the workspace is
    already secured its key is never re-disclosed (use ``rotate-key`` instead).
    """
    workspace = await get_workspace_by_slug(db, slug)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"workspace '{slug}' not found")
    if workspace.api_key:
        return WorkspaceSecured(slug=workspace.slug, secured=True, api_key=None)
    workspace.api_key = generate_api_key()
    await db.commit()
    return WorkspaceSecured(slug=workspace.slug, secured=True, api_key=workspace.api_key)


@router.post("/workspaces/{slug}/rotate-key", response_model=WorkspaceKeyRotated)
async def rotate_workspace_key(
    principal: Principal = Depends(require_action(Permission.owner)),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceKeyRotated:
    """Rotate the workspace key (owner only). Returns the new key once.

    The old workspace key stops working immediately. Per-actor keys are
    unaffected (they are separate credentials), so existing actors keep access
    and the rotated key simply re-secures the legacy/owner path.
    """
    workspace = principal.workspace
    workspace.api_key = generate_api_key()
    await db.commit()
    return WorkspaceKeyRotated(slug=workspace.slug, api_key=workspace.api_key)


# ---------------------------------------------------------------------------
# Actors, access grants, and tokens
# ---------------------------------------------------------------------------


@router.post("/workspaces/{slug}/actors", response_model=ActorCreated, status_code=status.HTTP_201_CREATED)
async def create_actor(
    payload: ActorIn,
    principal: Principal = Depends(require_action(Permission.admin_keys)),
    db: AsyncSession = Depends(get_db),
) -> ActorCreated:
    """Mint a new actor with its own API key (shown only here).

    Requires the ``admin_keys`` permission. The raw key is never stored — only
    its SHA-256 — so it is disclosed exactly once in this response.
    """
    workspace = principal.workspace
    existing = await db.execute(select(Actor).where(Actor.workspace_id == workspace.id, Actor.name == payload.name))
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"actor '{payload.name}' already exists")

    raw_key = generate_api_key()
    actor = Actor(
        workspace_id=workspace.id,
        name=payload.name,
        role=payload.role,
        key_hash=hash_api_key(raw_key),
    )
    db.add(actor)
    await db.flush()  # get actor.id for grants
    grants = (
        [Grant(actor_id=actor.id, permission=p) for p in set(payload.permissions)]
        if payload.permissions is not None
        else [Grant(actor_id=actor.id, permission=p) for p in ROLE_GRANTS[payload.role]]
    )
    db.add_all(grants)
    await db.commit()
    await db.refresh(actor)
    return ActorCreated(
        id=actor.id,
        name=actor.name,
        role=actor.role,
        active=actor.active,
        created_at=actor.created_at,
        api_key=raw_key,
    )


@router.get("/workspaces/{slug}/actors", response_model=list[ActorOut])
async def list_actors(
    principal: Principal = Depends(require_action(Permission.admin_keys)),
    db: AsyncSession = Depends(get_db),
) -> list[ActorOut]:
    """List actors in the workspace (names, roles, status — never keys)."""
    result = await db.execute(select(Actor).where(Actor.workspace_id == principal.workspace.id).order_by(Actor.name))
    return [ActorOut.model_validate(a) for a in result.scalars().all()]


@router.delete("/workspaces/{slug}/actors/{actor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_actor(
    actor_id: uuid.UUID,
    principal: Principal = Depends(require_action(Permission.admin_keys)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an actor (delete it; its keys and grants stop working)."""
    result = await db.execute(select(Actor).where(Actor.id == actor_id, Actor.workspace_id == principal.workspace.id))
    actor = result.scalars().first()
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"actor '{actor_id}' not found")
    await db.delete(actor)
    await db.commit()


@router.post("/workspaces/{slug}/token", response_model=ActorToken)
async def login_for_token(
    payload: TokenRequest,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> ActorToken:
    """Exchange an actor (or legacy workspace) API key for a short-lived JWT.

    Clients then send the token as ``Authorization: Bearer <jwt>`` instead of
    re-sending the raw key on every request.
    """
    workspace = await get_workspace_by_slug(db, slug)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"workspace '{slug}' not found")

    name: str
    role: ActorRole | None
    if workspace.api_key and secrets.compare_digest(payload.api_key, workspace.api_key):
        name, role = workspace.slug, ActorRole.owner  # legacy key acts as owner
    else:
        actor = await _find_actor_by_key(db, workspace, payload.api_key)
        if actor is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key")
        name, role = actor.name, actor.role

    return ActorToken(
        access_token=issue_token(workspace_slug=slug, actor_name=name, role=role.value if role else None),
        expires_in=settings.jwt_ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/tasks", response_model=list[TaskOut])
async def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    principal: Principal = Depends(require_action(Permission.read)),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    workspace = principal.workspace
    stmt = select(Task).where(Task.workspace_id == workspace.id).order_by(Task.created_at)
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    result = await db.execute(stmt)
    return [TaskOut.model_validate(t) for t in result.scalars().all()]


@router.post("/workspaces/{slug}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskIn,
    principal: Principal = Depends(require_action(Permission.write_tasks)),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    workspace = principal.workspace
    task = Task(
        workspace_id=workspace.id,
        title=payload.title,
        assigned_to=payload.assigned_to,
        created_by=payload.created_by or principal.actor_name,
        status=payload.status,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    await _publish(workspace.slug, "task_created", TaskOut.model_validate(task).model_dump(mode="json"))
    return TaskOut.model_validate(task)


@router.put("/workspaces/{slug}/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    principal: Principal = Depends(require_action(Permission.write_tasks)),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    workspace = principal.workspace
    result = await db.execute(select(Task).where(Task.id == task_id, Task.workspace_id == workspace.id))
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"task '{task_id}' not found")
    if payload.title is not None:
        task.title = payload.title
    if payload.status is not None:
        task.status = payload.status
    if payload.assigned_to is not None:
        task.assigned_to = payload.assigned_to
    await db.commit()
    await db.refresh(task)
    await _publish(workspace.slug, "task_updated", TaskOut.model_validate(task).model_dump(mode="json"))
    return TaskOut.model_validate(task)


@router.delete("/workspaces/{slug}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    principal: Principal = Depends(require_action(Permission.write_tasks)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a task. Decisions that link to it are kept (their task_id SET NULLs)."""
    workspace = principal.workspace
    result = await db.execute(select(Task).where(Task.id == task_id, Task.workspace_id == workspace.id))
    task = result.scalars().first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"task '{task_id}' not found")
    await db.delete(task)
    await db.commit()
    await _publish(workspace.slug, "task_deleted", {"id": str(task_id), "workspace_id": str(workspace.id)})


@router.get("/workspaces/{slug}/tasks/{task_id}/decisions", response_model=list[DecisionOut])
async def list_task_decisions(
    task_id: uuid.UUID,
    principal: Principal = Depends(require_action(Permission.read)),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    """List decisions linked to a task (decision ↔ task linking)."""
    workspace = principal.workspace
    result = await db.execute(
        select(Decision)
        .where(Decision.workspace_id == workspace.id, Decision.task_id == task_id)
        .order_by(Decision.created_at.desc())
    )
    return [DecisionOut.model_validate(d) for d in result.scalars().all()]


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/decisions", response_model=list[DecisionOut])
async def list_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require_action(Permission.read)),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    workspace = principal.workspace
    stmt = (
        select(Decision).where(Decision.workspace_id == workspace.id).order_by(Decision.created_at.desc()).limit(limit)
    )
    result = await db.execute(stmt)
    return [DecisionOut.model_validate(d) for d in result.scalars().all()]


@router.post("/workspaces/{slug}/decisions", response_model=DecisionOut, status_code=status.HTTP_201_CREATED)
async def create_decision(
    payload: DecisionIn,
    principal: Principal = Depends(require_action(Permission.write_decisions)),
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    workspace = principal.workspace
    # If linking to a task, it must exist in this workspace.
    if payload.task_id is not None:
        task = (
            (await db.execute(select(Task).where(Task.id == payload.task_id, Task.workspace_id == workspace.id)))
            .scalars()
            .first()
        )
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"task '{payload.task_id}' not found in workspace",
            )
    decision = Decision(
        workspace_id=workspace.id,
        title=payload.title,
        reason=payload.reason,
        related_files=payload.related_files,
        made_by=payload.made_by or principal.actor_name,
        task_id=payload.task_id,
    )
    db.add(decision)
    await db.commit()
    await db.refresh(decision)
    await _publish(workspace.slug, "decision_created", DecisionOut.model_validate(decision).model_dump(mode="json"))
    return DecisionOut.model_validate(decision)


@router.delete("/workspaces/{slug}/decisions/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decision(
    decision_id: uuid.UUID,
    principal: Principal = Depends(require_action(Permission.write_decisions)),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a decision."""
    workspace = principal.workspace
    result = await db.execute(select(Decision).where(Decision.id == decision_id, Decision.workspace_id == workspace.id))
    decision = result.scalars().first()
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"decision '{decision_id}' not found")
    await db.delete(decision)
    await db.commit()
    await _publish(workspace.slug, "decision_deleted", {"id": str(decision_id), "workspace_id": str(workspace.id)})


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/presence", response_model=list[PresenceOut])
async def list_presence(
    principal: Principal = Depends(require_action(Permission.read)),
    db: AsyncSession = Depends(get_db),
) -> list[PresenceOut]:
    workspace = principal.workspace
    cutoff = datetime.now(UTC) - STALE_AFTER
    stmt = (
        select(Presence)
        .where(Presence.workspace_id == workspace.id, Presence.last_seen > cutoff)
        .order_by(Presence.last_seen.desc())
    )
    result = await db.execute(stmt)
    return [PresenceOut.model_validate(p) for p in result.scalars().all()]


@router.post("/workspaces/{slug}/presence", response_model=PresenceOut)
async def update_presence(
    payload: PresenceIn,
    principal: Principal = Depends(require_action(Permission.presence)),
    db: AsyncSession = Depends(get_db),
) -> PresenceOut:
    """Upsert a presence heartbeat for an actor, keyed on (workspace, actor).

    Implemented as a true atomic ``INSERT ... ON CONFLICT ... DO UPDATE`` against
    the ``(workspace_id, actor_name)`` unique constraint, using the Postgres or
    SQLite insert construct depending on the bound dialect. This removes the old
    read-then-insert race that would raise on concurrent heartbeats.
    """
    workspace = principal.workspace
    now = datetime.now(UTC)
    values = {
        "workspace_id": workspace.id,
        "actor_name": payload.actor_name,
        "actor_type": payload.actor_type,
        "current_file": payload.current_file,
        "current_task": payload.current_task,
        "last_seen": now,
    }
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(Presence).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["workspace_id", "actor_name"],
        set_={
            "actor_type": stmt.excluded.actor_type,
            "current_file": stmt.excluded.current_file,
            "current_task": stmt.excluded.current_task,
            "last_seen": stmt.excluded.last_seen,
        },
    )
    await db.execute(stmt)
    await db.commit()
    presence = (
        (
            await db.execute(
                select(Presence).where(Presence.workspace_id == workspace.id, Presence.actor_name == payload.actor_name)
            )
        )
        .scalars()
        .one()
    )
    await _publish(workspace.slug, "presence_updated", PresenceOut.model_validate(presence).model_dump(mode="json"))
    return PresenceOut.model_validate(presence)


# ---------------------------------------------------------------------------
# Real-time stream
# ---------------------------------------------------------------------------


@router.websocket("/workspaces/{slug}/ws")
async def workspace_events(websocket: WebSocket, slug: str):
    """Stream workspace events. Auth via ``?api_key=...`` / ``?token=...`` or the
    ``X-API-Key`` header when the workspace has a key configured (WS clients
    often can't set headers, so query params are also accepted)."""
    await websocket.accept()

    # Resolve workspace + enforce auth manually (no DI for WS query auth).
    db_gen = get_db()
    db = await anext(db_gen)
    try:
        key = websocket.query_params.get("api_key") or websocket.headers.get(settings.api_key_header)
        token = websocket.query_params.get("token")
        principal = await resolve_ws_principal(slug, db, key=key, token=token)
        if principal is None or not principal.has(Permission.read):
            await websocket.close(code=1008, reason="invalid credentials")
            return
    finally:
        await db_gen.aclose()

    bus = await get_event_bus()
    try:
        async with bus.subscribe(slug) as queue:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except (asyncio.CancelledError, RuntimeError) as exc:  # connection dropped
        logger.debug("workspace_events closed for %s: %s", slug, exc)
