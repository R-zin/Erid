"""Social login (OAuth) routes.

``login`` and ``callback`` are *open* endpoints: they authenticate a human
against Google/GitHub and hand back the same internal Ed25519 JWT the dashboard
already uses. ``login`` redirects the browser to the provider; ``callback``
validates the signed state, fetches the caller's identity, resolves it to a
workspace ``Actor`` under the admission policy below, mints a token, and
redirects to the dashboard with the token in the URL fragment.

Admission policy (see ``_resolve_or_create_oauth_actor``):

1. An identity already linked to an actor **in this workspace** logs in as that
   actor. Identities are per-workspace: a link made in workspace A is never
   consulted for workspace B.
2. Otherwise, a valid **invitation** (minted by a workspace admin for a specific
   pre-created actor, carried through the signed state) links the identity to
   that actor. Invitations are single-use: they only redeem while the actor has
   no linked identity, and may pin a verified email.
3. Otherwise, **self-join** (a fresh ``writer`` actor) is allowed only for an
   *open* (keyless) workspace and only while ``allow_open_workspaces`` is on.
   A secured workspace refuses with 403.
"""

import secrets
import uuid
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import oauth
from app.core.security import Principal, require_action
from app.core.settings import settings
from app.core.tokens import issue_token
from app.db.session import get_db
from app.models.models import Actor, ActorRole, OAuthIdentity, Permission, Workspace
from app.schemas.schemas import OAuthInvite, OAuthInviteIn
from app.services.workspaces import get_or_create_workspace, get_workspace_by_slug

router = APIRouter()

ProviderName = Literal["google", "github"]

ADMIN = require_action(Permission.admin_keys)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _verify_invite_for(invite: str, slug: str) -> dict:
    """Verify an invite's signature/expiry and that it targets ``slug``."""
    try:
        payload = oauth.verify_invite(invite)
    except oauth.SignatureExpired:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invitation expired") from None
    except oauth.BadSignature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid invitation") from None
    if payload["slug"] != slug:
        raise _forbidden("invitation is for a different workspace")
    return payload


@router.get("/auth/{provider}/login", name="oauth_login")
async def oauth_login(
    provider: str,
    slug: str = Query(min_length=1, max_length=128),
    invite: str | None = Query(default=None, min_length=1, max_length=2048),
) -> RedirectResponse:
    """Begin the OAuth flow: redirect the browser to the provider.

    ``slug`` names the workspace to log in to. A first-time identity may only
    join a *secured* workspace with an ``invite`` (from
    ``POST /workspaces/{slug}/actors/{actor_id}/oauth-invite``); open workspaces
    allow self-join while ``ERID_ALLOW_OPEN_WORKSPACES`` is on. Requires the
    provider to be configured (``ERID_OAUTH_<PROVIDER>_*``) and
    ``ERID_SESSION_SECRET`` to be set.
    """
    if provider not in oauth.PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown provider '{provider}'")
    if not settings.session_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oauth not configured (no session secret)"
        )
    if not oauth.configured(provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"provider '{provider}' not configured"
        )
    if invite is not None:
        _verify_invite_for(invite, slug)  # fail fast, before the provider round-trip
    url = oauth.build_authorize_url(provider, slug, invite)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/auth/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Complete the flow: mint a JWT for the resolved actor and return to the SPA.

    The token travels in the URL *fragment* (``#/oauth/callback?token=…``) so it
    never reaches the server, logs, or the Referer header. The dashboard reads
    the fragment on load and persists the token.
    """
    if provider not in oauth.PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown provider '{provider}'")
    if not settings.session_secret or not oauth.configured(provider):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oauth not configured")

    try:
        payload = oauth.verify_state(state)
    except oauth.SignatureExpired:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="oauth state expired") from None
    except oauth.BadSignature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid oauth state") from None
    if payload.get("provider") != provider or not payload.get("slug"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="oauth state/provider mismatch")
    slug = payload["slug"]
    invite = payload.get("invite")

    try:
        profile = await (oauth.fetch_google_profile(code) if provider == "google" else oauth.fetch_github_profile(code))
    except Exception as exc:  # provider/token exchange failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"failed to fetch {provider} profile"
        ) from exc

    actor = await _resolve_or_create_oauth_actor(db, provider, profile, slug, invite=invite)
    # ``sub`` is the actor's id, never its name: verification resolves by id
    # within the workspace, so a token can't alias a same-named actor.
    token = issue_token(workspace_slug=slug, subject=str(actor.id), role=actor.role.value, name=actor.name)

    # quote_via=quote (not quote_plus) keeps the JWT's [A-Za-z0-9._-] chars
    # literal in the fragment, so clients/tests can split it on "&" simply.
    fragment = urlencode({"token": token, "slug": slug, "name": actor.name}, quote_via=quote)
    redirect = f"{settings.oauth_web_base}/#/oauth/callback?{fragment}"
    return RedirectResponse(redirect, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post(
    "/workspaces/{slug}/actors/{actor_id}/oauth-invite",
    response_model=OAuthInvite,
    status_code=status.HTTP_201_CREATED,
)
async def create_oauth_invite(
    actor_id: uuid.UUID,
    payload: OAuthInviteIn | None = None,
    principal: Principal = Depends(ADMIN),
    db: AsyncSession = Depends(get_db),
) -> OAuthInvite:
    """Invite a person to log in as an existing actor via Google/GitHub (admin only).

    Create the actor first (``POST /workspaces/{slug}/actors``) with the role it
    should have, then mint an invite for it. The first OAuth login carrying the
    invite links that provider account to the actor; afterwards the invite is
    spent. Optionally pin ``email`` so only an account with that verified email
    can redeem it.
    """
    if not settings.session_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oauth not configured (no session secret)"
        )
    workspace = principal.workspace
    actor = (
        (await db.execute(select(Actor).where(Actor.id == actor_id, Actor.workspace_id == workspace.id)))
        .scalars()
        .first()
    )
    if actor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"actor '{actor_id}' not found")
    if not actor.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"actor '{actor.name}' is inactive")
    if await _actor_has_identity(db, actor):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"actor '{actor.name}' already has a linked login"
        )

    email = (payload.email.strip().lower() or None) if payload and payload.email else None
    invite = oauth.make_invite(slug=workspace.slug, actor_id=str(actor.id), email=email)
    query = urlencode({"slug": workspace.slug, "invite": invite})
    return OAuthInvite(
        actor_id=actor.id,
        actor_name=actor.name,
        invite=invite,
        email=email,
        expires_in=settings.oauth_invite_ttl_seconds,
        login_urls={
            name: f"{settings.oauth_redirect_base}/api/auth/{name}/login?{query}"
            for name in oauth.PROVIDERS
            if oauth.configured(name)
        },
    )


async def _actor_has_identity(db: AsyncSession, actor: Actor) -> bool:
    result = await db.execute(select(OAuthIdentity.id).where(OAuthIdentity.actor_id == actor.id).limit(1))
    return result.first() is not None


async def _resolve_or_create_oauth_actor(
    db: AsyncSession,
    provider: ProviderName,
    profile: oauth.OAuthProfile,
    slug: str,
    *,
    invite: str | None = None,
) -> Actor:
    """Map an external OAuth identity to an ``Actor`` in the target workspace.

    Applies the admission policy in the module docstring: existing link in
    *this* workspace → invitation → open-workspace self-join → refuse.
    """
    # Honour closed mode: never create a workspace for an unknown slug there.
    if settings.allow_open_workspaces:
        workspace: Workspace = await get_or_create_workspace(db, slug)
    else:
        workspace = await get_workspace_by_slug(db, slug)
        if workspace is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"workspace '{slug}' not found")

    # 1. Existing link — scoped to this workspace only.
    result = await db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_subject == profile.subject,
            OAuthIdentity.workspace_id == workspace.id,
        )
    )
    identity = result.scalars().first()
    if identity is not None:
        actor = await db.get(Actor, identity.actor_id)
        if actor is None or actor.workspace_id != workspace.id:
            raise _forbidden("oauth identity is not linked to this workspace")
        if not actor.active:
            # A revoked actor stays revoked: never silently re-admit it as a new one.
            raise _forbidden(f"actor '{actor.name}' has been deactivated")
        return actor

    # 2. Invitation for a pre-created actor.
    if invite:
        return await _redeem_invite(db, workspace, provider, profile, invite)

    # 3. Self-join: open workspaces only, and only while open mode is on.
    if workspace.secured:
        raise _forbidden(f"workspace '{slug}' is secured: ask an owner for an invitation to log in")
    if not settings.allow_open_workspaces:
        raise _forbidden(f"open workspaces are disabled: ask an owner of '{slug}' for an invitation")

    name = await _unique_actor_name(db, workspace, _candidate_name(provider, profile))
    actor = Actor(workspace_id=workspace.id, name=name, role=ActorRole.writer, key_hash=None, active=True)
    db.add(actor)
    await db.flush()  # materialize actor.id for the FK
    _link_identity(db, workspace, actor, provider, profile)
    await _commit_link(db)
    await db.refresh(actor)
    return actor


async def _redeem_invite(
    db: AsyncSession,
    workspace: Workspace,
    provider: ProviderName,
    profile: oauth.OAuthProfile,
    invite: str,
) -> Actor:
    """Link ``profile`` to the actor an invitation names (single-use)."""
    payload = _verify_invite_for(invite, workspace.slug)
    try:
        actor_id = uuid.UUID(str(payload["actor_id"]))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid invitation") from None

    # Lock the actor row (Postgres) so two concurrent redemptions serialize on
    # the "already linked?" check below.
    actor = (
        (
            await db.execute(
                select(Actor).where(Actor.id == actor_id, Actor.workspace_id == workspace.id).with_for_update()
            )
        )
        .scalars()
        .first()
    )
    if actor is None or not actor.active:
        raise _forbidden("invitation is no longer valid")

    pinned = payload.get("email")
    if pinned and not (profile.email_verified and profile.email and profile.email.lower() == pinned):
        raise _forbidden("invitation is for a different email address")

    if await _actor_has_identity(db, actor):
        raise _forbidden("invitation has already been used")

    _link_identity(db, workspace, actor, provider, profile)
    await _commit_link(db)
    await db.refresh(actor)
    return actor


def _link_identity(
    db: AsyncSession, workspace: Workspace, actor: Actor, provider: ProviderName, profile: oauth.OAuthProfile
) -> None:
    db.add(
        OAuthIdentity(
            workspace_id=workspace.id,
            provider=provider,
            provider_subject=profile.subject,
            email=profile.email,
            display_name=profile.display_name,
            actor_id=actor.id,
        )
    )


async def _commit_link(db: AsyncSession) -> None:
    """Commit a new identity link; a concurrent duplicate login is a 409, not a 500."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="login raced with another login; please retry"
        ) from None


def _candidate_name(provider: str, profile: oauth.OAuthProfile) -> str:
    """A readable default actor name from the provider profile."""
    if provider == "github" and profile.login:
        return profile.login
    if profile.email:
        return profile.email.split("@", 1)[0]
    base = profile.display_name.strip().lower()
    base = "".join(c if c.isalnum() else "-" for c in base).strip("-")
    return base or f"{provider}-user"


async def _unique_actor_name(db: AsyncSession, workspace: Workspace, base: str) -> str:
    """Disambiguate an actor name within a workspace (suffix -2, -3, …)."""
    result = await db.execute(select(func.lower(Actor.name)).where(Actor.workspace_id == workspace.id))
    taken = {row[0] for row in result.all()}
    if base.lower() not in taken:
        return base
    for i in range(2, 10_000):
        candidate = f"{base}-{i}"
        if candidate.lower() not in taken:
            return candidate
    return f"{base}-{secrets.token_hex(3)}"
