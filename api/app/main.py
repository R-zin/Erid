from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import context
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: create tables on startup (Alembic is the roadmap's
    # intended migration tool).
    await init_db()
    yield


app = FastAPI(title="AI Context Hub API", lifespan=lifespan)

# The dashboard (web/) is served from a different origin in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context.router, prefix="/api", tags=["context"])


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
