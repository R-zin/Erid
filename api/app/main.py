from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import context, context_misc
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
# context_misc re-declares /search & /summary behind auth. It must come AFTER
# context.router so the secured routes win for identical paths while the legacy
# open handlers remain registered (the coordinator removes those separately).
app.include_router(context_misc.router, prefix="/api", tags=["context_misc"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
