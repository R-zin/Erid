from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import Decision, Presence, Task, TaskStatus, Workspace
from app.schemas.schemas import DecisionOut, TaskOut, WorkspaceSummary
from app.services.workspace_service import get_or_create_workspace

router = APIRouter()

STALE_AFTER = timedelta(minutes=10)


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
            or_(Decision.title.ilike(like), Decision.reason.ilike(like))
        )
    )
    tasks_result = await db.execute(
        select(Task).where(
            Task.workspace_id == workspace.id,
            Task.title.ilike(like)
        )
    )
    return {
        "query": q,
        "decisions": [DecisionOut.model_validate(d) for d in decisions_result.scalars().all()],
        "tasks": [TaskOut.model_validate(d) for d in tasks_result.scalars().all()],
    }


@router.get("/workspaces/{slug}/summary")
async def workspace_summary(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    workspace = await get_or_create_workspace(db, slug)
    tasks_result = await db.execute(select(Task).where(Task.workspace_id == workspace.id))
    tasks = tasks_result.scalars().all()
    decisions_result = await db.execute(select(Decision).where(Decision.workspace_id == workspace.id))
    decisions = decisions_result.scalars().all()
    presences_result = await db.execute(
        select(Presence).where(
            Presence.workspace_id == workspace.id,
            Presence.last_seen > datetime.now(timezone.utc) - STALE_AFTER
        )
    )
    active_developers = list({p.actor_name for p in presences_result.scalars().all()})
    return WorkspaceSummary(
        slug=workspace.slug,
        name=workspace.name,
        task_count=len(tasks),
        open_task_count=sum(1 for t in tasks if t.status != TaskStatus.done),
        decision_count=len(decisions),
        active_developers=active_developers,
    )
