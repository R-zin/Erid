"""Security controls: rate limits, lockout, body limit, headers, Origin checks,
log redaction, the production config gate, and the audit trail."""

import logging

import pytest
from app.core import hardening, ratelimit
from app.core.settings import Settings, settings
from app.main import app
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio

_TUNABLE = (
    "rate_limit_auth",
    "rate_limit_auth_failures",
    "rate_limit_api",
    "max_body_bytes",
    "cors_origins",
    "allow_open_workspaces",
    "admin_token",
    "jwt_private_key",
    "jwt_public_key",
    "env",
)


@pytest.fixture(autouse=True)
def _restore_settings():
    saved = {name: getattr(settings, name) for name in _TUNABLE}
    yield
    for name, value in saved.items():
        object.__setattr__(settings, name, value)


def _set(**kw) -> None:
    for k, v in kw.items():
        object.__setattr__(settings, k, v)


def _client_from(ip: str) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=(ip, 4321)), base_url="http://test")


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------


async def test_auth_endpoints_are_rate_limited_per_ip(client: AsyncClient, authed):
    slug, headers = authed
    # The fixture's provisioning call already spent 1 of this address's budget.
    _set(rate_limit_auth="4/minute")
    body = {"api_key": headers["X-API-Key"]}
    for _ in range(3):
        assert (await client.post(f"/api/workspaces/{slug}/token", json=body)).status_code == 200
    r = await client.post(f"/api/workspaces/{slug}/token", json=body)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    # Provisioning shares the auth budget.
    assert (await client.post("/api/workspaces", params={"slug": "another"})).status_code == 429
    # Another client address has its own budget.
    async with _client_from("10.9.9.9") as other:
        assert (await other.post(f"/api/workspaces/{slug}/token", json=body)).status_code == 200


async def test_repeated_bad_credentials_lock_the_client_out(client: AsyncClient, authed):
    slug, headers = authed
    _set(rate_limit_auth_failures="3/minute")
    bad = {"X-API-Key": "not-the-key"}
    for _ in range(3):
        assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=bad)).status_code == 403
    # Locked out: even the right key is refused for the rest of the window,
    # so guessing can't continue.
    locked = await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)
    assert locked.status_code == 429
    assert "retry-after" in locked.headers
    # Other clients are unaffected.
    async with _client_from("10.1.2.3") as other:
        assert (await other.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 200


async def test_failed_token_logins_count_towards_lockout(client: AsyncClient, authed):
    slug, headers = authed
    _set(rate_limit_auth_failures="2/minute")
    for _ in range(2):
        r = await client.post(f"/api/workspaces/{slug}/token", json={"api_key": "wrong"})
        assert r.status_code == 403
    r = await client.post(f"/api/workspaces/{slug}/token", json={"api_key": headers["X-API-Key"]})
    assert r.status_code == 429


async def test_api_limit_is_per_credential(client: AsyncClient, authed):
    slug, headers = authed
    _set(rate_limit_api="5/minute")
    for _ in range(5):
        assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 200
    assert (await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)).status_code == 429
    # A different credential (an actor key) has its own budget.
    _set(rate_limit_api="1000/minute")
    actor = (
        await client.post(f"/api/workspaces/{slug}/actors", json={"name": "bot", "role": "reader"}, headers=headers)
    ).json()
    _set(rate_limit_api="5/minute")
    r = await client.get(f"/api/workspaces/{slug}/tasks", headers={"X-API-Key": actor["api_key"]})
    assert r.status_code == 200


def test_limit_parsing():
    assert ratelimit.Limit.parse("10/minute") == ratelimit.Limit(10, 60)
    assert ratelimit.Limit.parse("2/s") == ratelimit.Limit(2, 1)
    assert not ratelimit.Limit.parse("0/hour").enabled
    with pytest.raises(ValueError):
        ratelimit.Limit.parse("10/fortnight")


# ---------------------------------------------------------------------------
# Body size, headers, Origin
# ---------------------------------------------------------------------------


async def test_oversized_body_is_413(client: AsyncClient, authed):
    slug, headers = authed
    _set(max_body_bytes=1024)
    big = {"title": "t", "reason": "x" * 5000}
    r = await client.post(f"/api/workspaces/{slug}/decisions", json=big, headers=headers)
    assert r.status_code == 413


async def test_oversized_chunked_body_is_413(client: AsyncClient, authed):
    slug, headers = authed
    _set(max_body_bytes=1024)

    async def chunks():
        for _ in range(10):
            yield b'{"title": "' + b"x" * 300 + b'"}'

    r = await client.post(
        f"/api/workspaces/{slug}/decisions",
        content=chunks(),
        headers={**headers, "content-type": "application/json"},
    )
    assert r.status_code == 413


async def test_api_responses_carry_security_headers(client: AsyncClient, authed):
    slug, headers = authed
    r = await client.get(f"/api/workspaces/{slug}/tasks", headers=headers)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in r.headers  # plain http in tests


async def test_hsts_over_https(authed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as tls:
        r = await tls.get("/health")
    assert r.headers["strict-transport-security"].startswith("max-age=")


async def test_mcp_refuses_foreign_browser_origins(client: AsyncClient):
    _set(cors_origins=["https://erid.example.com"])
    evil = await client.post("/mcp", json={}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    # Allowed origin and no-Origin (CLI/editor clients) get past the guard.
    ok = await client.post("/mcp", json={}, headers={"Origin": "https://erid.example.com"})
    assert ok.status_code != 403
    assert (await client.post("/mcp", json={})).status_code != 403


async def test_websocket_refuses_foreign_origin():
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    _set(cors_origins=["https://erid.example.com"])
    with (
        TestClient(app) as tc,
        pytest.raises(WebSocketDisconnect) as exc,
        tc.websocket_connect("/api/workspaces/ws-origin/ws", headers={"Origin": "https://evil.example"}),
    ):
        pass
    assert exc.value.code == 1008


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------


def test_access_log_redacts_credentials():
    line = hardening.redact("GET /api/workspaces/w/ws?api_key=sk-123&since=4&token=eyJabc HTTP/1.1")
    assert "sk-123" not in line and "eyJabc" not in line
    assert "since=4" in line

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/x?api_key=s3cret", "1.1", 200),
        None,
    )
    hardening.RedactSecretsFilter().filter(record)
    assert "s3cret" not in record.getMessage()


# ---------------------------------------------------------------------------
# Production configuration gate
# ---------------------------------------------------------------------------


def test_production_refuses_unsafe_config():
    _set(env="production", allow_open_workspaces=True, admin_token="", jwt_private_key="", jwt_public_key="")
    problems = hardening.config_problems()
    assert any("OPEN_WORKSPACES" in p for p in problems)
    assert any("ADMIN_TOKEN" in p for p in problems)
    assert any("JWT" in p for p in problems)
    with pytest.raises(RuntimeError, match="refusing to start"):
        hardening.check_configuration()


def test_production_accepts_safe_config():
    _set(
        env="production",
        allow_open_workspaces=False,
        admin_token="a" * 64,
        jwt_private_key="-----BEGIN PRIVATE KEY-----",
        jwt_public_key="-----BEGIN PUBLIC KEY-----",
        cors_origins=["https://erid.example.com"],
    )
    assert hardening.config_problems() == []
    hardening.check_configuration()  # does not raise


def test_docs_are_off_by_default_in_production(monkeypatch):
    monkeypatch.setenv("ERID_ENV", "production")
    monkeypatch.delenv("ERID_EXPOSE_DOCS", raising=False)
    assert Settings().expose_docs is False
    monkeypatch.setenv("ERID_EXPOSE_DOCS", "1")
    assert Settings().expose_docs is True
    monkeypatch.setenv("ERID_ENV", "development")
    monkeypatch.delenv("ERID_EXPOSE_DOCS")
    assert Settings().expose_docs is True


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


async def test_audit_trail_records_security_actions(client: AsyncClient, authed):
    slug, headers = authed
    await client.post(f"/api/workspaces/{slug}/token", json={"api_key": headers["X-API-Key"]})
    await client.post(f"/api/workspaces/{slug}/token", json={"api_key": "wrong"})
    await client.get(f"/api/workspaces/{slug}/tasks", headers={"X-API-Key": "also-wrong"})
    actor = (
        await client.post(f"/api/workspaces/{slug}/actors", json={"name": "ci-bot", "role": "writer"}, headers=headers)
    ).json()
    await client.delete(f"/api/workspaces/{slug}/actors/{actor['id']}", headers=headers)
    rotated = (await client.post(f"/api/workspaces/{slug}/rotate-key", headers=headers)).json()

    trail = (await client.get(f"/api/workspaces/{slug}/audit", headers={"X-API-Key": rotated["api_key"]})).json()
    actions = [e["action"] for e in trail]
    for expected in (
        "workspace.provisioned",
        "token.issued",
        "token.denied",
        "auth.rejected",
        "actor.created",
        "actor.revoked",
        "workspace.key_rotated",
    ):
        assert expected in actions, actions
    denied = next(e for e in trail if e["action"] == "token.denied")
    assert denied["outcome"] == "denied" and denied["client_ip"] == "127.0.0.1"
    ids = [e["id"] for e in trail]
    assert ids == sorted(ids, reverse=True)  # newest first
    created = next(e for e in trail if e["action"] == "actor.created")
    assert created["target"] == "ci-bot" and created["detail"]["role"] == "writer"


async def test_audit_trail_needs_admin(client: AsyncClient, authed):
    slug, headers = authed
    writer = (
        await client.post(f"/api/workspaces/{slug}/actors", json={"name": "w", "role": "writer"}, headers=headers)
    ).json()
    r = await client.get(f"/api/workspaces/{slug}/audit", headers={"X-API-Key": writer["api_key"]})
    assert r.status_code == 403


async def test_audit_trail_does_not_leak_across_slug_reuse(client: AsyncClient):
    old = (await client.post("/api/workspaces", params={"slug": "audit-reuse"})).json()["api_key"]
    old = (await client.post("/api/workspaces/audit-reuse/rotate-key", headers={"X-API-Key": old})).json()["api_key"]
    assert (await client.delete("/api/workspaces/audit-reuse", headers={"X-API-Key": old})).status_code == 204

    # A new owner provisions the same slug and must see only its own history.
    new = (await client.post("/api/workspaces", params={"slug": "audit-reuse"})).json()["api_key"]
    trail = (await client.get("/api/workspaces/audit-reuse/audit", headers={"X-API-Key": new})).json()
    assert [e["action"] for e in trail] == ["workspace.provisioned"]
