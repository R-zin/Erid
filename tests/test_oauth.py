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
from app.core.tokens import issue_token

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


def _patch_profile(
    provider: str,
    monkeypatch,
    subject: str,
    *,
    email: str | None = None,
    email_verified: bool = True,
    login: str | None = None,
) -> None:
    profile = oauth.OAuthProfile(
        subject=subject,
        email=email or f"{provider}-dev@example.com",
        display_name=f"{provider.title()} Dev",
        login=login or ("dev-gh" if provider == "github" else None),
        email_verified=email_verified,
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


# ---------------------------------------------------------------------------
# Admission policy + per-workspace identity scoping
# ---------------------------------------------------------------------------


async def _callback(client, provider: str, slug: str, *, invite: str | None = None):
    data = {"provider": provider, "slug": slug, "nonce": "x"}
    if invite:
        data["invite"] = invite
    state = oauth._serializer().dumps(data)
    return await client.get(
        f"/api/auth/{provider}/callback", params={"code": "fake", "state": state}, follow_redirects=False
    )


def _token(r) -> str:
    assert r.status_code == 307, r.text
    return _callback_fragment(r.headers["location"])["token"][0]


async def _provision(client, slug: str) -> dict[str, str]:
    """Create a *secured* workspace; return owner (legacy-key) headers."""
    r = await client.post("/api/workspaces", params={"slug": slug})
    assert r.status_code == 201
    return {"X-API-Key": r.json()["api_key"]}


async def _create_actor(client, slug: str, owner: dict, name: str, role: str = "writer") -> str:
    r = await client.post(f"/api/workspaces/{slug}/actors", json={"name": name, "role": role}, headers=owner)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _invite(client, slug: str, owner: dict, actor_id: str, email: str | None = None) -> str:
    body = {"email": email} if email else {}
    r = await client.post(f"/api/workspaces/{slug}/actors/{actor_id}/oauth-invite", json=body, headers=owner)
    assert r.status_code == 201, r.text
    return r.json()["invite"]


async def _actor_names(client, slug: str, owner: dict) -> set[str]:
    r = await client.get(f"/api/workspaces/{slug}/actors", headers=owner)
    return {a["name"] for a in r.json()}


async def test_uninvited_identity_refused_on_secured_workspace(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    owner = await _provision(client, "secure-ws")

    r = await _callback(client, "github", "secure-ws")
    assert r.status_code == 403
    assert "invitation" in r.json()["detail"]
    # No actor was created as a side effect.
    assert await _actor_names(client, "secure-ws", owner) == set()


async def test_self_join_refused_when_open_workspaces_disabled(client, monkeypatch):
    _configure("google", monkeypatch)
    _patch_profile("google", monkeypatch, subject="sub-1")
    # A keyless workspace that predates closed mode.
    assert (await client.get("/api/workspaces/legacy-open/tasks")).status_code == 200
    _set_settings(monkeypatch, "allow_open_workspaces", False)

    assert (await _callback(client, "google", "legacy-open")).status_code == 403
    # Unknown slug in closed mode is still a 404, not an implicit create.
    assert (await _callback(client, "google", "never-made")).status_code == 404


async def test_identity_from_workspace_a_cannot_get_token_for_secured_b(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    token_a = _token(await _callback(client, "github", "ws-a"))  # open: self-join as dev-gh

    # B is secured and has its *own* actor that happens to share the name.
    owner_b = await _provision(client, "ws-b")
    await _create_actor(client, "ws-b", owner_b, "dev-gh", role="owner")

    # Logging in to B with the A-linked identity is refused (not B's dev-gh).
    r = await _callback(client, "github", "ws-b")
    assert r.status_code == 403
    # And A's token never authenticates in B.
    bh = {"Authorization": f"Bearer {token_a}"}
    assert (await client.get("/api/workspaces/ws-b/tasks", headers=bh)).status_code == 403


async def test_identity_gets_separate_actor_per_open_workspace(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    token_a = _token(await _callback(client, "github", "open-a"))
    token_b = _token(await _callback(client, "github", "open-b"))

    from app.core.tokens import verify_token

    sub_a, sub_b = verify_token(token_a)["sub"], verify_token(token_b)["sub"]
    assert sub_a != sub_b  # distinct actors, one per workspace
    # A second login to A resolves to the same A actor.
    assert verify_token(_token(await _callback(client, "github", "open-a")))["sub"] == sub_a


async def test_invited_identity_joins_secured_workspace(client, monkeypatch):
    _configure("google", monkeypatch)
    _patch_profile("google", monkeypatch, subject="alice-sub")
    owner = await _provision(client, "team")
    actor_id = await _create_actor(client, "team", owner, "alice", role="reader")
    invite = await _invite(client, "team", owner, actor_id)

    r = await _callback(client, "google", "team", invite=invite)
    frag = _callback_fragment(r.headers["location"])
    assert frag["name"] == ["alice"]
    bh = {"Authorization": f"Bearer {frag['token'][0]}"}
    assert (await client.get("/api/workspaces/team/tasks", headers=bh)).status_code == 200
    # The invited actor's role (reader) applies, not a default writer.
    assert (await client.post("/api/workspaces/team/tasks", json={"title": "x"}, headers=bh)).status_code == 403

    # Subsequent logins need no invite: the identity is now linked in `team`.
    assert _callback_fragment(_token_loc(await _callback(client, "google", "team")))["name"] == ["alice"]
    assert await _actor_names(client, "team", owner) == {"alice"}


def _token_loc(r) -> str:
    assert r.status_code == 307, r.text
    return r.headers["location"]


async def test_invite_is_single_use(client, monkeypatch):
    _configure("google", monkeypatch)
    owner = await _provision(client, "team")
    actor_id = await _create_actor(client, "team", owner, "alice")
    invite = await _invite(client, "team", owner, actor_id)

    _patch_profile("google", monkeypatch, subject="alice-sub")
    assert (await _callback(client, "google", "team", invite=invite)).status_code == 307
    # Someone else replaying the same link is refused.
    _patch_profile("google", monkeypatch, subject="mallory-sub", email="mallory@example.com")
    assert (await _callback(client, "google", "team", invite=invite)).status_code == 403
    # And the owner can't mint a fresh invite for an already-linked actor.
    r = await client.post(f"/api/workspaces/team/actors/{actor_id}/oauth-invite", json={}, headers=owner)
    assert r.status_code == 409


async def test_invite_for_other_workspace_rejected(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    owner_a = await _provision(client, "inv-a")
    await _provision(client, "inv-b")
    invite_a = await _invite(client, "inv-a", owner_a, await _create_actor(client, "inv-a", owner_a, "bob"))

    assert (await _callback(client, "github", "inv-b", invite=invite_a)).status_code == 403
    # The login endpoint rejects it up front too.
    r = await client.get("/api/auth/github/login", params={"slug": "inv-b", "invite": invite_a}, follow_redirects=False)
    assert r.status_code == 403


async def test_tampered_invite_rejected(client, monkeypatch):
    _configure("github", monkeypatch)
    _patch_profile("github", monkeypatch, subject="42")
    await _provision(client, "team")
    assert (await _callback(client, "github", "team", invite="not-an-invite")).status_code == 400
    r = await client.get("/api/auth/github/login", params={"slug": "team", "invite": "nope"}, follow_redirects=False)
    assert r.status_code == 400
    # A signed OAuth *state* is not accepted as an invite (distinct salt).
    forged = oauth._serializer().dumps({"slug": "team", "actor_id": "00000000-0000-0000-0000-000000000000"})
    assert (await _callback(client, "github", "team", invite=forged)).status_code == 400


async def test_email_pinned_invite(client, monkeypatch):
    _configure("github", monkeypatch)
    owner = await _provision(client, "team")
    actor_id = await _create_actor(client, "team", owner, "carol")
    invite = await _invite(client, "team", owner, actor_id, email="Carol@Example.com")

    _patch_profile("github", monkeypatch, subject="1", email="someone@example.com")
    assert (await _callback(client, "github", "team", invite=invite)).status_code == 403
    # Matching but unverified email is not good enough.
    _patch_profile("github", monkeypatch, subject="2", email="carol@example.com", email_verified=False)
    assert (await _callback(client, "github", "team", invite=invite)).status_code == 403
    _patch_profile("github", monkeypatch, subject="3", email="carol@example.com", login="carol-gh")
    r = await _callback(client, "github", "team", invite=invite)
    assert _callback_fragment(_token_loc(r))["name"] == ["carol"]


async def test_invite_endpoint_requires_admin(client, monkeypatch):
    _configure("github", monkeypatch)
    owner = await _provision(client, "team")
    actor_id = await _create_actor(client, "team", owner, "dave")
    url = f"/api/workspaces/team/actors/{actor_id}/oauth-invite"
    assert (await client.post(url, json={})).status_code == 401
    writer = await client.post("/api/workspaces/team/actors", json={"name": "w", "role": "writer"}, headers=owner)
    wh = {"X-API-Key": writer.json()["api_key"]}
    assert (await client.post(url, json={}, headers=wh)).status_code == 403


async def test_removed_actor_cannot_log_back_in_to_secured_workspace(client, monkeypatch):
    _configure("google", monkeypatch)
    _patch_profile("google", monkeypatch, subject="alice-sub")
    owner = await _provision(client, "team")
    actor_id = await _create_actor(client, "team", owner, "alice")
    assert (
        await _callback(client, "google", "team", invite=await _invite(client, "team", owner, actor_id))
    ).status_code == 307

    assert (await client.delete(f"/api/workspaces/team/actors/{actor_id}", headers=owner)).status_code == 204
    # Revocation sticks: no silent re-admission as a fresh actor.
    assert (await _callback(client, "google", "team")).status_code == 403
    assert await _actor_names(client, "team", owner) == set()


async def test_jwt_sub_is_actor_id_not_name(client, monkeypatch):
    """A token resolves by actor id, so names can't alias another actor."""
    owner = await _provision(client, "team")
    old_id = await _create_actor(client, "team", owner, "eve", role="owner")
    old_token = issue_token(workspace_slug="team", subject=old_id, role="owner", name="eve")
    assert (
        await client.get("/api/workspaces/team/actors", headers={"Authorization": f"Bearer {old_token}"})
    ).status_code == 200

    # Delete eve and create a new, different actor that reuses the name.
    await client.delete(f"/api/workspaces/team/actors/{old_id}", headers=owner)
    await _create_actor(client, "team", owner, "eve", role="reader")
    bh = {"Authorization": f"Bearer {old_token}"}
    assert (await client.get("/api/workspaces/team/tasks", headers=bh)).status_code == 403

    # A name-as-subject token (the old format) authenticates as no one.
    by_name = issue_token(workspace_slug="team", subject="eve", role="reader")
    assert (
        await client.get("/api/workspaces/team/tasks", headers={"Authorization": f"Bearer {by_name}"})
    ).status_code == 403
    # Nor can a name-subject token claim owner unless it is the legacy slug form.
    fake_owner = issue_token(workspace_slug="team", subject="eve", role="owner")
    assert (
        await client.get("/api/workspaces/team/tasks", headers={"Authorization": f"Bearer {fake_owner}"})
    ).status_code == 403
