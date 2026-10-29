from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import auth, context, context_misc
from app.core.settings import settings
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bring the schema up to date. Runs Alembic "upgrade head" for real
    # databases; tests/SQLite create tables directly from the models instead.
    await init_db()
    yield


app = FastAPI(title="AI Context Hub API", lifespan=lifespan)

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

app.include_router(context.router, prefix="/api", tags=["context"])
# /search & /summary live in context_misc, scoped behind Permission.read.
app.include_router(context_misc.router, prefix="/api", tags=["context_misc"])
# Social login (OAuth) endpoints — open; they mint the same JWT as /token.
app.include_router(auth.router, prefix="/api", tags=["auth"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
        assets_dir = (dist / "assets").resolve()
        target = (assets_dir / asset_path).resolve()
        if target.is_relative_to(assets_dir) and target.is_file():
            return FileResponse(target)
    raise HTTPException(status_code=404, detail="Asset Not Found")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    # API paths must not fall through to the SPA fallback HTML
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    dist = get_frontend_dist()
    if dist and (dist / "index.html").is_file():
        dist_resolved = dist.resolve()
        if full_path:
            target = (dist / full_path).resolve()
            if target.is_relative_to(dist_resolved):
                if target.is_file():
                    return FileResponse(target)
            else:
                # Path traversal attempt outside dist
                raise HTTPException(status_code=404, detail="Not Found")
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
