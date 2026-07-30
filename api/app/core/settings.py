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


def _cors_origins_default() -> list[str]:
    # Comma-separated in CORS_ORIGINS; the local dashboard (:5173) + API by
    # default. A wildcard ("*") must never be paired with allow_credentials=True
    # (invalid per the CORS spec), so enumerate the dashboard origins instead.
    raw = os.getenv("CORS_ORIGINS")
    if raw is None:
        return ["http://localhost:5173", "http://localhost:8000"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", _database_url_default()))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    # When true (or when redis is unreachable), the event bus falls back to an
    # in-process bus. Single-instance deployments work without Redis.
    event_bus_backend: str = field(default_factory=lambda: os.getenv("EVENT_BUS_BACKEND", "redis"))
    # Header clients use to authenticate against a workspace.
    api_key_header: str = "X-API-Key"
    # Skip Alembic migrations on startup (create tables directly instead). Used
    # by tests and local SQLite; production should leave this unset.
    skip_migrations: bool = field(default_factory=lambda: os.getenv("ERID_SKIP_MIGRATIONS", "") == "1")
    # Ed25519 (EdDSA) keys for signing/verifying JWT access tokens. PEM-encoded;
    # the private key signs (login endpoint), the public verifies. An ephemeral
    # pair is generated at startup when unset (tokens then die on restart).
    jwt_private_key: str = field(default_factory=lambda: os.getenv("ERID_JWT_PRIVATE_KEY", ""))
    jwt_public_key: str = field(default_factory=lambda: os.getenv("ERID_JWT_PUBLIC_KEY", ""))
    # Access-token lifetime in seconds (default 12h).
    jwt_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("ERID_JWT_TTL_SECONDS", "43200")))
    # Origins allowed to call the API cross-origin (the dashboard). Comma-
    # separated in CORS_ORIGINS. Never "*" — credentials are disallowed, so a
    # wildcard would conflict; enumerate the dashboard origins explicitly.
    cors_origins: list[str] = field(default_factory=lambda: _cors_origins_default())


settings = Settings()
