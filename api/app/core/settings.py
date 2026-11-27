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
    # Comma-separated in CORS_ORIGINS; the local dashboard (:5173), compose web
    # (:8080), and API (:8000) origins. A wildcard ("*") must never be paired with
    # allow_credentials=True (invalid per the CORS spec), so enumerate the dashboard origins.
    raw = os.getenv("CORS_ORIGINS")
    if raw is None:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean env var; "", "0", "false", "no", "off" are false."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", _database_url_default()))
    # Real-time fan-out backend: "postgres" (LISTEN/NOTIFY, works across API
    # instances; the default when DATABASE_URL is Postgres) or "memory"
    # (in-process only; the default otherwise, e.g. SQLite). If the Postgres
    # listener can't connect, the bus falls back to in-process.
    event_bus_backend: str = field(default_factory=lambda: os.getenv("EVENT_BUS_BACKEND", "auto"))
    # How long replayable events are kept in the outbox for ``/ws?since=``.
    event_retention_hours: int = field(default_factory=lambda: int(os.getenv("ERID_EVENT_RETENTION_HOURS", "72")))
    # Header clients use to authenticate against a workspace.
    api_key_header: str = "X-API-Key"
    # Whether "open" workspaces (no key at all) are permitted. ON by default,
    # which is what makes the zero-config quick-start work: an unknown slug is
    # created on first touch and grants full access without credentials.
    #
    # Set ERID_ALLOW_OPEN_WORKSPACES=0 on any deployment reachable by people you
    # don't trust. Closed mode changes three things: an unknown slug 404s instead
    # of being created (so an anonymous caller can neither fill the workspaces
    # table nor squat a slug), an existing keyless workspace grants nothing
    # anonymously, and POST /workspaces/{slug}/secure stops handing its key to
    # whoever asks first — provision with POST /api/workspaces instead, which
    # mints a key up front.
    allow_open_workspaces: bool = field(default_factory=lambda: _env_flag("ERID_ALLOW_OPEN_WORKSPACES", True))
    # Operator secret gating workspace provisioning. When set, POST
    # /api/workspaces requires a matching ``X-Admin-Token`` header, so only the
    # operator can mint new workspaces (and their owner keys). Empty keeps the
    # endpoint open, which is fine locally but lets anyone who can reach a public
    # deployment create workspaces. Generate with: `openssl rand -hex 32`
    admin_token: str = field(default_factory=lambda: os.getenv("ERID_ADMIN_TOKEN", ""))
    # Whether GET /api/workspaces lists every workspace slug to anonymous
    # callers. ON by default (the dashboard's workspace picker uses it). Turn it
    # off on a shared deployment so one team can't enumerate another's slugs;
    # the listing then needs the admin token.
    public_workspace_directory: bool = field(default_factory=lambda: _env_flag("ERID_PUBLIC_WORKSPACE_DIRECTORY", True))
    # Deployment mode. "production" (or "prod") turns configuration warnings
    # into startup errors (see app.core.production) and disables silent
    # fallbacks that are only safe for a single local instance.
    env: str = field(default_factory=lambda: os.getenv("ERID_ENV", "development").strip().lower())
    # Run Alembic "upgrade head" when the API starts. Safe with many replicas
    # (an advisory lock serializes them), but on Kubernetes the migrate Job does
    # it once per rollout and pods set this to 0 to start faster.
    run_migrations: bool = field(default_factory=lambda: _env_flag("ERID_RUN_MIGRATIONS", True))
    # SQLAlchemy connection pool, per API process. Budget it: replicas x
    # (pool_size + max_overflow) + 1 listener each must stay under Postgres
    # max_connections (default 100), or put PgBouncer in front.
    db_pool_size: int = field(default_factory=lambda: int(os.getenv("ERID_DB_POOL_SIZE", "10")))
    db_max_overflow: int = field(default_factory=lambda: int(os.getenv("ERID_DB_MAX_OVERFLOW", "10")))
    db_pool_timeout: float = field(default_factory=lambda: float(os.getenv("ERID_DB_POOL_TIMEOUT", "10")))
    db_pool_recycle: int = field(default_factory=lambda: int(os.getenv("ERID_DB_POOL_RECYCLE", "1800")))
    # Direct (unpooled) Postgres URL for the two things a transaction-pooling
    # PgBouncer breaks: the event bus's LISTEN connection and the migration
    # advisory lock. Defaults to DATABASE_URL; set it when DATABASE_URL points
    # at PgBouncer.
    direct_database_url: str = field(
        default_factory=lambda: (
            os.getenv("ERID_DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL", _database_url_default())
        )
    )
    # Set when DATABASE_URL goes through PgBouncer in transaction mode:
    # disables asyncpg's prepared-statement caches, which that mode can't hold.
    db_pgbouncer: bool = field(default_factory=lambda: _env_flag("ERID_DB_PGBOUNCER", False))
    # Load shedding, per API process. Past these, new HTTP requests get 503 +
    # Retry-After and new WebSockets are refused with close code 1013, so an
    # overloaded instance degrades cleanly while the autoscaler adds replicas
    # instead of falling over. 0 disables a limit.
    max_inflight_requests: int = field(default_factory=lambda: int(os.getenv("ERID_MAX_INFLIGHT_REQUESTS", "256")))
    max_websockets: int = field(default_factory=lambda: int(os.getenv("ERID_MAX_WEBSOCKETS", "2000")))
    # Rate limits ("<count>/<second|minute|hour>", count 0 disables one).
    # auth: per client IP, shared by all replicas, on key->token login,
    #   provisioning, claiming and OAuth.
    # auth_failures: rejected credentials per client IP before it is locked
    #   out for the rest of the window (shared).
    # api: per workspace + credential, counted per replica (so the cluster-wide
    #   ceiling is about replicas x this).
    rate_limits_enabled: bool = field(default_factory=lambda: _env_flag("ERID_RATE_LIMITS", True))
    rate_limit_auth: str = field(default_factory=lambda: os.getenv("ERID_RATE_LIMIT_AUTH", "30/minute"))
    rate_limit_auth_failures: str = field(
        default_factory=lambda: os.getenv("ERID_RATE_LIMIT_AUTH_FAILURES", "20/minute")
    )
    rate_limit_api: str = field(default_factory=lambda: os.getenv("ERID_RATE_LIMIT_API", "1200/minute"))
    # Largest request body accepted, in bytes (413 beyond). Free-text fields
    # are capped at 16k characters, so 1 MiB is generous.
    max_body_bytes: int = field(default_factory=lambda: int(os.getenv("ERID_MAX_BODY_BYTES", str(1024 * 1024))))
    # Serve the interactive API docs (/docs, /redoc, /openapi.json). On by
    # default in development, off in production unless set to 1.
    expose_docs: bool = field(
        default_factory=lambda: _env_flag(
            "ERID_EXPOSE_DOCS", os.getenv("ERID_ENV", "development").strip().lower() not in ("prod", "production")
        )
    )
    # Secret scanning on writes: "redact" (default) replaces credentials found
    # in task/decision/handoff/claim text with [REDACTED:<rule>]; "reject"
    # refuses the write (422); "off" disables it. See app.core.secret_scan.
    secret_scanning: str = field(default_factory=lambda: os.getenv("ERID_SECRET_SCANNING", "redact"))
    # How long audit events are kept.
    audit_retention_days: int = field(default_factory=lambda: int(os.getenv("ERID_AUDIT_RETENTION_DAYS", "90")))
    # Optional bearer token protecting GET /metrics (Prometheus). Empty leaves
    # it open; keep it off the public ingress either way.
    metrics_token: str = field(default_factory=lambda: os.getenv("ERID_METRICS_TOKEN", ""))
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
    # Secret for signing the OAuth ``state`` round-trip (itsdangerous). When
    # empty, OAuth social login is disabled (login/callback return 503).
    session_secret: str = field(default_factory=lambda: os.getenv("ERID_SESSION_SECRET", ""))
    # Lifetime of an OAuth invitation (owner-minted, single-use link that lets a
    # new Google/GitHub identity join a *secured* workspace). Default 7 days.
    oauth_invite_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("ERID_OAUTH_INVITE_TTL_SECONDS", "604800"))
    )
    # Google OAuth app credentials. Empty client id => provider disabled (503).
    oauth_google_client_id: str = field(default_factory=lambda: os.getenv("ERID_OAUTH_GOOGLE_CLIENT_ID", ""))
    oauth_google_client_secret: str = field(default_factory=lambda: os.getenv("ERID_OAUTH_GOOGLE_CLIENT_SECRET", ""))
    # GitHub OAuth app credentials.
    oauth_github_client_id: str = field(default_factory=lambda: os.getenv("ERID_OAUTH_GITHUB_CLIENT_ID", ""))
    oauth_github_client_secret: str = field(default_factory=lambda: os.getenv("ERID_OAUTH_GITHUB_CLIENT_SECRET", ""))
    # Public base URL of THIS API, used to build the provider ``redirect_uri``.
    # Must match the callback URL registered in the provider console.
    oauth_redirect_base: str = field(
        default_factory=lambda: os.getenv("ERID_OAUTH_REDIRECT_BASE", "http://localhost:8000").rstrip("/")
    )
    # Public base URL of the dashboard SPA; the callback redirects here with the
    # minted JWT in the URL fragment. In compose the web service is on :8080.
    oauth_web_base: str = field(
        default_factory=lambda: os.getenv("ERID_OAUTH_WEB_BASE", "http://localhost:8080").rstrip("/")
    )
    # Origins allowed to call the API cross-origin (the dashboard). Comma-
    # separated in CORS_ORIGINS. Never "*" — credentials are disallowed, so a
    # wildcard would conflict; enumerate the dashboard origins explicitly.
    cors_origins: list[str] = field(default_factory=lambda: _cors_origins_default())
    # Directory path to built frontend SPA assets (web/dist). When present, FastAPI
    # serves the web dashboard alongside the REST/WS API routes.
    frontend_dist_dir: str = field(default_factory=lambda: os.getenv("FRONTEND_DIST_DIR", ""))

    @property
    def is_production(self) -> bool:
        return self.env in ("prod", "production")


settings = Settings()
