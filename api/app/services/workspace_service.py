from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Base
from app.models.models import Workspace


async def get_or_create_workspace(db: AsyncSession, slug: str) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.slug == slug))
    workspace = result.scalars().first()
    if workspace is None:
        workspace = Workspace(slug=slug, name=slug)
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
    return workspace
