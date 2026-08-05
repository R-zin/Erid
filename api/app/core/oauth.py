"""OAuth provider plumbing (Google + GitHub) for social login.

OAuth here is only an alternate way to mint the internal Ed25519 JWT the
dashboard already uses: the provider authenticates a human, we resolve that
external identity to a workspace ``Actor``, then sign a normal access token for
it via ``tokens.issue_token``. Nothing about the key/JWT authorization path
changes.

This module is deliberately thin and side-effect-free: ``build_authorize_url``
and ``verify_state`` handle the round-trip (state is signed, no server-side
session store), and the two ``fetch_*_profile`` helpers exchange a code for a
normalized identity. Those fetchers are kept small and separately mockable so
tests never touch the real providers.
"""

import secrets
from dataclasses import dataclass

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.settings import settings

# How long a signed OAuth ``state`` stays valid for the login round-trip.
STATE_MAX_AGE_SECONDS = 600


@dataclass(frozen=True)
class Provider:
    """Static endpoints for one OAuth provider (thin, httpx-exchanged)."""

    authorize_url: str
    token_url: str
    scope: str


@dataclass(frozen=True)
class OAuthProfile:
    """Provider-normalized identity used to resolve/create an actor."""

    subject: str  # stable, unique account id at the provider
    email: str | None
    display_name: str
    login: str | None = None  # GitHub handle (preferred actor name); None for Google


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email profile",
    ),
    "github": Provider(
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scope="read:user user:email",
    ),
}


def configured(provider: str) -> bool:
    """True when the provider has both a client id and secret configured."""
    if provider == "google":
        return bool(settings.oauth_google_client_id and settings.oauth_google_client_secret)
    if provider == "github":
        return bool(settings.oauth_github_client_id and settings.oauth_github_client_secret)
    return False


def _client_id(provider: str) -> str:
    return settings.oauth_google_client_id if provider == "google" else settings.oauth_github_client_id


def _client_secret(provider: str) -> str:
    return settings.oauth_google_client_secret if provider == "google" else settings.oauth_github_client_secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="oauth-state")


def callback_url(provider: str) -> str:
    """The ``redirect_uri`` registered with the provider for this login."""
    return f"{settings.oauth_redirect_base}/api/auth/{provider}/callback"


def build_authorize_url(provider: str, slug: str) -> str:
    """Provider authorization URL with a signed, short-lived ``state``.

    The state carries the target workspace slug and a nonce; it's HMAC-signed
    with ``ERID_SESSION_SECRET`` so the callback can trust it without storing
    anything server-side.
    """
    state = _serializer().dumps({"provider": provider, "slug": slug, "nonce": secrets.token_urlsafe(8)})
    params = {
        "client_id": _client_id(provider),
        "redirect_uri": callback_url(provider),
        "response_type": "code",
        "scope": PROVIDERS[provider].scope,
        "state": state,
    }
    if provider == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    return f"{PROVIDERS[provider].authorize_url}?{httpx.QueryParams(params)}"


def verify_state(state: str) -> dict:
    """Validate a signed state and return its payload.

    Raises ``SignatureExpired`` (too old) or ``BadSignature`` (tampered).
    """
    return _serializer().loads(state, max_age=STATE_MAX_AGE_SECONDS)


async def fetch_google_profile(code: str) -> OAuthProfile:
    """Exchange a Google auth code for the caller's normalized identity."""
    async with httpx.AsyncClient(timeout=15) as http:
        token_resp = await http.post(
            PROVIDERS["google"].token_url,
            data={
                "client_id": _client_id("google"),
                "client_secret": _client_secret("google"),
                "grant_type": "authorization_code",
                "redirect_uri": callback_url("google"),
                "code": code,
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        info_resp = await http.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        info_resp.raise_for_status()
        data = info_resp.json()
    return OAuthProfile(
        subject=str(data["sub"]),
        email=data.get("email"),
        display_name=data.get("name") or data.get("email") or "google-user",
        login=None,
    )


async def fetch_github_profile(code: str) -> OAuthProfile:
    """Exchange a GitHub auth code for the caller's normalized identity."""
    async with httpx.AsyncClient(timeout=15) as http:
        token_resp = await http.post(
            PROVIDERS["github"].token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": _client_id("github"),
                "client_secret": _client_secret("github"),
                "redirect_uri": callback_url("github"),
                "code": code,
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        user_resp = await http.get("https://api.github.com/user", headers=headers)
        user_resp.raise_for_status()
        data = user_resp.json()
        email = data.get("email")
        if not email:  # private email: pick the primary verified one
            emails_resp = await http.get("https://api.github.com/user/emails", headers=headers)
            if emails_resp.is_success:
                primary = next((e for e in emails_resp.json() if e.get("primary") and e.get("verified")), None)
                email = primary["email"] if primary else None
    return OAuthProfile(
        subject=str(data["id"]),
        email=email,
        display_name=data.get("name") or data.get("login") or "github-user",
        login=data.get("login"),
    )


__all__ = [
    "BadSignature",
    "OAuthProfile",
    "SignatureExpired",
    "build_authorize_url",
    "callback_url",
    "configured",
    "fetch_github_profile",
    "fetch_google_profile",
    "verify_state",
]
