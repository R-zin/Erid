"""File claims: advisory leases on paths."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from app.models.models import FileClaim
from app.services.claims import normalize_path, overlaps
from app.services.errors import Unprocessable
from conftest import IS_POSTGRES
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_mcp_http import _call, _payload, live_server  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Path rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "normal"),
    [("./src//a.py", "src/a.py"), ("src\\win\\b.py", "src/win/b.py"), ("src/auth/", "src/auth/**"), ("x", "x")],
)
def test_normalize(raw, normal):
    assert normalize_path(raw) == normal


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../outside", "a/../../b", "C:/win", "a\x00b", "x" * 600])
def test_normalize_rejects(bad):
    with pytest.raises(Unprocessable):
        normalize_path(bad)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("src/a.py", "src/a.py", True),
        ("src/a.py", "src/b.py", False),
        ("src/auth/**", "src/auth/login.py", True),
        ("src/auth", "src/auth/login.py", True),  # a plain path may be a directory
        ("src/authz.py", "src/auth", False),
        ("src/**/*.py", "src/deep/x.py", True),
        ("src/*.py", "src/x.js", False),
        ("src/*.py", "src/*.js", False),
        ("src/**", "src/*.py", True),
        ("docs/**", "src/**", False),
        ("src/auth", "src/auth/**/*.py", True),
    ],
)
def test_overlaps(a, b, expected):
    assert overlaps(a, b) is expected
    assert overlaps(b, a) is expected


# ---------------------------------------------------------------------------
# API behaviour
# ---------------------------------------------------------------------------


async def _actor(client, slug, admin, name, role="writer") -> dict[str, str]:
    r = await client.post(f"/api/workspaces/{slug}/actors", json={"name": name, "role": role}, headers=admin)
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["api_key"]}


@pytest.fixture
async def team(client: AsyncClient, authed):
    slug, admin = authed
    return slug, admin, await _actor(client, slug, admin, "alice"), await _actor(client, slug, admin, "bob")


async def _claim(client, slug, headers, *paths, **extra):
    r = await client.post(f"/api/workspaces/{slug}/claims", json={"paths": list(paths), **extra}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_conflicting_claims_are_refused_with_the_holder(client: AsyncClient, team):
    slug, _, alice, bob = team
    first = await _claim(client, slug, alice, "src/auth/", reason="refactoring login")
    assert first["ok"] and first["granted"][0]["holder"] == "alice"

    second = await _claim(client, slug, bob, "src/auth/login.py", "docs/readme.md")
    assert second["ok"] is False
    assert [c["path"] for c in second["granted"]] == ["docs/readme.md"]
    conflict = second["conflicts"][0]
    assert conflict["path"] == "src/auth/login.py"
    assert conflict["held_by"][0]["holder"] == "alice"
    assert conflict["held_by"][0]["reason"] == "refactoring login"


async def test_shared_claims_coexist_but_block_exclusive(client: AsyncClient, team):
    slug, admin, alice, bob = team
    assert (await _claim(client, slug, alice, "lib/util.py", exclusive=False))["ok"]
    assert (await _claim(client, slug, bob, "lib/util.py", exclusive=False))["ok"]
    carol = await _actor(client, slug, admin, "carol")
    assert (await _claim(client, slug, carol, "lib/", exclusive=True))["ok"] is False


async def test_reclaiming_renews_instead_of_duplicating(client: AsyncClient, team):
    slug, _, alice, _ = team
    first = (await _claim(client, slug, alice, "a.py", ttl_seconds=60))["granted"][0]
    again = (await _claim(client, slug, alice, "a.py", ttl_seconds=7200))["granted"][0]
    assert again["id"] == first["id"]
    assert again["expires_at"] > first["expires_at"]
    assert len((await client.get(f"/api/workspaces/{slug}/claims", headers=alice)).json()) == 1


async def test_expired_claims_stop_blocking(client: AsyncClient, team, db_engine):
    slug, _, alice, bob = team
    await _claim(client, slug, alice, "a.py")
    sessions = async_sessionmaker(db_engine, class_=AsyncSession)
    async with sessions() as db:
        await db.execute(update(FileClaim).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await db.commit()
    assert (await _claim(client, slug, bob, "a.py"))["ok"]


async def test_release_and_permissions(client: AsyncClient, team):
    slug, admin, alice, bob = team
    claim = (await _claim(client, slug, alice, "a.py", "b.py"))["granted"]
    # Bob can't release Alice's claim; an admin can.
    r = await client.delete(f"/api/workspaces/{slug}/claims/{claim[0]['id']}", headers=bob)
    assert r.status_code == 403
    r = await client.delete(f"/api/workspaces/{slug}/claims/{claim[0]['id']}", headers=admin)
    assert r.status_code == 200 and r.json()["released"] == [claim[0]["id"]]
    # Alice releases the rest of hers.
    r = await client.post(f"/api/workspaces/{slug}/claims/release", json={}, headers=alice)
    assert r.json()["released"] == [claim[1]["id"]]
    assert (await _claim(client, slug, bob, "a.py", "b.py"))["ok"]


async def test_check_reports_without_claiming(client: AsyncClient, team):
    slug, _, alice, bob = team
    await _claim(client, slug, alice, "src/**/*.py")
    r = await client.post(
        f"/api/workspaces/{slug}/claims/check", json={"paths": ["src/x/y.py", "README.md"]}, headers=bob
    )
    checks = {c["path"]: c for c in r.json()}
    assert checks["src/x/y.py"]["claimed_by_others"] is True
    assert checks["README.md"]["claimed_by_others"] is False
    # Alice's own claim doesn't count as someone else's.
    mine = await client.post(f"/api/workspaces/{slug}/claims/check", json={"paths": ["src/x/y.py"]}, headers=alice)
    assert mine.json()[0]["claimed_by_others"] is False
    assert len((await client.get(f"/api/workspaces/{slug}/claims", headers=bob)).json()) == 1


async def test_actor_cannot_claim_as_someone_else(client: AsyncClient, team):
    slug, _, _, bob = team
    granted = (await _claim(client, slug, bob, "x.py", holder="alice"))["granted"][0]
    assert granted["holder"] == "bob"


async def test_readers_cannot_claim(client: AsyncClient, team):
    slug, admin, _, _ = team
    reader = await _actor(client, slug, admin, "ro", role="reader")
    r = await client.post(f"/api/workspaces/{slug}/claims", json={"paths": ["a.py"]}, headers=reader)
    assert r.status_code == 403


async def test_bad_paths_are_422(client: AsyncClient, team):
    slug, _, alice, _ = team
    r = await client.post(f"/api/workspaces/{slug}/claims", json={"paths": ["../../etc/passwd"]}, headers=alice)
    assert r.status_code == 422
    r = await client.post(f"/api/workspaces/{slug}/claims", json={"paths": ["a"] * 51}, headers=alice)
    assert r.status_code == 422


async def test_claims_are_tenant_isolated_and_counted(client: AsyncClient, team):
    slug, admin, alice, _ = team
    await _claim(client, slug, alice, "a.py", "b.py")
    other = (await client.post("/api/workspaces", params={"slug": "other-team"})).json()["api_key"]
    assert (await client.get("/api/workspaces/other-team/claims", headers={"X-API-Key": other})).json() == []
    summary = (await client.get(f"/api/workspaces/{slug}/summary", headers=admin)).json()
    assert summary["active_claim_count"] == 2


@pytest.mark.skipif(not IS_POSTGRES, reason="needs real concurrent transactions (Postgres)")
async def test_concurrent_exclusive_claims_have_one_winner(client: AsyncClient, authed):
    slug, admin = authed
    agents = [await _actor(client, slug, admin, f"agent-{i}") for i in range(12)]
    results = await asyncio.gather(
        *(client.post(f"/api/workspaces/{slug}/claims", json={"paths": ["hot.py"]}, headers=h) for h in agents)
    )
    winners = [r.json() for r in results if r.json()["ok"]]
    assert len(winners) == 1, [r.json() for r in results]


async def test_claims_over_mcp(live_server, authed, client: AsyncClient):  # noqa: F811
    slug, admin = authed
    alice = await _actor(client, slug, admin, "alice")
    bob = await _actor(client, slug, admin, "bob")
    h_alice = {**alice, "X-Erid-Workspace": slug}
    h_bob = {**bob, "X-Erid-Workspace": slug}
    granted = _payload(await _call(live_server, h_alice, "claim_files", {"paths": ["api/"], "reason": "mcp"}))
    assert granted["ok"]
    refused = _payload(await _call(live_server, h_bob, "claim_files", {"paths": ["api/main.py"]}))
    assert refused["conflicts"][0]["held_by"][0]["holder"] == "alice"
    checked = _payload(await _call(live_server, h_bob, "check_files", {"paths": ["api/x.py"]}))
    assert checked[0]["claimed_by_others"] is True
    released = _payload(await _call(live_server, h_alice, "release_files", {}))
    assert len(released["released"]) == 1
    assert _payload(await _call(live_server, h_bob, "list_claims", {})) == []
