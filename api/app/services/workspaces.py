"""Workspace lifecycle, actors, and token exchange.

Raw keys (the legacy workspace key and per-actor keys) are generated here,
returned exactly once to the caller, and stored only as SHA-256 digests.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.core.keys import generate_api_key, hash_api_key, key_matches
from app.core.settings import settings
from app.core.tokens import issue_token, key_fingerprint
from app.models.models import ROLE_GRANTS, Actor, ActorRole, Grant, Workspace
from app.schemas.schemas import (
    ActorCreated,
    ActorIn,
    ActorOut,
    ActorToken,
    WorkspaceCreated,
    WorkspaceKeyRotated,
    WorkspaceListItem,
    WorkspaceSecured,
)
from app.services import events
from app.services.errors import Conflict, Forbidden, NotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:  # security imports this module; avoid the cycle at runtime
    from app.core.security import Principal


async def get_workspace_by_slug(db: AsyncSession, slug: str) -> Workspace | None:
    result = await db.execute(select(Workspace).where(Workspace.slug == slug))
    return result.scalars().first()


async def get_or_create_workspace(db: AsyncSession, slug: str) -> Workspace:
    """Fetch a workspace, creating it *open* (keyless) if it doesn't exist.

    Only reachable when ``allow_open_workspaces`` is on; explicit provisioning
    (:func:`provision_workspace`) mints a key so the workspace starts secured.
    """
    workspace = await get_workspace_by_slug(db, slug)
    if workspace is None:
        workspace = Workspace(slug=slug, name=slug)
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
    return workspace


async def list_workspaces(db: AsyncSession) -> list[WorkspaceListItem]:
    result = await db.execute(select(Workspace).order_by(Workspace.slug))
    return [
        WorkspaceListItem(slug=w.slug, name=w.name, created_at=w.created_at, secured=w.secured)
        for w in result.scalars().all()
    ]


async def provision_workspace(db: AsyncSession, slug: str) -> WorkspaceCreated:
    """Create a secured workspace and return its key (shown only here).

    If the workspace already exists its key is never re-disclosed.
    """
    existing = await get_workspace_by_slug(db, slug)
    if existing is not None:
        return WorkspaceCreated(slug=existing.slug, name=existing.name, created_at=existing.created_at, api_key=None)
    raw = generate_api_key()
    workspace = Workspace(slug=slug, name=slug, api_key_hash=hash_api_key(raw))
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return WorkspaceCreated(slug=workspace.slug, name=workspace.name, created_at=workspace.created_at, api_key=raw)


async def secure_workspace(db: AsyncSession, slug: str) -> WorkspaceSecured:
    """Claim an open workspace by minting its key (returned once).

    Unauthenticated by design: an open workspace has no admin to gate on. Refused
    outright when ``allow_open_workspaces`` is off.
    """
    workspace = await get_workspace_by_slug(db, slug)
    if workspace is None:
        raise NotFound(f"workspace '{slug}' not found")
    if workspace.secured:
        return WorkspaceSecured(slug=workspace.slug, secured=True, api_key=None)
    if not settings.allow_open_workspaces:
        raise Forbidden(
            "open workspaces are disabled (ERID_ALLOW_OPEN_WORKSPACES=0), so an unauthenticated "
            "caller cannot claim one; provision with POST /api/workspaces?slug= instead"
        )
    raw = generate_api_key()
    workspace.api_key_hash = hash_api_key(raw)
    await db.commit()
    return WorkspaceSecured(slug=workspace.slug, secured=True, api_key=raw)


async def rotate_workspace_key(db: AsyncSession, principal: Principal) -> WorkspaceKeyRotated:
    """Replace the workspace key; the old one stops working. Actor keys are unaffected."""
    raw = generate_api_key()
    principal.workspace.api_key_hash = hash_api_key(raw)
    await db.commit()
    return WorkspaceKeyRotated(slug=principal.workspace.slug, api_key=raw)


async def delete_workspace(db: AsyncSession, principal: Principal) -> None:
    """Delete a workspace and everything in it (ORM + FK cascades)."""
    workspace = principal.workspace
    # Ephemeral: the outbox rows go with the workspace, so don't store this one.
    await events.emit(db, workspace, "workspace_deleted", {"slug": workspace.slug}, persist=False)
    await db.delete(workspace)
    await events.commit(db)


# ---------------------------------------------------------------------------
# Actors and tokens
# ---------------------------------------------------------------------------


async def create_actor(db: AsyncSession, principal: Principal, payload: ActorIn) -> ActorCreated:
    workspace = principal.workspace
    existing = await db.execute(select(Actor).where(Actor.workspace_id == workspace.id, Actor.name == payload.name))
    if existing.scalars().first() is not None:
        raise Conflict(f"actor '{payload.name}' already exists")

    raw = generate_api_key()
    actor = Actor(workspace_id=workspace.id, name=payload.name, role=payload.role, key_hash=hash_api_key(raw))
    db.add(actor)
    await db.flush()  # assigns actor.id for the grants
    permissions = set(payload.permissions) if payload.permissions is not None else ROLE_GRANTS[payload.role]
    db.add_all([Grant(actor_id=actor.id, permission=p) for p in permissions])
    await db.commit()
    await db.refresh(actor)
    return ActorCreated(
        id=actor.id, name=actor.name, role=actor.role, active=actor.active, created_at=actor.created_at, api_key=raw
    )


async def list_actors(db: AsyncSession, principal: Principal) -> list[ActorOut]:
    result = await db.execute(select(Actor).where(Actor.workspace_id == principal.workspace.id).order_by(Actor.name))
    return [ActorOut.model_validate(a) for a in result.scalars().all()]


async def delete_actor(db: AsyncSession, principal: Principal, actor_id: uuid.UUID) -> None:
    result = await db.execute(select(Actor).where(Actor.id == actor_id, Actor.workspace_id == principal.workspace.id))
    actor = result.scalars().first()
    if actor is None:
        raise NotFound(f"actor '{actor_id}' not found")
    await db.delete(actor)
    await db.commit()


async def exchange_key_for_token(db: AsyncSession, slug: str, raw_key: str) -> ActorToken:
    """Exchange an actor (or legacy workspace) key for a short-lived JWT."""
    workspace = await get_workspace_by_slug(db, slug)
    if workspace is None:
        raise NotFound(f"workspace '{slug}' not found")

    if key_matches(raw_key, workspace.api_key_hash):
        # Legacy key acts as owner; its subject is the workspace slug.
        token = issue_token(
            workspace_slug=slug,
            subject=workspace.slug,
            role=ActorRole.owner.value,
            workspace_id=str(workspace.id),
            key_fingerprint=key_fingerprint(workspace.api_key_hash),
        )
    else:
        actor = (
            (
                await db.execute(
                    select(Actor)
                    .options(selectinload(Actor.grants))
                    .where(
                        Actor.workspace_id == workspace.id,
                        Actor.key_hash == hash_api_key(raw_key),
                        Actor.active.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )
        if actor is None:
            raise Forbidden("invalid api key")
        token = issue_token(
            workspace_slug=slug,
            subject=str(actor.id),
            role=actor.role.value,
            name=actor.name,
            workspace_id=str(workspace.id),
        )

    return ActorToken(access_token=token, expires_in=settings.jwt_ttl_seconds)
