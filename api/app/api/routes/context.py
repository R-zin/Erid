import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.keys import generate_api_key
from app.core.security import require_workspace_access
from app.db.session import get_db
from app.models.models import Decision, Presence, Task, TaskStatus, Workspace
from app.schemas.schemas import (
    DecisionIn,
    DecisionOut,
    PresenceIn,
    PresenceOut,
    TaskIn,
    TaskOut,
    TaskUpdate,
    WorkspaceCreated,
    WorkspaceSummary,
)
from app.services.event_bus import get_event_bus
from app.services.workspace_service import get_or_create_workspace, get_workspace_by_slug

logger = logging.getLogger("context_hub.routes")

router = APIRouter()

# A presence record is considered active if seen within this window.
STALE_AFTER = timedelta(minutes=10)


async def _publish(slug: str, event_type: str, data: dict) -> None:
    bus = await get_event_bus()
    await bus.publish(slug, {"type": event_type, "data": data})


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


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/tasks", response_model=list[TaskOut])
async def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    stmt = select(Task).where(Task.workspace_id == workspace.id).order_by(Task.created_at)
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    result = await db.execute(stmt)
    return [TaskOut.model_validate(t) for t in result.scalars().all()]


@router.post("/workspaces/{slug}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskIn,
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = Task(
        workspace_id=workspace.id,
        title=payload.title,
        assigned_to=payload.assigned_to,
        created_by=payload.created_by,
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
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
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


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/decisions", response_model=list[DecisionOut])
async def list_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    stmt = (
        select(Decision)
        .where(Decision.workspace_id == workspace.id)
        .order_by(Decision.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [DecisionOut.model_validate(d) for d in result.scalars().all()]


@router.post("/workspaces/{slug}/decisions", response_model=DecisionOut, status_code=status.HTTP_201_CREATED)
async def create_decision(
    payload: DecisionIn,
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    decision = Decision(
        workspace_id=workspace.id,
        title=payload.title,
        reason=payload.reason,
        related_files=payload.related_files,
        made_by=payload.made_by,
    )
    db.add(decision)
    await db.commit()
    await db.refresh(decision)
    await _publish(workspace.slug, "decision_created", DecisionOut.model_validate(decision).model_dump(mode="json"))
    return DecisionOut.model_validate(decision)


# ---------------------------------------------------------------------------
# Presence
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/presence", response_model=list[PresenceOut])
async def list_presence(
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> list[PresenceOut]:
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
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
    workspace: Workspace = Depends(require_workspace_access),
    db: AsyncSession = Depends(get_db),
) -> PresenceOut:
    """Upsert a presence heartbeat for an actor, keyed on (workspace, actor)."""
    result = await db.execute(
        select(Presence).where(
            Presence.workspace_id == workspace.id,
            Presence.actor_name == payload.actor_name,
        )
    )
    presence = result.scalars().first()
    if presence is None:
        presence = Presence(workspace_id=workspace.id, actor_name=payload.actor_name)
        db.add(presence)
    presence.actor_type = payload.actor_type
    presence.current_file = payload.current_file
    presence.current_task = payload.current_task
    presence.last_seen = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(presence)
    await _publish(workspace.slug, "presence_updated", PresenceOut.model_validate(presence).model_dump(mode="json"))
    return PresenceOut.model_validate(presence)


# ---------------------------------------------------------------------------
# Search & summary (open reads)
# ---------------------------------------------------------------------------


@router.get("/workspaces/{slug}/search")
async def search_workspace(
    slug: str,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    workspace = await get_or_create_workspace(db, slug)
    like = f"%{q}%"
    decisions_result = await db.execute(
        select(Decision).where(
            Decision.workspace_id == workspace.id,
            or_(Decision.title.ilike(like), Decision.reason.ilike(like)),
        )
    )
    tasks_result = await db.execute(
        select(Task).where(Task.workspace_id == workspace.id, Task.title.ilike(like))
    )
    return {
        "query": q,
        "decisions": [DecisionOut.model_validate(d) for d in decisions_result.scalars().all()],
        "tasks": [TaskOut.model_validate(t) for t in tasks_result.scalars().all()],
    }


@router.get("/workspaces/{slug}/summary", response_model=WorkspaceSummary)
async def workspace_summary(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummary:
    workspace = await get_or_create_workspace(db, slug)
    tasks = (await db.execute(select(Task).where(Task.workspace_id == workspace.id))).scalars().all()
    decisions = (await db.execute(select(Decision).where(Decision.workspace_id == workspace.id))).scalars().all()
    presences = (
        await db.execute(
            select(Presence).where(
                Presence.workspace_id == workspace.id,
                Presence.last_seen > datetime.now(timezone.utc) - STALE_AFTER,
            )
        )
    ).scalars().all()
    active_developers = sorted({p.actor_name for p in presences})
    return WorkspaceSummary(
        slug=workspace.slug,
        name=workspace.name,
        task_count=len(tasks),
        open_task_count=sum(1 for t in tasks if t.status != TaskStatus.done),
        decision_count=len(decisions),
        active_developers=active_developers,
    )


# ---------------------------------------------------------------------------
# Real-time stream
# ---------------------------------------------------------------------------


@router.websocket("/workspaces/{slug}/ws")
async def workspace_events(websocket: WebSocket, slug: str):
    """Stream workspace events. Auth via ``?api_key=...`` when the workspace
    has a key configured (WebSocket clients can't easily set headers)."""
    await websocket.accept()

    # Resolve workspace + enforce key manually (no DI for WS query auth).
    db_gen = get_db()
    db = await anext(db_gen)
    try:
        workspace = await get_or_create_workspace(db, slug)
        if workspace.api_key:
            provided = websocket.query_params.get("api_key")
            if not provided or not secrets.compare_digest(provided, workspace.api_key):
                await websocket.close(code=1008, reason="invalid api key")
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
