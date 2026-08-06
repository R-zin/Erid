"""Integration tests for OAuth social login (Google + GitHub).

OAuth is only an alternate way to mint the internal JWT. These tests never hit
a real provider: the ``fetch_*_profile`` helpers are monkeypatched and the
provider client id/secret + session secret are configured per test via
monkeypatched settings. Runs against SQLite via the shared conftest fixtures.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from app.api.routes import auth as auth_routes
from app.core import oauth
from app.core.settings import settings

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _restore_settings():
    """Snapshot and restore the frozen Settings singleton around each test.

    ``Settings`` is a frozen dataclass, so ``monkeypatch.setattr`` on the instance
    raises ``FrozenInstanceError`` — instead we override attributes directly via
    ``object.__setattr__`` (consumers read the same singleton at call time, so it
    takes effect) and restore the originals afterwards.
    """
    originals = {f: getattr(settings, f) for f in settings.__dataclass_fields__}
    yield
    for name, value in originals.items():
        object.__setattr__(settings, name, value)


def _set_settings(_monkeypatch, name: str, value) -> None:  # noqa: ARG001 (kept for call-site clarity)
    object.__setattr__(settings, name, value)


def _configure(provider: str, monkeypatch, *, secret: str = "test-secret") -> None:
    """Enable OAuth + a provider by patching the frozen Settings in place."""
    _set_settings(monkeypatch, "session_secret", secret)
    field = f"oauth_{provider}_client_"
    _set_settings(monkeypatch, f"{field}id", f"{provider}-id")
    _set_settings(monkeypatch, f"{field}secret", f"{provider}-secret")


def _patch_profile(provider: str, monkeypatch, subject: str) -> None:
    profile = oauth.OAuthProfile(
        subject=subject,
        email=f"{provider}-dev@example.com",
        display_name=f"{provider.title()} Dev",
        login="dev-gh" if provider == "github" else None,
    )
    fetch = f"fetch_{provider}_profile"

    async def fake(_code: str, _profile=profile):
        return _profile

    # Patch at BOTH the definition site and the route's import site.
    monkeypatch.setattr(oauth, fetch, fake)
    monkeypatch.setattr(auth_routes.oauth, fetch, fake)


def _callback_fragment(location: str) -> dict[str, list[str]]:
    """Parse the SPA callback location's ``#/oauth/callback?...`` params.

    The redirect target is a hash route, so the whole ``/oauth/callback?k=v…``
    lives in the URL *fragment* (after ``#``). Splitting on the literal
    ``#/oauth/callback?`` prefix and parsing the remainder yields the clean map.
    """
    fragment = urlparse(location).fragment
    _, _, query = fragment.partition("?")
    return {k: v for k, v in parse_qs(query).items() if k}


async def test_login_redirects_to_provider(client, monkeypatch):
    _configure("google", monkeypatch)
    r = await client.get("/api/auth/google/login", params={"slug": "acme"}, follow_redirects=False)
    assert r.status_code == 307
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    q = parse_qs(urlparse(loc).query)
    assert q["client_id"] == ["google-id"]
    assert q["redirect_uri"] == [oauth.callback_url("google")]
    assert q["state"]


async def test_callback_mints_working_jwt_and_creates_actor(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    state = oauth._serializer().dumps({"provider": "github", "slug": "acme", "nonce": "x"})

    r = await client.get(
        "/api/auth/github/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 307
    frag = _callback_fragment(r.headers["location"])
    assert frag["slug"] == ["acme"]
    assert frag["name"] == ["dev-gh"]  # GitHub login handle is the actor name
    token = frag["token"][0]

    # The minted JWT authenticates against the joined workspace like any token.
    bh = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/workspaces/acme/tasks", headers=bh)).status_code == 200
    assert (
        await client.post("/api/workspaces/acme/decisions", json={"title": "via oauth"}, headers=bh)
    ).status_code == 201


async def test_oauth_identity_reused_on_second_login(client, monkeypatch):
    _configure("google", monkeypatch)
    _patch_profile("google", monkeypatch, subject="sub-1")
    state = oauth._serializer().dumps({"provider": "google", "slug": "acme", "nonce": "x"})
    params = {"code": "fake", "state": state}

    r1 = await client.get("/api/auth/google/callback", params=params, follow_redirects=False)
    r2 = await client.get("/api/auth/google/callback", params=params, follow_redirects=False)
    name1 = parse_qs(urlparse(r1.headers["location"]).fragment)["name"][0]
    name2 = parse_qs(urlparse(r2.headers["location"]).fragment)["name"][0]
    # Same external subject → same actor, no duplicate created.
    assert name1 == name2


async def test_callback_rejects_bad_state(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    r = await client.get(
        "/api/auth/github/callback",
        params={"code": "fake", "state": "tampered"},
        follow_redirects=False,
    )
    assert r.status_code == 400


async def test_callback_rejects_provider_mismatched_state(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    # State signed for google but presented to the github callback.
    state = oauth._serializer().dumps({"provider": "google", "slug": "acme", "nonce": "x"})
    r = await client.get(
        "/api/auth/github/callback",
        params={"code": "fake", "state": state},
        follow_redirects=False,
    )
    assert r.status_code == 400


async def test_unknown_provider_404(client, monkeypatch):
    _set_settings(monkeypatch, "session_secret", "test-secret")
    assert (await client.get("/api/auth/facebook/login", params={"slug": "x"})).status_code == 404
    assert (await client.get("/api/auth/facebook/callback", params={"code": "c", "state": "s"})).status_code == 404


async def test_unconfigured_provider_503(client, monkeypatch):
    # Session secret present but no client id/secret for the provider.
    _set_settings(monkeypatch, "session_secret", "test-secret")
    _set_settings(monkeypatch, "oauth_google_client_id", "")
    _set_settings(monkeypatch, "oauth_google_client_secret", "")
    assert (await client.get("/api/auth/google/login", params={"slug": "x"})).status_code == 503


async def test_missing_session_secret_503(client, monkeypatch):
    _configure("google", monkeypatch, secret="")
    assert (await client.get("/api/auth/google/login", params={"slug": "x"})).status_code == 503


async def test_token_scoped_to_its_workspace(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    state = oauth._serializer().dumps({"provider": "github", "slug": "acme", "nonce": "x"})
    r = await client.get("/api/auth/github/callback", params={"code": "fake", "state": state}, follow_redirects=False)
    token = _callback_fragment(r.headers["location"])["token"][0]
    bh = {"Authorization": f"Bearer {token}"}

    other = await client.post("/api/workspaces", params={"slug": "other-ws"})
    assert other.status_code == 201
    # OAuth token for `acme` must NOT authorize the secured `other-ws`.
    assert (await client.get("/api/workspaces/other-ws/tasks", headers=bh)).status_code == 403


async def test_google_callback_uses_email_localpart(client, monkeypatch):
    _configure("google", monkeypatch)
    _patch_profile("google", monkeypatch, subject="sub-9")
    state = oauth._serializer().dumps({"provider": "google", "slug": "acme", "nonce": "x"})
    r = await client.get("/api/auth/google/callback", params={"code": "fake", "state": state}, follow_redirects=False)
    name = _callback_fragment(r.headers["location"])["name"][0]
    assert name == "google-dev"  # email local-part (google-dev@example.com)
