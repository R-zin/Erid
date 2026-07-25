from datetime import datetime,timedelta,timezone
from fastapi import APIRouter, Depends, HTTPException,Query
from sqlalchemy import or_,select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.models import Decision,Presence,Task,TaskStatus
from app.schemas.schemas import DecisionOut,TaskOut,WorkspaceSummary
from app.services.workspace_service improt get_or_create_workspace

router = APIRouter()

STALE_AFTER = timedelta(minutes=10)

@router.get("/workspaces/{slug}/search")
async def search_workspace(
        slug:str,
        q:str = Query(...,min_length=1),
        dbb:AsyncSession = Depends(get_db),
):
    workspace = await get_or_create_workspace(db,slug)
    like = f"%{q}%"

    decisions_result = await db.execute(select(Decision).where(Decison.workspace_id == workspace.id,
                                                               or_(Decision.title.ilike(like),
                                                                   Decision.reason.ilike(like)))
    tasks_result = await db.execute(select(Task).where(Task.workspace_id == workspace.id,
                                                       Task.title.ilike(like)))
    return {
        "query":q,
        "decisions":[DecisionOut.model_validate(d) for d in decisions_result.scalars().all()],
        "tasks":[TaskOut.model_validate(d) for d in tasks_result.scalars().all()],
    }
