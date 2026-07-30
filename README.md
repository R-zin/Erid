# AI Context Hub

A shared, real-time context server for AI coding tools. **Claude Code, Cursor,
and Codex CLI all read from and write to the same project state** — tasks,
decisions, and who's-working-on-what — instead of every session starting from
zero.

The MCP tools your editor already has (`workspace_summary`, `create_decision`,
`update_task`, `update_presence`, …) talk to this one hub, so context built up
in one tool is immediately visible in every other tool and on a live dashboard.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Claude Code │  │   Cursor    │  │  Codex CLI  │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │   MCP (stdio / streamable-http)  │
       └────────────────┼────────────────┘
                        ▼
              ┌──────────────────┐        ┌──────────┐
              │   MCP server     │───────▶│ REST API │◀────────┐
              │ (mcp-server/)    │ HTTP   │  (api/)  │         │
              └──────────────────┘        └────┬─────┘         │
                                               │               │
                              ┌────────────────┼───────────┐   │
                              ▼                ▼           ▼   │
                         ┌─────────┐    ┌───────────┐  ┌─────┐│
                         │Postgres │    │ Redis     │  │ WS  ││
                         │ (state) │    │ pub/sub   │  │push ││
                         └─────────┘    └───────────┘  └──┬──┘│
                                                          ▼   │
                                                    ┌──────────┐
                                                    │ web/     │
                                                    │ dashboard│
                                                    └──────────┘
```

## Why

Each AI tool keeps its own scratchpad. Decisions made in one session are
invisible to the next, two agents redo the same analysis, and there's no shared
list of what's in flight. The Hub externalizes that state into one store with a
real-time feed, so:

- **Continuity** — a new session calls `workspace_summary` and immediately knows
  open tasks, recent decisions, and active collaborators.
- **No duplicate work** — `search_context` / `recent_decisions` surface what's
  already been decided before re-deciding it.
- **Coordination** — `update_presence` broadcasts "I'm editing `auth.py`" so
  humans and agents don't collide.
- **Visibility** — the dashboard shows all of it live over a WebSocket.

## Components

| Dir          | What it is                                                            |
| ------------ | --------------------------------------------------------------------- |
| `api/`       | FastAPI + Postgres. State, REST routes, and the WebSocket event feed. |
| `mcp-server/`| MCP server exposing the state as tools to AI clients (stdio or HTTP). |
| `clients/`   | Ready-made MCP configs for Claude Code, Cursor, Codex CLI.            |
| `web/`       | React dashboard: live presence, open tasks, recent decisions over WS. |
| `tests/`     | Integration tests for the API routes + WebSocket (pytest + httpx).    |
| `mcp-server/tests/` | Integration test driving the MCP tools against a live API.       |

## Quick start

### With Docker Compose

```bash
docker compose up -d postgres redis api
curl http://localhost:8000/health    # {"status":"ok"}
open http://localhost:8000/docs      # interactive OpenAPI docs
```

Add the dashboard container to serve the React UI (proxies `/api` + WS to `api`):

```bash
docker compose up -d web            # http://localhost:8080
```

### Natively (no Docker)

You need Postgres and Redis running locally, and [`uv`](https://astral.sh/uv):

```bash
# one-time: create the database
createdb erid   # role/password postgres:postgres per docker-compose

# run the API
cd api
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/erid" \
REDIS_URL="redis://localhost:6379/0" \
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# run the dashboard (proxies /api to :8000)
cd web && npm install && npm run dev    # http://localhost:5173
```

The API creates its tables on startup (a dev convenience; Alembic is the
roadmap's intended migration tool).

## Using it from an AI tool

Point your tool's MCP config at the server. `clients/` has ready examples for
Claude Code, Cursor, and Codex. For Claude Code:

```bash
claude mcp add context-hub \
  --env API_BASE=http://localhost:8000 \
  --env WORKSPACE_SLUG=your-workspace \
  -- uv run python mcp-server/src/server.py --transport stdio
```

`WORKSPACE_SLUG` sets a default workspace so tools don't need a slug each call.
`WORKSPACE_API_KEY` (optional) authenticates against a secured workspace.

Then the tools are available in-session: `workspace_summary`, `search_context`,
`current_tasks`, `create_task`, `update_task`, `create_decision`,
`recent_decisions`, `active_developers`, `update_presence`, `task_decisions`.
The server also exposes read-only **resources** (`workspace://{slug}/summary`,
`.../tasks`, `.../decisions`, `.../presence`) and **prompts**
(`summarize_workspace`, `standup_report`, `catch_up`).

## Auto-presence (file watch)

`mcp-server/src/watcher.py` keeps "who's working on what" current without manual
`update_presence` calls: it polls a directory (your repo) for the most recently
modified source file and posts it as your `current_file` presence heartbeat.

```bash
WORKSPACE_SLUG=your-workspace WORKSPACE_API_KEY=$KEY \
  uv run python mcp-server/src/watcher.py   # add & to background it
```

Config: `WATCH_ROOT` (default cwd), `WATCH_INTERVAL` seconds (default 15),
`PRESENCE_NAME` (default: your git `user.name`, else `$USER`). It reuses the
same `API_BASE`/`WORKSPACE_API_KEY`/`WORKSPACE_TOKEN` env as the MCP client, and
ignores VCS internals, caches, hidden files, and build output.

## Authentication

Workspaces are **open** (no auth) until secured. Once secured, requests
authenticate as a **principal** carrying fine-grained **permissions**. Three
credential shapes are accepted:

- **Legacy workspace key** — the original shared `workspaces.api_key`; maps to
  full access (owner). Existing setups keep working.
- **Per-actor key** — each actor (person/bot) gets its own key, scoped by role +
  grants. Only its SHA-256 is stored; it's disclosed **once** at minting.
- **JWT (Ed25519)** — exchange a key for a short-lived bearer token at the login
  endpoint; send as `Authorization: Bearer <jwt>`.

**Roles:** `reader` (read-only) → `writer` (read + write tasks/decisions/
presence) → `owner` (writer + mint/revoke keys, manage actors). Grants give
per-resource control: `read`, `write_tasks`, `write_decisions`, `presence`,
`admin_keys`, `owner` (implies all). An actor's permissions are its role defaults
plus any explicit grants.

```bash
# Provision a workspace (returns the legacy/owner key once)
KEY=$(curl -s -XPOST 'http://localhost:8000/api/workspaces?slug=myproj' | jq -r .api_key)

# Mint a per-actor writer (admin only); raw key shown once
ACTOR=$(curl -s -XPOST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  'http://localhost:8000/api/workspaces/myproj/actors' -d '{"name":"claude","role":"writer"}' | jq -r .api_key)

# Exchange for a JWT, then use it
TOKEN=$(curl -s -XPOST -H 'Content-Type: application/json' \
  'http://localhost:8000/api/workspaces/myproj/token' -d "{\"api_key\":\"$ACTOR\"}" | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/workspaces/myproj/tasks
```

Send a key as the `X-API-Key` header for REST, or `?api_key=...` / `?token=...`
on the WebSocket (browsers can't set WS headers). JWT Ed25519 keys come from
`ERID_JWT_PRIVATE_KEY`/`ERID_JWT_PUBLIC_KEY` (PEM); an ephemeral pair is
generated if unset (tokens then die on restart — set them in production).

## REST API

Base path `/api`, workspace-scoped under `/workspaces/{slug}`:

| Method | Path                          | Auth | Purpose                          |
| ------ | ----------------------------- | ---- | -------------------------------- |
| GET    | `/health`                     | —    | liveness                         |
| POST   | `/workspaces?slug=`           | —    | provision + mint API key         |
| GET    | `/workspaces/{slug}/summary`  | key* | counts + active developers       |
| GET    | `/workspaces/{slug}/search?q=`| key* | search decisions + tasks         |
| GET    | `/workspaces/{slug}/tasks`    | key* | list (filter `?status=`)         |
| POST   | `/workspaces/{slug}/tasks`    | key* | create                           |
| PUT    | `/workspaces/{slug}/tasks/{id}`| key*| update status/title/assignee     |
| GET    | `/workspaces/{slug}/decisions`| key* | list recent (`?limit=`)          |
| POST   | `/workspaces/{slug}/decisions`| key* | record a decision                |
| GET    | `/workspaces/{slug}/presence` | key* | active collaborators             |
| POST   | `/workspaces/{slug}/presence` | key* | presence heartbeat (upsert)      |
| POST   | `/workspaces/{slug}/actors`   | admin| mint per-actor key (shown once)  |
| GET    | `/workspaces/{slug}/actors`   | admin| list actors (never keys)         |
| DELETE | `/workspaces/{slug}/actors/{id}`| admin | revoke an actor                |
| POST   | `/workspaces/{slug}/token`    | key* | exchange a key for a JWT         |
| WS     | `/workspaces/{slug}/ws`       | key* | real-time event stream           |

\* only when the workspace has a key configured; open workspaces skip auth.
`admin` requires the `admin_keys` permission (owner or a granted admin). Each
route enforces a specific permission (`read`/`write_tasks`/`write_decisions`/
`presence`); a key/token must carry it.

## Real-time events

Mutations publish events (`task_created`, `task_updated`, `decision_created`,
`presence_updated`) onto the workspace's stream. The event bus
(`api/app/services/event_bus.py`) uses **Redis pub/sub** so updates fan out
across multiple API instances; if Redis is unreachable it falls back to an
in-process bus (single-instance dev/tests need no broker). Select with
`EVENT_BUS_BACKEND=redis|memory`.

The dashboard subscribes at `GET /api/workspaces/{slug}/ws` and re-renders live.

## Testing

```bash
uv run pytest            # API routes + WebSocket + MCP tool round-trip
```

`tests/` runs the app against an isolated in-memory SQLite DB (no Postgres
needed) and includes a live WebSocket-over-uvicorn test. `mcp-server/tests/`
boots a real API subprocess and drives the MCP client end-to-end; set
`ERID_LIVE_API` to target an already-running server instead.

## Configuration

Environment variables (see `api/app/core/settings.py`, `mcp-server/src/client.py`):

| Var                 | Default                                            | Used by   |
| ------------------- | -------------------------------------------------- | --------- |
| `DATABASE_URL`      | `postgresql+asyncpg://postgres:postgres@localhost:5432/erid` | api |
| `REDIS_URL`         | `redis://localhost:6379/0`                         | api       |
| `EVENT_BUS_BACKEND` | `redis` (falls back to in-process if unreachable)  | api       |
| `CORS_ORIGINS`      | `http://localhost:5173,http://localhost:8000`      | api       |
| `API_BASE`          | `http://localhost:8000`                            | mcp-server|
| `WORKSPACE_SLUG`    | —                                                  | mcp-server|
| `WORKSPACE_API_KEY` | —                                                  | mcp-server|

Docker Compose injects `DATABASE_URL`/`REDIS_URL` pointing at the container
hosts; the defaults target local services for native dev.

## Roadmap

Done (this iteration):

- [x] REST API for tasks / decisions / presence + summary + search
- [x] All 9 MCP tools wired end-to-end and config for Claude/Cursor/Codex
- [x] Redis-backed event bus (in-process fallback) + WebSocket stream
- [x] Single API-key-per-workspace auth
- [x] Live React dashboard (presence, tasks, decisions)
- [x] Integration tests (API routes, WebSocket, MCP round-trip)
- [x] Alembic migrations (`upgrade head` on startup; tests/SQLite use `create_all`)
- [x] Postgres FTS for `search_context` (generated `search_vector` + GIN/`pg_trgm` indexes; `websearch_to_tsquery`)
- [x] Richer auth: per-actor keys, roles, fine-grained grants, Ed25519 (EdDSA) JWT
- [x] Decision ↔ task linking (`decisions.task_id`) and file-watch auto-presence (`mcp-server/src/watcher.py`)
- [x] MCP `resources` (`workspace://{slug}/{summary,tasks,decisions,presence}`) + `prompts` (`summarize_workspace`, `standup_report`, `catch_up`)
- [x] Containerized dashboard (`web/Dockerfile`, multi-stage → nginx proxying `/api` + WS) + compose `web` service; CORS origins via `CORS_ORIGINS` (`docker compose up` not yet verified — env had no docker CLI)
- [x] `/search` + `/summary` scoped behind the `read` permission (`context_misc.py`)
- [x] Presence atomic upsert (`INSERT … ON CONFLICT`) + `uq_presence_workspace_actor`, `decisions.made_by` / `tasks.assigned_to` indexes
- [x] DELETE endpoints (`/tasks/{id}` → `write_tasks`, `/decisions/{id}` → `write_decisions`, `/workspaces/{slug}` → owner, cascading)
- [x] Workspace management (`GET /workspaces` directory, `POST /{slug}/secure` claim, `POST /{slug}/rotate-key`)
- [x] Dashboard auth flow (per-workspace key/token, persisted) + workspace switcher + quick task-create form
- [x] Test sweep: WS-auth happy/negative, non-decision event payloads, edge cases, MCP client error paths (90 tests)
- [x] Codex CLI config (`clients/codex.toml`); empty `mcp-server/src/tools/` stubs removed

All roadmap items complete. Future ideas (not scoped): OAuth providers, multi-instance MCP resources, dashboard decision-create UI, deploy/CI verification of the compose stack.
