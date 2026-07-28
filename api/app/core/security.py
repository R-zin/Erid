"""API-key authentication, one key per workspace.

A workspace can carry an ``api_key``. When set, all read/write routes for that
workspace require the ``X-API-Key`` header to match. Workspaces created without
an explicit key get a generated one; a workspace created implicitly (via an
unauthenticated read) is "open" until a key is assigned.

Workspaces auto-provision on first use (a read or a write) and start "open"
(no key). Only the explicit ``POST /workspaces`` provisioning endpoint mints a
key, so a workspace is secured from the moment it is deliberately created.

This is intentionally minimal — a single shared secret per workspace — per the
roadmap. Full JWT/OAuth is a documented future step, not built here.
"""

import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.session import get_db
from app.models.models import Workspace
from app.services.workspace_service import get_or_create_workspace

# auto_error=False so we can return a precise 401/403 ourselves and so WS
# connections (which can't set headers easily) can pass the key as a query
# param instead.
_header_scheme = APIKeyHeader(name=settings.api_key_header, auto_error=False)
_query_scheme = APIKeyQuery(name="api_key", auto_error=False)


async def require_workspace_access(
    slug: str,
    db: AsyncSession = Depends(get_db),
    header_key: str | None = Security(_header_scheme),
    query_key: str | None = Security(_query_scheme),
) -> Workspace:
    """Resolve the workspace (creating an open one on first use) and enforce
    its API key if one is set."""
    workspace = await get_or_create_workspace(db, slug)

    if not workspace.api_key:
        # Open workspace (no key configured yet).
        return workspace

    provided = header_key or query_key
    if provided is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing API key (provide the {settings.api_key_header} header)",
        )
    if not secrets.compare_digest(provided, workspace.api_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid API key")
    return workspace
