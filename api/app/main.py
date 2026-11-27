import asyncio
import contextlib
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from app.api.routes import auth, claims, context, context_misc
from app.core import ratelimit
from app.core.hardening import (
    BodySizeLimitMiddleware,
    NulByteGuard,
    OriginGuardMiddleware,
    SecurityHeadersMiddleware,
    check_configuration,
    install_log_redaction,
)
from app.core.observability import TrafficMiddleware, readiness, render_metrics
from app.core.settings import settings
from app.db import session as db_session
from app.db.session import init_db
from app.mcp_server import endpoint as mcp_endpoint
from app.services import audit
from app.services import claims as claims_svc
from app.services.errors import ServiceError
from app.services.event_bus import close_event_bus, get_event_bus
from app.services.events import prune_events

logger = logging.getLogger("context_hub.main")

# How often the outbox is pruned of events older than the retention window.
PRUNE_INTERVAL_SECS = 3600


async def _housekeeping_forever() -> None:
    """Hourly: prune the event outbox, past rate-limit windows and old audit events."""
    while True:
        try:
            async with db_session.AsyncSessionLocal() as db:
                removed = await prune_events(db)
                await ratelimit.shared.prune(db)
                await audit.prune(db)
                await claims_svc.prune(db)
            if removed:
                logger.info("pruned %d expired events from the outbox", removed)
        except Exception:  # noqa: BLE001 - housekeeping must never take the app down
            logger.exception("housekeeping failed")
        await asyncio.sleep(PRUNE_INTERVAL_SECS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Unsafe settings are warnings in development and a startup error with
    # ERID_ENV=production.
    check_configuration()
    install_log_redaction()
    # Bring the schema up to date. Runs Alembic "upgrade head" for real
    # databases; tests/SQLite create tables directly from the models instead.
    await init_db()
    # Connect the event bus now rather than on first use, so a replica that
    # can't LISTEN fails at startup (production) instead of mid-request.
    await get_event_bus()
    housekeeping = asyncio.create_task(_housekeeping_forever())
    try:
        async with mcp_endpoint.lifespan():
            yield
    finally:
        housekeeping.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await housekeeping
        await close_event_bus()


_docs = settings.expose_docs
app = FastAPI(
    title="AI Context Hub API",
    lifespan=lifespan,
    # Interactive docs are off in production unless ERID_EXPOSE_DOCS=1.
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)

# Middleware runs outermost-last-added. From the inside out: security headers
# and the body limit wrap the app, then metrics + load shedding, then the
# Origin guard, and CORS outermost so even refusals carry CORS headers the
# dashboard can read.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(NulByteGuard)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(TrafficMiddleware)
app.add_middleware(OriginGuardMiddleware)

# The dashboard (web/) is served from a different origin. allow_origins=["*"]
# with allow_credentials=True is invalid per the CORS spec, so enumerate the
# allowed origins explicitly (settings.cors_origins / CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 listing where and why validation failed, without echoing the input.

    FastAPI's default handler reflects each offending value back. That turned a
    body containing a lone UTF-16 surrogate into a 500 (the reply couldn't be
    encoded) and bounced 20k-character payloads straight back to the sender.
    """
    detail = [
        {"loc": list(err.get("loc", ())), "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(ServiceError)
async def _service_error(_request: Request, exc: ServiceError) -> JSONResponse:
    """Map domain errors raised by services to their HTTP status."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(context.router, prefix="/api", tags=["context"])
# /search & /summary live in context_misc, scoped behind Permission.read.
app.include_router(context_misc.router, prefix="/api", tags=["context_misc"])
# Social login (OAuth) endpoints — open; they mint the same JWT as /token.
app.include_router(auth.router, prefix="/api", tags=["auth"])
# Advisory file claims (leases) for coordinating edits.
app.include_router(claims.router, prefix="/api", tags=["claims"])


# MCP over Streamable HTTP. A plain Route (not a Mount) so POST /mcp is served
# directly instead of being redirected to /mcp/. Registered before the SPA
# catch-all below.
app.router.routes.append(Route("/mcp", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"]))


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies (a DB blip must not restart pods)."""
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
async def ready() -> JSONResponse:
    """Readiness: the database answers and the event bus is connected (503 otherwise)."""
    ok, checks = await readiness()
    return JSONResponse({"status": "ready" if ok else "not ready", "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus metrics. Guarded by ``ERID_METRICS_TOKEN`` when set."""
    if settings.metrics_token:
        auth = request.headers.get("authorization", "")
        presented = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not secrets.compare_digest(presented.encode(), settings.metrics_token.encode()):
            raise HTTPException(status_code=401, detail="metrics token required")
    body, content_type = render_metrics()
    return Response(body, media_type=content_type)


_override_frontend_dist: Path | None = None


def set_frontend_dist(dist: Path | str | None) -> None:
    """Override the frontend dist directory (used in tests or dynamic deployment)."""
    global _override_frontend_dist
    _override_frontend_dist = Path(dist).resolve() if dist else None


def get_frontend_dist() -> Path | None:
    """Resolve the directory containing built frontend assets (web/dist)."""
    if _override_frontend_dist is not None:
        return _override_frontend_dist

    # 1. Configured via settings / environment variable
    if settings.frontend_dist_dir:
        p = Path(settings.frontend_dist_dir).resolve()
        if p.exists() and (p / "index.html").is_file():
            return p

    # 2. Check repo-relative location (web/dist relative to project root)
    repo_dist = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
    if repo_dist.exists() and (repo_dist / "index.html").is_file():
        return repo_dist

    # 3. Check common container paths
    for candidate in [Path("/app/web/dist"), Path("./web/dist"), Path("./dist")]:
        if candidate.exists() and (candidate / "index.html").is_file():
            return candidate.resolve()

    return None


@app.get("/assets/{asset_path:path}", include_in_schema=False)
async def serve_assets(asset_path: str):
    dist = get_frontend_dist()
    if dist:
        file = dist / "assets" / asset_path
        if file.is_file():
            return FileResponse(file)
    raise HTTPException(status_code=404, detail="Asset Not Found")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    # API paths must not fall through to the SPA fallback HTML
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    dist = get_frontend_dist()
    if dist and (dist / "index.html").is_file():
        target = dist / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(dist / "index.html")

    if not full_path:
        return {
            "name": "AI Context Hub API",
            "status": "running",
            "docs": "/docs",
            "health": "/health",
            "message": "Frontend assets not built. Run 'npm run build' in web/ to serve the SPA.",
        }

    raise HTTPException(status_code=404, detail="Not Found")
