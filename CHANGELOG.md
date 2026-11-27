# Changelog

## Unreleased: production readiness

Full details: [`docs/production.md`](docs/production.md).

### Scaling and autoscaling
- Stateless API replicas: Alembic serialized by an advisory lock (concurrent
  boots crashed 4 of 6 before), `ERID_RUN_MIGRATIONS` + `python -m app.migrate`,
  configurable connection pool, PgBouncer support (`ERID_DB_PGBOUNCER`,
  `ERID_DIRECT_DATABASE_URL`).
- `/ready` (database + LISTEN connection) beside `/health`; Prometheus `/metrics`.
- Load shedding (`ERID_MAX_INFLIGHT_REQUESTS`, `ERID_MAX_WEBSOCKETS`); graceful
  shutdown closes WebSockets with 1012.
- Production mode never silently falls back to an in-process event bus.
- Kubernetes manifests with HPA, PDB, probes, NetworkPolicies and restricted Pod
  Security; Compose prod overlay runs N replicas behind Caddy; image release
  workflow to GHCR.

### Security
- Rate limits shared across replicas for auth-sensitive routes, per credential
  elsewhere; brute-force lockout; audit trail (`GET /workspaces/{slug}/audit`).
- `ERID_ENV=production` refuses unsafe configuration; docs off in production.
- Security headers, Origin checks on `/mcp` and WebSockets, request body limit,
  credential redaction in access logs, non-root containers.
- Workspace-key JWTs are bound to the key and workspace (rotation now revokes them).

### Features
- File claims: advisory, TTL'd, exclusive/shared leases on paths and globs, with
  conflict reporting (REST + MCP `claim_files`, `release_files`, `list_claims`,
  `check_files`).
- Secret scanning on writes (`ERID_SECRET_SCANNING=redact|reject|off`).
- `GET /tasks` is paginated.

### Fixed
- 500s on over-long fields, NUL characters, lone surrogates and huge offsets;
  MCP errors leaking database internals.
- 24 known vulnerabilities in dependencies: certifi 2026.11.20, cryptography
  50.0.2, mcp 1.30.0, pyjwt 2.15.1. The API image now installs the hash-pinned
  `api/requirements.lock` (exported from `uv.lock`) instead of open-ended ranges.

### Testing
- API and MCP fuzzing, Hypothesis properties, migration/model drift and
  round-trip, multi-process cluster tests, deployment manifest checks, load test
  script; CI adds a load smoke, dependency audits, kubeconform and a production
  Compose run with 3 replicas.

## v0.1.0: soft launch

First tagged release, for an invite-only hosted beta.

### Highlights
- A shared, real-time context server for AI coding tools: tasks, decisions, handoffs and
  presence, shared across Claude Code, Cursor and Codex CLI.
- MCP over Streamable HTTP at `/mcp`, plus a stdio bridge for clients that can't speak HTTP.
- A REST API, a replayable WebSocket event stream (`/ws?since=`) and Postgres LISTEN/NOTIFY
  fan-out across API instances.
- A React dashboard, a VS Code/Cursor extension and a Claude Code plugin.
- Auth: workspace keys, per-actor keys with fine-grained permissions, Ed25519 JWTs, and
  Google/GitHub OAuth with invitations.

### Added for launch
- `docker-compose.prod.yml` + `infra/Caddyfile`: HTTPS via Caddy, closed mode by default,
  required secrets, and a named Postgres volume. `ERID_ENV=prod ./infra/deploy.sh` uses it.
- `ERID_ADMIN_TOKEN`: when set, `POST /api/workspaces` requires `X-Admin-Token`.
- `ERID_PUBLIC_WORKSPACE_DIRECTORY`: set it to `0` to hide the anonymous workspace listing.
- Startup warnings for dev-only settings (open workspaces, no admin token, ephemeral JWT keys).
- `docs/softlaunch.md`: launch checklist, onboarding steps and invite copy.
