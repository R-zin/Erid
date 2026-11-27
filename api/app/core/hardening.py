"""HTTP-level hardening: body limits, security headers, Origin checks,
secret-free access logs, and a production configuration gate.

* :class:`BodySizeLimitMiddleware` refuses request bodies over
  ``ERID_MAX_BODY_BYTES`` with 413, whether declared by ``Content-Length`` or
  streamed chunked.
* :class:`SecurityHeadersMiddleware` adds ``nosniff``, frame denial, a strict
  referrer policy, ``Cache-Control: no-store`` and a locked-down CSP on API
  responses (they carry keys and workspace data), plus HSTS over HTTPS.
* :class:`OriginGuardMiddleware` checks the ``Origin`` header on ``/mcp`` and
  on WebSocket handshakes. The MCP spec asks Streamable HTTP servers to
  validate it against DNS rebinding, and it blocks cross-site WebSocket
  hijacking. Non-browser clients send no Origin and are unaffected; a browser
  page is only let through from an allowed origin (``CORS_ORIGINS``).
* :class:`RedactSecretsFilter` scrubs ``api_key``/``token`` query parameters
  from uvicorn's access log. Browsers can't set WebSocket headers, so the
  dashboard authenticates its stream with ``?api_key=``, which would otherwise
  be written to every log line.
* :func:`config_problems` lists unsafe settings; with ``ERID_ENV=production``
  the API refuses to start until they're fixed.
"""

from __future__ import annotations

import json
import logging
import re

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.settings import settings

logger = logging.getLogger("context_hub.hardening")


class _BodyTooLarge(HTTPException):
    """Raised mid-stream. An HTTPException so FastAPI's body parsing re-raises
    it as a 413 instead of wrapping it into a generic 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail="request body too large")


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = settings.max_body_bytes
        if scope["type"] != "http" or not limit:
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    await _reject(send, 413, "request body too large")
                    return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await _reject(send, 413, "request body too large")


async def _reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class NulByteGuard:
    """422 for a NUL byte in the path or query string (raw or %00-encoded).

    Postgres text can't hold NUL, so such a value reaching a query was a 500.
    Request bodies are covered by ``InputModel`` in the schemas.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            raw = scope.get("raw_path") or scope.get("path", "").encode()
            query = scope.get("query_string", b"")
            if b"\x00" in raw or b"%00" in raw.lower() or b"\x00" in query or b"%00" in query.lower():
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008, "reason": "NUL not allowed"})
                else:
                    await _reject(send, 422, "NUL characters are not allowed in the URL")
                return
            if "\x00" in scope.get("path", ""):
                await _reject(send, 422, "NUL characters are not allowed in the URL")
                return
        await self.app(scope, receive, send)


# Applied to API responses. The SPA and the interactive docs (which need
# scripts and styles) only get the headers that can't break a page.
_API_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cross-origin-resource-policy", b"same-origin"),
]
_PAGE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        is_api = path.startswith("/api/") or path in ("/mcp", "/health", "/ready", "/metrics")
        extra = list(_API_HEADERS if is_api else _PAGE_HEADERS)
        if scope.get("scheme") == "https":
            extra.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (name, value) for name, value in extra if name not in present
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


def allowed_origins() -> set[str]:
    return {o.rstrip("/") for o in settings.cors_origins if o and o != "*"}


class OriginGuardMiddleware:
    """Reject browser requests to /mcp and WebSockets from origins not allowed."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        guarded = scope["type"] == "websocket" or (scope["type"] == "http" and scope.get("path") == "/mcp")
        if guarded:
            origin = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"origin"), None)
            if origin is not None and origin.rstrip("/") not in allowed_origins():
                logger.warning("refused %s from origin %r", scope.get("path"), origin)
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008, "reason": "origin not allowed"})
                else:
                    await _reject(send, 403, "origin not allowed")
                return
        await self.app(scope, receive, send)


_SECRET_QUERY = re.compile(r"(?i)\b(api_key|token|access_token|invite|code|state)=([^&\s\"]+)")


def redact(text: str) -> str:
    return _SECRET_QUERY.sub(lambda m: f"{m.group(1)}=[redacted]", text)


class RedactSecretsFilter(logging.Filter):
    """Scrub credentials from query strings in access-log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install_log_redaction() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        log = logging.getLogger(name)
        if not any(isinstance(f, RedactSecretsFilter) for f in log.filters):
            log.addFilter(RedactSecretsFilter())


def config_problems() -> list[str]:
    """Settings that are unsafe on a deployment strangers can reach."""
    problems: list[str] = []
    if settings.allow_open_workspaces:
        problems.append("ERID_ALLOW_OPEN_WORKSPACES is on: anyone can create and use workspaces anonymously")
    if len(settings.admin_token) < 32:
        problems.append("ERID_ADMIN_TOKEN is unset or shorter than 32 characters (openssl rand -hex 32)")
    if not (settings.jwt_private_key and settings.jwt_public_key):
        problems.append(
            "ERID_JWT_PRIVATE_KEY/ERID_JWT_PUBLIC_KEY are unset: tokens are signed with a per-process key, "
            "so they fail on other replicas and die on restart"
        )
    oauth_on = settings.oauth_google_client_id or settings.oauth_github_client_id
    if oauth_on and len(settings.session_secret) < 32:
        problems.append("OAuth is configured but ERID_SESSION_SECRET is unset or shorter than 32 characters")
    if "*" in settings.cors_origins:
        problems.append("CORS_ORIGINS contains '*'")
    if not settings.rate_limits_enabled:
        problems.append("ERID_RATE_LIMITS is off")
    return problems


def check_configuration() -> None:
    """Warn about unsafe settings; in production, refuse to start on any."""
    problems = config_problems()
    if not problems:
        return
    if settings.is_production:
        raise RuntimeError(
            "refusing to start with ERID_ENV=production and an unsafe configuration:\n  - " + "\n  - ".join(problems)
        )
    for problem in problems:
        logger.warning("insecure for production: %s", problem)
