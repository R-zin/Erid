"""Search & summary routes (read-only, behind ``Permission.read``)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal, require_action
from app.db.session import get_db
from app.models.models import Permission
from app.schemas.schemas import SearchResults, WorkspaceSummary
from app.services import context as svc

router = APIRouter()

READ = require_action(Permission.read)


@router.get("/workspaces/{slug}/search", response_model=SearchResults)
async def search_workspace(
    q: str = Query(..., min_length=1, max_length=1000),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> SearchResults:
    """Search decisions and tasks (Postgres full-text search; substring elsewhere)."""
    return await svc.search(db, principal, q, limit)


@router.get("/workspaces/{slug}/summary", response_model=WorkspaceSummary)
async def workspace_summary(
    principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> WorkspaceSummary:
    """Counts + open handoffs + active developers."""
    return await svc.summary(db, principal)
