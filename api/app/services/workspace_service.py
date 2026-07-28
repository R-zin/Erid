from app.core.keys import generate_api_key
from app.models.models import Workspace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_workspace_by_slug(db: AsyncSession, slug: str) -> Workspace | None:
    result = await db.execute(select(Workspace).where(Workspace.slug == slug))
    return result.scalars().first()


async def get_or_create_workspace(db: AsyncSession, slug: str, *, mint_key: bool = False) -> Workspace:
    """Fetch a workspace, creating it if needed.

    ``mint_key`` controls whether a new workspace gets a generated API key.
    Implicit creation from unauthenticated reads stays open (no key); explicit
    provisioning endpoints mint a key so the workspace starts secured.
    """
    workspace = await get_workspace_by_slug(db, slug)
    if workspace is None:
        workspace = Workspace(slug=slug, name=slug, api_key=generate_api_key() if mint_key else None)
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
    return workspace
