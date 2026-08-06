"""Social login (OAuth) routes.

These are *open* endpoints: they authenticate a human against Google/GitHub and
hand back the same internal Ed25519 JWT the dashboard already uses. ``login``
redirects the browser to the provider; ``callback`` validates the signed state,
fetches the caller's identity, resolves it to a workspace ``Actor`` (creating a
``writer`` actor on first login), mints a token, and redirects to the dashboard
with the token in the URL fragment.
"""

import secrets
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import oauth
from app.core.settings import settings
from app.core.tokens import issue_token
from app.db.session import get_db
from app.models.models import Actor, ActorRole, OAuthIdentity, Workspace
from app.services.workspace_service import get_or_create_workspace

router = APIRouter()

ProviderName = Literal["google", "github"]


@router.get("/auth/{provider}/login", name="oauth_login")
async def oauth_login(provider: str, slug: str = Query(min_length=1, max_length=128)) -> RedirectResponse:
    """Begin the OAuth flow: redirect the browser to the provider.

    ``slug`` names the workspace the resulting actor should join (created as an
    open workspace on first use). Requires the provider to be configured
    (``ERID_OAUTH_<PROVIDER>_*``) and ``ERID_SESSION_SECRET`` to be set.
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
    url = oauth.build_authorize_url(provider, slug)
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

    try:
        profile = await (oauth.fetch_google_profile(code) if provider == "google" else oauth.fetch_github_profile(code))
    except Exception as exc:  # provider/token exchange failure
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"failed to fetch {provider} profile"
        ) from exc

    actor = await _resolve_or_create_oauth_actor(db, provider, profile, slug)
    token = issue_token(workspace_slug=slug, actor_name=actor.name, role=actor.role.value)

    # quote_via=quote (not quote_plus) keeps the JWT's [A-Za-z0-9._-] chars
    # literal in the fragment, so clients/tests can split it on "&" simply.
    fragment = urlencode({"token": token, "slug": slug, "name": actor.name}, quote_via=quote)
    redirect = f"{settings.oauth_web_base}/#/oauth/callback?{fragment}"
    return RedirectResponse(redirect, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


async def _resolve_or_create_oauth_actor(
    db: AsyncSession, provider: ProviderName, profile: oauth.OAuthProfile, slug: str
) -> Actor:
    """Map an external OAuth identity to a workspace ``Actor`` (create on first login).

    A given ``(provider, provider_subject)`` always resolves to the same actor.
    The actor is created role ``writer`` with no API key (``key_hash`` NULL) —
    OAuth-issued JWTs authenticate purely via ``sub`` → actor-name resolution,
    which the existing token-verification path already supports.
    """
    workspace: Workspace = await get_or_create_workspace(db, slug, mint_key=False)

    result = await db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_subject == profile.subject,
        )
    )
    identity = result.scalars().first()
    if identity is not None:
        actor = await db.get(Actor, identity.actor_id)
        if actor is not None and actor.active:
            return actor
        # Actor revoked/deleted since; fall through to re-map.

    name = await _unique_actor_name(db, workspace, _candidate_name(provider, profile))
    actor = Actor(workspace_id=workspace.id, name=name, role=ActorRole.writer, key_hash=None, active=True)
    db.add(actor)
    await db.flush()  # materialize actor.id for the FK
    db.add(
        OAuthIdentity(
            provider=provider,
            provider_subject=profile.subject,
            email=profile.email,
            display_name=profile.display_name,
            actor_id=actor.id,
        )
    )
    await db.commit()
    await db.refresh(actor)
    return actor


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
