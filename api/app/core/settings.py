"""Application settings.

Reads configuration from environment variables (optionally via a local `.env`
file). Centralizing this avoids scattering hardcoded hosts/secrets across the
codebase and keeps Docker, native, and test environments consistent.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _database_url_default() -> str:
    # Docker Compose injects DATABASE_URL explicitly; this default targets a
    # locally-running Postgres (native dev mode).
    return "postgresql+asyncpg://postgres:postgres@localhost:5432/erid"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", _database_url_default()))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    # When true (or when redis is unreachable), the event bus falls back to an
    # in-process bus. Single-instance deployments work without Redis.
    event_bus_backend: str = field(default_factory=lambda: os.getenv("EVENT_BUS_BACKEND", "redis"))
    # Header clients use to authenticate against a workspace.
    api_key_header: str = "X-API-Key"


settings = Settings()
