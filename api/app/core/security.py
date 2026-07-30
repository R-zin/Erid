"""Workspace authentication and per-action authorization.

A request resolves to a :class:`Principal`, which may act on a resource only if
it holds the matching :class:`Permission`. Four credential shapes are accepted
(highest precedence first — a bearer JWT, then ``X-API-Key``/``?api_key=``):

- **legacy workspace key** — the shared ``workspaces.api_key``. Maps to ``owner``
  (full access) so existing deployments keep working.
- **actor key** — a per-actor API key (``actors.key_hash`` holds only its
  SHA-256). Resolves to that actor's role + grants.
- **JWT bearer** — an Ed25519 token from ``POST /workspaces/{slug}/token``,
  resolved back to its actor.
- **open** — a workspace with no key at all: read/write fully open (back-compat).

Authorization is fine-grained: each route declares the action it requires via
:func:`require_action`.
"""

import hashlib
import secrets
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.core.tokens import verify_token
from app.db.session import get_db
from app.models.models import ROLE_GRANTS, Actor, ActorRole, Permission, Workspace
from app.services.workspace_service import get_or_create_workspace

# auto_error=False so we can return a precise 401/403 ourselves and so WS
# connections (which can't set headers easily) can pass the key as a query param.
_header_scheme = APIKeyHeader(name=settings.api_key_header, auto_error=False)
_query_scheme = APIKeyQuery(name="api_key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)


class PrincipalKind(str, Enum):
    legacy_key = "legacy_key"
    actor = "actor"
    open = "open"


@dataclass
class Principal:
    """An authenticated (or open) identity with a set of permissions."""

    kind: PrincipalKind
    workspace: Workspace
    role: ActorRole | None
    permissions: frozenset[Permission]
    actor_name: str | None = None

    def has(self, permission: Permission) -> bool:
        return Permission.owner in self.permissions or permission in self.permissions


def hash_api_key(raw: str) -> str:
    """Stable SHA-256 digest used to store/look up actor keys (never raw)."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _permissions_for(role: ActorRole, grants: frozenset[Permission]) -> frozenset[Permission]:
    """Resolve effective permissions: role defaults + explicit grants.

    The ``owner`` role implies every permission; we store a marker rather than
    enumerating them so ``has()`` short-circuits.
    """
    if role == ActorRole.owner:
        return frozenset({Permission.owner})
    return ROLE_GRANTS[role] | grants


async def _find_actor_by_key(db: AsyncSession, workspace: Workspace, raw: str) -> Actor | None:
    digest = hash_api_key(raw)
    result = await db.execute(
        select(Actor)
        .options(selectinload(Actor.grants))
        .where(Actor.workspace_id == workspace.id, Actor.key_hash == digest, Actor.active.is_(True))
    )
    actor = result.scalars().first()
    # Constant-time comparison to avoid leaking valid hashes via timing.
    if actor is not None and secrets.compare_digest(actor.key_hash or "", digest):
        return actor
    return None


async def _find_actor_by_name(db: AsyncSession, workspace: Workspace, name: str) -> Actor | None:
    result = await db.execute(
        select(Actor)
        .options(selectinload(Actor.grants))
        .where(Actor.workspace_id == workspace.id, Actor.name == name, Actor.active.is_(True))
    )
    return result.scalars().first()


async def _actor_principal(actor: Actor, workspace: Workspace) -> Principal:
    grants = frozenset(g.permission for g in actor.grants)
    return Principal(
        kind=PrincipalKind.actor,
        workspace=workspace,
        role=actor.role,
        permissions=_permissions_for(actor.role, grants),
        actor_name=actor.name,
    )


async def resolve_credentials(
    db: AsyncSession,
    workspace: Workspace,
    *,
    key: str | None,
    bearer: str | None,
) -> Principal | None:
    """Resolve presented credentials to a Principal, or ``None`` if they do not
    authenticate at all. Bearer JWT takes precedence over a raw key."""
    if workspace.api_key and key and secrets.compare_digest(key, workspace.api_key):
        # Legacy workspace key → full access (owner). Keeps old clients working.
        return Principal(
            kind=PrincipalKind.legacy_key,
            workspace=workspace,
            role=ActorRole.owner,
            permissions=frozenset({Permission.owner}),
        )

    if bearer:
        claims = verify_token(bearer)
        if claims and claims.get("workspace") == workspace.slug:
            if claims.get("role") == ActorRole.owner.value:
                # Token minted from the legacy workspace key acts as owner directly.
                return Principal(
                    kind=PrincipalKind.legacy_key,
                    workspace=workspace,
                    role=ActorRole.owner,
                    permissions=frozenset({Permission.owner}),
                    actor_name=claims["sub"],
                )
            actor = await _find_actor_by_name(db, workspace, claims["sub"])
            if actor is not None:
                return await _actor_principal(actor, workspace)
        # A presented-but-invalid bearer is an auth failure, not an open request.
        return None

    if key:
        actor = await _find_actor_by_key(db, workspace, key)
        if actor is not None:
            return await _actor_principal(actor, workspace)
    return None


async def resolve_principal(
    slug: str,
    db: AsyncSession,
    header_key: str | None,
    query_key: str | None,
    bearer: HTTPAuthorizationCredentials | None,
) -> Principal:
    """Resolve a request to a Principal, handling open workspaces.

    Unlike :func:`resolve_credentials`, this never fails for an open workspace
    (no key configured): it returns an open Principal with full access.
    """
    workspace = await get_or_create_workspace(db, slug)
    key = header_key or query_key
    bearer_token = bearer.credentials if bearer else None

    if not workspace.api_key:
        # Open workspace (no shared key). An actor credential may still carry
        # finer-grained permissions, but nothing is enforced here.
        principal = await resolve_credentials(db, workspace, key=key, bearer=bearer_token)
        if principal is not None:
            return principal
        return Principal(
            kind=PrincipalKind.open,
            workspace=workspace,
            role=None,
            permissions=frozenset({Permission.owner}),
        )

    principal = await resolve_credentials(db, workspace, key=key, bearer=bearer_token)
    if principal is None:
        if not (key or bearer_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"missing credentials (provide the {settings.api_key_header} header or a Bearer token)",
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid credentials")
    return principal


async def resolve_ws_principal(
    slug: str,
    db: AsyncSession,
    *,
    key: str | None,
    token: str | None,
) -> Principal | None:
    """Resolve a WebSocket connection (query/header credentials) to a Principal.

    Returns an open Principal for keyless workspaces, ``None`` when credentials
    are required but missing/invalid.
    """
    workspace = await get_or_create_workspace(db, slug)
    principal = await resolve_credentials(db, workspace, key=key, bearer=token)
    if principal is not None:
        return principal
    if not workspace.api_key and not (key or token):
        return Principal(
            kind=PrincipalKind.open,
            workspace=workspace,
            role=None,
            permissions=frozenset({Permission.owner}),
        )
    return None


def require_action(action: Permission) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """FastAPI dependency factory: resolve the principal and require ``action``."""

    async def dependency(
        slug: str,
        db: AsyncSession = Depends(get_db),
        header_key: str | None = Security(_header_scheme),
        query_key: str | None = Security(_query_scheme),
        bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    ) -> Principal:
        principal = await resolve_principal(slug, db, header_key, query_key, bearer)
        if not principal.has(action):
            who = principal.actor_name or (
                "legacy workspace key" if principal.kind == PrincipalKind.legacy_key else "anonymous"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"'{who}' lacks permission '{action.value}'",
            )
        return principal

    return dependency


# Back-compat alias: previously the only gate, equivalent to requiring read.
require_workspace_access = require_action(Permission.read)
