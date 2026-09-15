"""Secured search & summary routes.

These handlers mirror ``/search`` and ``/summary`` from ``context.py`` but are
scoped behind ``Depends(require_action(Permission.read))`` so they resolve the
caller's workspace via ``principal.workspace`` (auth-aware) instead of the open
``get_or_create_workspace`` call. They are the sole handlers for these paths
(the legacy open versions were removed from ``context.py``).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

# Reuse the same search-vector helper and staleness window as context.py.
from app.api.routes.context import STALE_AFTER, _search_vector
from app.core.security import Principal, require_action
from app.db.session import get_db
from app.models.models import Decision, Permission, Presence, Task, TaskStatus
from app.schemas.schemas import DecisionOut, TaskOut, WorkspaceSummary

router = APIRouter()


@router.get("/workspaces/{slug}/search")
async def search_workspace(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require_action(Permission.read)),
    db: AsyncSession = Depends(get_db),
):
    """Search decisions and tasks in a workspace (requires the read permission).

    On Postgres this uses full-text search over the generated ``search_vector``
    columns (stemmed matching, ranked by relevance). On other backends (SQLite,
    used by tests) it falls back to a substring match.
    """
    workspace = principal.workspace

    if db.bind.dialect.name == "postgresql":
        query = func.websearch_to_tsquery("english", q)
        decisions_result = await db.execute(
            select(Decision)
            .where(Decision.workspace_id == workspace.id, _search_vector(Decision).op("@@")(query))
            .order_by(func.ts_rank(_search_vector(Decision), query).desc())
            .limit(limit)
        )
        tasks_result = await db.execute(
            select(Task)
            .where(Task.workspace_id == workspace.id, _search_vector(Task).op("@@")(query))
            .order_by(func.ts_rank(_search_vector(Task), query).desc())
            .limit(limit)
        )
    else:
        # Escape LIKE wildcards so %, _, and \ in the query match literally;
        # backslash must be escaped first (escaping % before \ would double-escape).
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        decisions_result = await db.execute(
            select(Decision)
            .where(
                Decision.workspace_id == workspace.id,
                or_(
                    Decision.title.ilike(like, escape="\\"),
                    Decision.reason.ilike(like, escape="\\"),
                ),
            )
            .limit(limit)
        )
        tasks_result = await db.execute(
            select(Task).where(Task.workspace_id == workspace.id, Task.title.ilike(like, escape="\\")).limit(limit)
        )

    return {
        "query": q,
        "decisions": [DecisionOut.model_validate(d) for d in decisions_result.scalars().all()],
        "tasks": [TaskOut.model_validate(t) for t in tasks_result.scalars().all()],
    }


@router.get("/workspaces/{slug}/summary", response_model=WorkspaceSummary)
async def workspace_summary(
    principal: Principal = Depends(require_action(Permission.read)),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummary:
    workspace = principal.workspace
    # Aggregate in SQL — loading every Task/Decision row just to count it in
    # Python degrades badly as a workspace grows. Presence stays a row fetch
    # because the response needs the actor names, not just a count.
    task_count = (
        await db.execute(select(func.count()).select_from(Task).where(Task.workspace_id == workspace.id))
    ).scalar_one()
    open_task_count = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.workspace_id == workspace.id, Task.status != TaskStatus.done)
        )
    ).scalar_one()
    decision_count = (
        await db.execute(select(func.count()).select_from(Decision).where(Decision.workspace_id == workspace.id))
    ).scalar_one()
    presences = (
        (
            await db.execute(
                select(Presence).where(
                    Presence.workspace_id == workspace.id,
                    Presence.last_seen > datetime.now(UTC) - STALE_AFTER,
                )
            )
        )
        .scalars()
        .all()
    )
    active_developers = sorted({p.actor_name for p in presences})
    return WorkspaceSummary(
        slug=workspace.slug,
        name=workspace.name,
        task_count=task_count,
        open_task_count=open_task_count,
        decision_count=decision_count,
        active_developers=active_developers,
    )
