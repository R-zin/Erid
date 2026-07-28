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
`recent_decisions`, `active_developers`, `update_presence`.

## Authentication

One API key per workspace (intentionally minimal — full JWT/OAuth is on the
roadmap).

- `POST /api/workspaces?slug=NAME` creates a workspace and returns its key
  **once** (it is never re-disclosed).
- A workspace touched first via a normal read/write auto-creates **open**
  (no key) so onboarding is frictionless; secure it by provisioning explicitly.
- Send the key as the `X-API-Key` header for REST, or `?api_key=...` on the
  WebSocket (browsers can't set WS headers).

```bash
KEY=$(curl -s -XPOST 'http://localhost:8000/api/workspaces?slug=myproj' | jq -r .api_key)
curl -H "X-API-Key: $KEY" http://localhost:8000/api/workspaces/myproj/tasks
```

## REST API

Base path `/api`, workspace-scoped under `/workspaces/{slug}`:

| Method | Path                          | Auth | Purpose                          |
| ------ | ----------------------------- | ---- | -------------------------------- |
| GET    | `/health`                     | —    | liveness                         |
| POST   | `/workspaces?slug=`           | —    | provision + mint API key         |
| GET    | `/workspaces/{slug}/summary`  | open | counts + active developers       |
| GET    | `/workspaces/{slug}/search?q=`| open | search decisions + tasks         |
| GET    | `/workspaces/{slug}/tasks`    | key* | list (filter `?status=`)         |
| POST   | `/workspaces/{slug}/tasks`    | key* | create                           |
| PUT    | `/workspaces/{slug}/tasks/{id}`| key*| update status/title/assignee     |
| GET    | `/workspaces/{slug}/decisions`| key* | list recent (`?limit=`)          |
| POST   | `/workspaces/{slug}/decisions`| key* | record a decision                |
| GET    | `/workspaces/{slug}/presence` | key* | active collaborators             |
| POST   | `/workspaces/{slug}/presence` | key* | presence heartbeat (upsert)      |
| WS     | `/workspaces/{slug}/ws`       | key* | real-time event stream           |

\* only when the workspace has a key configured; open workspaces skip auth.

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

Next:

- [ ] Alembic migrations (replace startup `create_all`)
- [ ] Postgres `citext`/full-text indexes for `search_context`
- [ ] Richer auth: per-actor keys, roles, JWT/OAuth
- [ ] Decision ↔ task linking and file-watch auto-presence
- [ ] Dashboard auth flow + workspace switcher and creation UI
- [ ] MCP `resources`/`prompts` in addition to tools
