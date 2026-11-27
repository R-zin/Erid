"""Secret scanning on writes.

Fake credentials are assembled at runtime so this file never contains a
string that a repository secret scanner (or GitHub push protection) would
flag.
"""

import pytest
from app.core import secret_scan
from app.core.settings import settings
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

A36 = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # 36 alphanumerics

FAKES = {
    "aws_access_key_id": "AK" + "IA" + "Q3EGUJ5NJ7WLXKZP",
    "github_token": "gh" + "p_" + A36,
    "github_fine_grained_token": "github" + "_pat_" + "11ABCDEFG0" + "x" * 30,
    "anthropic_api_key": "sk-" + "ant-api03-" + "z" * 40,
    "openai_api_key": "sk-" + "proj-" + "abcdEFGH1234" + "T3Blbk" + "FJ" + "ijklMNOP5678",
    "slack_token": "xo" + "xb-" + "1234567890-abcdefghij",
    "stripe_live_key": "sk" + "_live_" + "a" * 24,
    "google_api_key": "AI" + "za" + "S" * 35,
    "npm_token": "np" + "m_" + A36,
    "jwt": "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "ey" + "JzdWIiOiIxMjM0In0" + "." + "abcdefghijklmnop",
}
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END " + "RSA PRIVATE KEY-----"


@pytest.fixture(autouse=True)
def _restore_mode():
    saved = settings.secret_scanning
    yield
    object.__setattr__(settings, "secret_scanning", saved)


@pytest.mark.parametrize(("rule", "secret"), sorted(FAKES.items()))
def test_each_rule_redacts_its_format(rule, secret):
    text, hits = secret_scan.redact(f"ran deploy with {secret} yesterday")
    assert secret not in text
    assert f"[REDACTED:{rule}]" in text
    assert rule in hits


def test_private_key_block():
    text, hits = secret_scan.redact(f"key:\n{PRIVATE_KEY}\nthanks")
    assert "MIIEow" not in text and hits == ["private_key"]
    assert text.endswith("thanks")


def test_url_password_keeps_the_rest_of_the_url():
    text, hits = secret_scan.redact("DATABASE_URL=postgresql://erid:" + "hunter22" + "@db.internal:5432/erid")
    assert "hunter22" not in text
    assert "postgresql://erid:[REDACTED:url_password]@db.internal:5432/erid" in text
    assert hits == ["url_password"]


def test_bearer_header():
    text, _ = secret_scan.redact("curl -H 'Authorization: Bearer " + "q" * 32 + "' https://x")
    assert "q" * 32 not in text and "Authorization: Bearer [REDACTED:bearer_token]" in text


@pytest.mark.parametrize(
    "benign",
    [
        "Use sk-learn for the classifier and ghp as an abbreviation",
        "see https://example.com/docs and git@github.com:org/repo.git",
        "Authorization: Bearer <token>",
        "AKIA is the prefix AWS uses for access keys",
        "eyJ is how base64 JSON starts",
        "the -----BEGIN CERTIFICATE----- block is public",
    ],
)
def test_ordinary_text_is_untouched(benign):
    assert secret_scan.redact(benign) == (benign, [])


async def test_handoff_secrets_are_redacted_and_audited(client: AsyncClient, authed):
    slug, headers = authed
    token = FAKES["github_token"]
    r = await client.post(
        f"/api/workspaces/{slug}/handoffs",
        json={"summary": "deployed", "commands_run": f"export GITHUB_TOKEN={token} && make deploy"},
        headers=headers,
    )
    assert r.status_code == 201
    stored = r.json()["commands_run"]
    assert token not in stored and "[REDACTED:github_token]" in stored
    # Also redacted at rest, not just in the response.
    listed = (await client.get(f"/api/workspaces/{slug}/handoffs", headers=headers)).json()
    assert token not in str(listed)
    trail = await client.get(f"/api/workspaces/{slug}/audit", params={"action": "secret.redacted"}, headers=headers)
    assert trail.json()[0]["detail"] == {"findings": ["commands_run:github_token"]}
    assert token not in trail.text


async def test_every_write_path_is_scanned(client: AsyncClient, authed):
    slug, headers = authed
    key = FAKES["aws_access_key_id"]
    task = (await client.post(f"/api/workspaces/{slug}/tasks", json={"title": f"rotate {key}"}, headers=headers)).json()
    assert key not in task["title"]
    upd = await client.put(
        f"/api/workspaces/{slug}/tasks/{task['id']}", json={"title": f"again {key}"}, headers=headers
    )
    assert key not in upd.json()["title"]
    dec = await client.post(
        f"/api/workspaces/{slug}/decisions",
        json={"title": "t", "reason": f"because {key}", "related_files": key},
        headers=headers,
    )
    assert key not in dec.text
    pres = await client.post(
        f"/api/workspaces/{slug}/presence", json={"actor_name": "a", "current_task": f"using {key}"}, headers=headers
    )
    assert key not in pres.text
    claim = await client.post(
        f"/api/workspaces/{slug}/claims", json={"paths": ["a.py"], "reason": f"key {key}"}, headers=headers
    )
    assert key not in claim.text


async def test_reject_mode_refuses_and_stores_nothing(client: AsyncClient, authed):
    slug, headers = authed
    object.__setattr__(settings, "secret_scanning", "reject")
    r = await client.post(
        f"/api/workspaces/{slug}/decisions",
        json={"title": "creds", "reason": "use " + FAKES["stripe_live_key"]},
        headers=headers,
    )
    assert r.status_code == 422
    assert "reason:stripe_live_key" in r.json()["detail"]
    assert FAKES["stripe_live_key"] not in r.text
    assert (await client.get(f"/api/workspaces/{slug}/decisions", headers=headers)).json() == []


async def test_off_mode_stores_verbatim(client: AsyncClient, authed):
    slug, headers = authed
    object.__setattr__(settings, "secret_scanning", "off")
    r = await client.post(f"/api/workspaces/{slug}/tasks", json={"title": "x " + FAKES["npm_token"]}, headers=headers)
    assert FAKES["npm_token"] in r.json()["title"]


async def test_redaction_never_overflows_a_column(client: AsyncClient, authed):
    # A short password becomes a longer marker; the title must still fit its
    # 512-character column (Postgres would otherwise fail the insert).
    slug, headers = authed
    title = "x" * 480 + " redis://u:" + "pw1" + "@h"
    assert len(title) <= 512
    r = await client.post(f"/api/workspaces/{slug}/tasks", json={"title": title}, headers=headers)
    assert r.status_code == 201, r.text
    assert len(r.json()["title"]) <= 512 and "pw1@" not in r.json()["title"]
