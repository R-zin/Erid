# Erid - Realtime Context Server for AI

A shared, real-time context server for AI coding tools. **Claude Code, Cursor,
and Codex CLI all read from and write to the same project state** — tasks,
decisions, and who's-working-on-what — instead of every session starting from
zero.

The MCP tools your editor already has (`workspace_summary`, `create_decision`,
`update_task`, `update_presence`, …) talk to this one hub, so context built up
in one tool is immediately visible in every other tool and on a live dashboard.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐   ┌───────────────────┐
│ Claude Code │  │   Cursor    │  │  Codex CLI  │   │ web/ dashboard,   │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │ VS Code, JetBrains│
       └──── MCP over HTTP (/mcp) ───────┘          └─────────┬─────────┘
                        │                       REST + WebSocket (/ws?since=)
                        ▼                                      ▼
        ┌───────────────────────────────────────────────────────────────┐
        │ API (api/)   routes ─┬─ MCP endpoint ─┬─ WebSocket stream     │
        │                      ▼                ▼                       │
        │            services (app/services): one implementation        │
        │            of every operation + transactional event outbox    │
        └──────────────────────────────┬────────────────────────────────┘
                                       ▼
                     ┌───────────────────────────────────┐
                     │ Postgres: state, event outbox,    │
                     │ LISTEN/NOTIFY fan-out across      │
                     │ API instances                     │
                     └───────────────────────────────────┘
```

Two moving parts: the API process (run as many as you like) and Postgres.

## Why

Each AI tool keeps its own scratchpad. Decisions made in one session are
invisible to the next, two agents redo the same analysis, and there's no shared
list of what's in flight. The Hub externalizes that state into one store with a
real-time feed, so:

- **Continuity** — a new session calls `workspace_summary` (or `catch_up`) and
  immediately knows open tasks, recent decisions, waiting handoffs, and active
  collaborators. A wrapping-up session calls `create_handoff` to leave the state
  of play for whoever picks up next.
- **No duplicate work** — `search_context` / `recent_decisions` surface what's
  already been decided before re-deciding it.
- **Coordination** — `update_presence` broadcasts "I'm editing `auth.py`", and
  `claim_files` takes an advisory lease on paths so two agents don't edit the
  same files: a conflicting claim comes back with who holds it and why.
- **Visibility** — the dashboard shows all of it live over a WebSocket.
- **Safe to share** — credentials pasted into tasks, decisions or handoffs are
  redacted before anyone (or any agent) sees them, and security-relevant
  actions land in an audit trail.

## Components

| Dir          | What it is                                                            |
| ------------ | --------------------------------------------------------------------- |
| `api/`       | FastAPI + Postgres. State, REST routes, the WebSocket event feed, and the MCP endpoint at `/mcp`. Routes and MCP tools are thin adapters over `app/services/`. |
| `api/openapi.json` | The committed API contract; regenerate with `uv run python scripts/export_openapi.py`. |
| `mcp-server/`| Standalone stdio MCP server (same tools, over REST) for clients that can't speak HTTP MCP. |
| `mcp-server/src/bridge.py` | stdio JSON-RPC bridge editor plugins spawn (owns all hub I/O). |
| `editors/vscode/` | VS Code/Cursor extension: live sidebar, quick actions, auto-presence, MCP setup. |
| `editors/claude-code/` | Claude Code plugin: bundles the MCP server + `/hub:*` slash commands. |
| `clients/`   | Ready-made MCP configs for Claude Code, Cursor, Codex CLI.            |
| `web/`       | React dashboard: live presence, open tasks, recent decisions over WS. |
| `tests/`     | Integration tests for the API routes + WebSocket (pytest + httpx).    |
| `mcp-server/tests/` | Integration test driving the MCP tools against a live API.       |

## Quick start

### With Docker Compose

```bash
docker compose up -d postgres api
curl http://localhost:8000/health    # {"status":"ok"}
open http://localhost:8000/docs      # interactive OpenAPI docs
```

Add the dashboard container to serve the React UI (proxies `/api` + WS to `api`):

```bash
docker compose up -d web            # http://localhost:8080
```

### Natively (no Docker)

You need Postgres running locally, and [`uv`](https://astral.sh/uv):

```bash
# one-time: create the database
createdb erid   # role/password postgres:postgres per docker-compose

# run the API
cd api
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/erid" \
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# run the dashboard (proxies /api to :8000)
cd web && npm install && npm run dev    # http://localhost:5173
```

The API runs the Alembic migrations (`upgrade head`) on startup.

## Deploy (self-host)

The `docker-compose.yml` stack is healthchecked and start-ordered:
`postgres` exposes a `pg_isready` healthcheck, and
`api` (which waits on it with `service_healthy`) probes its own `/health`
endpoint using Python baked into its slim image (no `curl` dependency). The
`web` service waits for `api` to be healthy before starting. Bring the whole
web stack up with:

```bash
docker compose up -d postgres api web
```

Only `api` (`:8000`) and `web` (`:8080`) publish on all interfaces. Postgres is
bound to `127.0.0.1`: it runs with default credentials, so it must stay
off-box; the `api` container reaches it over the compose network regardless. Host tools (`psql`) still work from the machine itself.

### Configuration (.env)

Copy `.env.example` to `.env` and fill it in — Compose reads it automatically.
It documents the MCP-worker vars (`WORKSPACE_SLUG`, `WORKSPACE_API_KEY`,
`WORKSPACE_TOKEN`), the session secret (`ERID_SESSION_SECRET`), the OAuth
credentials, and `ERID_JWT_PRIVATE_KEY`/`ERID_JWT_PUBLIC_KEY`. Set a stable
Ed25519 JWT keypair so access tokens survive restarts (an ephemeral pair is
generated otherwise); `.env.example` shows the `openssl` commands.

### One-shot deploy

`infra/deploy.sh` runs the deploy on a host: it does `git pull --ff-only`,
rebuilds the `api`/`web` images, restarts the stack, and polls
`http://localhost:8000/health` until the API is up:

```bash
./infra/deploy.sh
```

### Public deployment (production overlay)

For a server other people can reach, layer `docker-compose.prod.yml` on top.
It puts Caddy in front with automatic HTTPS for `ERID_DOMAIN`, unpublishes
`api`/`web` (only `:80`/`:443` are exposed), keeps Postgres data in a named
volume, runs `ERID_API_REPLICAS` (default 2) API replicas behind Caddy, and
defaults to closed mode. It **refuses to start** without `ERID_DOMAIN`,
`POSTGRES_PASSWORD`, `ERID_ADMIN_TOKEN` and a JWT keypair, and the API itself
runs in production mode (`ERID_ENV=production`), which refuses any other
unsafe setting:

```bash
cp .env.example .env    # set ERID_ENV=prod, ERID_DOMAIN, POSTGRES_PASSWORD,
                        # ERID_ADMIN_TOKEN, ERID_SESSION_SECRET, JWT keypair
./infra/deploy.sh       # uses the prod overlay when ERID_ENV=prod

# Provision a workspace for a team (operator only):
curl -XPOST "https://$ERID_DOMAIN/api/workspaces?slug=acme" -H "X-Admin-Token: $ERID_ADMIN_TOKEN"
```

MCP clients then point at `https://$ERID_DOMAIN/mcp`. See
[`docs/softlaunch.md`](docs/softlaunch.md) for the full launch checklist.

### Kubernetes (autoscaling) and production guide

[`deploy/k8s/`](deploy/k8s/README.md) deploys the API and dashboard with
HorizontalPodAutoscalers, PodDisruptionBudgets, readiness/liveness probes,
NetworkPolicies and the restricted Pod Security Standard
(`kubectl apply -k deploy/k8s/base`). [`docs/production.md`](docs/production.md)
covers how Erid scales (stateless replicas, LISTEN/NOTIFY fan-out, migration
lock, load shedding, graceful shutdown), its security controls, every
production setting, and load-test results.

### CI verification

The `compose-verify` job in `.github/workflows/tests.yml` builds the full
compose stack on `ubuntu-latest`, starts it, waits for `/health`, and runs a
REST round-trip smoke (provision a workspace, then assert it shows up in
`GET /api/workspaces`) before tearing down with `docker compose down -v`.

### OAuth provider setup

To enable social login, register an OAuth app with each provider and put the
client ID/secret in `.env`. The callback URLs are derived from
`ERID_OAUTH_REDIRECT_BASE`:

- **Google** — Google Cloud Console → APIs & Services → Credentials → Create
  OAuth 2.0 Client ID (Web). Authorized redirect URI:
  `{ERID_OAUTH_REDIRECT_BASE}/api/auth/google/callback`
- **GitHub** — Settings → Developer settings → OAuth Apps → New OAuth App.
  Authorization callback URL:
  `{ERID_OAUTH_REDIRECT_BASE}/api/auth/github/callback`

Set `ERID_OAUTH_WEB_BASE` to where the dashboard is served (default
`http://localhost:8080`) so users land back in the UI after login.

### MCP worker (optional)

The `mcp-server` service is a stdio MCP worker (one per editor/agent), not part
of the default web stack — it is gated behind the `mcp` profile. Start it
explicitly:

```bash
docker compose --profile mcp up -d
```

## Using it from an AI tool

The API serves MCP itself, over Streamable HTTP at `/mcp`. Point your tool at
the URL; there's nothing to install or run locally. For Claude Code:

```bash
claude mcp add --transport http erid http://localhost:8000/mcp \
  --header "X-Erid-Workspace: your-workspace" \
  --header "X-API-Key: $KEY"          # omit for an open workspace
```

`X-Erid-Workspace` (or `?workspace=` on the URL) sets the default workspace so
tools don't need a slug each call. Authenticate with `X-API-Key` or
`Authorization: Bearer <jwt>`; every tool enforces the same permission as the
matching REST route. `clients/` has configs for Claude Code, Cursor, and Codex.

For a client that only speaks stdio MCP, `mcp-server/src/server.py` exposes the
same tools over REST (a test keeps the two surfaces identical):

```bash
claude mcp add context-hub \
  --env API_BASE=http://localhost:8000 \
  --env WORKSPACE_SLUG=your-workspace \
  -- uv run python mcp-server/src/server.py --transport stdio
```

Then the tools are available in-session: `workspace_summary`, `search_context`,
`current_tasks`, `create_task`, `update_task`, `create_decision`,
`recent_decisions`, `active_developers`, `update_presence`, `task_decisions`,
plus session handoffs: `create_handoff`, `recent_handoffs`, `acknowledge_handoff`,
`resolve_handoff`. The server also exposes read-only **resources**
(`workspace://{slug}/summary`, `.../tasks`, `.../decisions`, `.../handoffs`,
`.../presence`) and **prompts** (`summarize_workspace`, `standup_report`,
`catch_up` — which now briefs on open handoffs first).

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

## Editor plugin (VS Code / Cursor)

`editors/vscode/` is an installable extension that brings the hub's core features
into the editor for a **human**, alongside the AI-facing MCP server. One `.vsix`
installs into VS Code, Cursor, and other VS Code forks. It provides:

- **Live sidebar** — Tasks, Decisions, and Presence views (in an Activity-bar
  container) that update in real time over the hub's WebSocket, plus a
  summary/live-status item.
- **Quick actions** — create / complete / delete tasks, record decisions
  (pre-filling `related_files` with the current file and optionally linking a
  task), and search the workspace, all from the command palette.
- **Auto-presence** — heartbeats "you're editing `<file>`" as a `human` actor
  (240s cadence, mirroring `watcher.py`), so collaborators and agents see you.
- **MCP auto-setup** — `AI Context Hub: Setup MCP` writes `.vscode/mcp.json` (or
  the Cursor equivalent) so the editor's AI agent shares the same hub.

The extension never talks to the API directly. It spawns
`uv run python mcp-server/src/bridge.py` (from `contextHub.repoPath`, default
`${workspaceFolder}`) — a stdio **JSON-RPC bridge** that owns the HTTP + WebSocket
connection and reuses the same `APIClient` as the MCP server. Install it:

```bash
cd editors/vscode && npm install && npm run compile && npx vsce package
# produces editors/vscode/ai-context-hub-<version>.vsix
```

Install it in either editor via **"Extensions: Install from VSIX…"**. The same `.vsix` works in
Cursor (a VS Code fork). In Cursor, the **MCP config still goes to `.cursor/mcp.json`** (top-level
`mcpServers`) rather than `.vscode/mcp.json` — the `AI Context Hub: Set Up MCP Config` command
offers to write that Cursor file too.

Settings: `contextHub.apiBase` (default `http://localhost:8000`),
`contextHub.workspaceSlug`, `contextHub.actorName`, `contextHub.autoPresence`,
`contextHub.heartbeatSeconds`, `contextHub.repoPath`. The API key/token live in
the editor's SecretStorage (set via `AI Context Hub: Connect`), never in
`settings.json` or written into `mcp.json`. The same bridge protocol is designed
to back a future JetBrains plugin.

## Claude Code plugin

`editors/claude-code/` is the Claude Code counterpart: a terminal can't show the
sidebar, so the surface is the **MCP server + `/hub:*` slash commands**. The plugin
bundles the same `mcp-server/` in `.mcp.json` (launching `mcp-server/src/server.py`
via `${CLAUDE_PROJECT_DIR}`) plus commands that drive it — `/hub:summary`,
`/hub:tasks`, `/hub:task-create`, `/hub:decision-record`, `/hub:search`,
`/hub:catch-up`, and more. It reads the same env vars (`API_BASE`, `WORKSPACE_SLUG`,
`WORKSPACE_API_KEY`, `WORKSPACE_TOKEN`) from your shell.

```bash
# from a Claude Code session started at the repo root
/plugin install ./editors/claude-code
# or via the repo marketplace (./.claude-plugin/marketplace.json):
/plugin marketplace add .
/plugin install context-hub@erid
```

It's **in-repo / project-scoped**: the MCP config references this repo's `mcp-server/`,
so it works from any clone but isn't a portable bundle. See
[`editors/claude-code/README.md`](editors/claude-code/README.md).

**Codex CLI** has no plugin UI — it's MCP-config only (`clients/codex.toml`, see
[clients/README.md](clients/README.md#codex-cli)).

## Authentication

Workspaces are **open** (no auth) until secured. Once secured, requests
authenticate as a **principal** carrying fine-grained **permissions**. Three
credential shapes are accepted:

- **Legacy workspace key** — the original shared workspace key; maps to full
  access (owner). Only its SHA-256 is stored, and it's disclosed once, when
  minted (provision, `/secure`, `rotate-key`).
- **Per-actor key** — each actor (person/bot) gets its own key, scoped by role +
  grants. Only its SHA-256 is stored; it's disclosed **once** at minting.
- **JWT (Ed25519)** — exchange a key for a short-lived bearer token at the login
  endpoint (or get one via social login, below); send as
  `Authorization: Bearer <jwt>`. An actor token's `sub` is the actor's **id**,
  not its name, and is resolved by id within the token's workspace — so a name
  collision, or a name reused after an actor is deleted, can never make a token
  act as a different actor. Role and grants are read from the actor row, not the
  token. (Legacy workspace-key tokens carry `sub` = the slug and act as owner.)

### Social login (Google / GitHub) admission

OAuth login only ever yields a token for an actor **in the workspace named by
`slug`**, under this policy (checked in order on the callback):

1. **Already linked here.** If this Google/GitHub account is linked to an actor
   in *this* workspace, it logs in as that actor. Links are per workspace
   (`oauth_identities` is unique on `(provider, provider_subject, workspace_id)`):
   a link made in workspace A is never consulted when logging in to B. If that
   actor was removed or deactivated, login is refused — revocation sticks.
2. **Invited.** Otherwise, a valid invitation links the account to the actor it
   names. An admin creates the actor (with the role it should have), then mints
   an invite:

   ```bash
   ID=$(curl -s -XPOST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
     'http://localhost:8000/api/workspaces/myproj/actors' -d '{"name":"alice","role":"writer"}' | jq -r .id)
   curl -s -XPOST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
     "http://localhost:8000/api/workspaces/myproj/actors/$ID/oauth-invite" -d '{"email":"alice@example.com"}'
   # → {"invite": "...", "login_urls": {"github": ".../api/auth/github/login?slug=myproj&invite=...", ...}}
   ```

   Send the invitee a `login_urls` entry. The invite is signed with
   `ERID_SESSION_SECRET`, expires after `ERID_OAUTH_INVITE_TTL_SECONDS`
   (default 7 days), only works for its own workspace, and is **single-use**:
   it redeems only while the actor has no linked login. The optional `email`
   pins it to an account whose *provider-verified* email matches; without it,
   whoever holds the link first can claim the actor, so treat it like a key.
3. **Self-join (open workspaces only).** Otherwise, a fresh `writer` actor is
   created — but only if the workspace is **open** (keyless) **and**
   `ERID_ALLOW_OPEN_WORKSPACES` is on. A **secured** workspace refuses an
   uninvited account with **403**, as does any workspace in closed mode.

### Closing off open workspaces (public deployments)

"Open" is a real convenience and a real exposure. With it on (the default), the
first request naming any slug **creates** that workspace, keyless, with full
access — and `POST /workspaces/{slug}/secure` then hands its owner key to whoever
asks first. On a private box that's the zero-config flow. On anything strangers
can reach it lets them grow the `workspaces` table at will and squat slugs your
team hasn't provisioned yet.

Set **`ERID_ALLOW_OPEN_WORKSPACES=0`** to turn all of that off:

- an unknown slug returns **404** instead of being created;
- an existing keyless workspace grants **nothing** anonymously;
- `POST /{slug}/secure` returns **403** — provision with
  `POST /api/workspaces?slug=` instead, which mints a key up front.

Already have keyless workspaces from before? Claim their keys via `/secure`
while the flag is still on, then flip it off.

**Attribution.** A per-actor key or token *is* an identity, so writes made with
one are always attributed to that actor; a `created_by`/`made_by` in the request
is ignored. Shared credentials (the legacy workspace key, an open workspace)
identify no one in particular, so the claimed author is kept.

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

**Where credentials live.** The dashboard keeps its workspace list (slug +
credential type) in `localStorage`, but the credentials themselves in
`sessionStorage` — so they're scoped to the tab and gone when it closes, rather
than sitting on disk indefinitely where one XSS would harvest all of them. You
re-enter a credential in a new tab. The VS Code extension has a real keystore and
uses it (`vscode.SecretStorage`, set via **AI Context Hub: Connect**).

## REST API

Base path `/api`, workspace-scoped under `/workspaces/{slug}`:

| Method | Path                          | Auth | Purpose                          |
| ------ | ----------------------------- | ---- | -------------------------------- |
| GET    | `/health`                     | —    | liveness (no dependencies)       |
| GET    | `/ready` (no `/api` prefix)   | —    | readiness: database + event bus  |
| GET    | `/metrics` (no `/api` prefix) | token‡ | Prometheus metrics             |
| GET    | `/workspaces`                 | —    | directory (slug/name/secured; never keys) |
| POST   | `/workspaces?slug=`           | operator§ | provision + mint API key    |
| POST   | `/workspaces/{slug}/secure`   | —†   | claim an open workspace (key shown once) |
| POST   | `/workspaces/{slug}/rotate-key`| owner | rotate the workspace key        |
| DELETE | `/workspaces/{slug}`          | owner| delete the workspace (cascades)  |
| GET    | `/workspaces/{slug}/summary`  | key* | counts + open handoffs + active developers |
| GET    | `/workspaces/{slug}/search?q=`| key* | search decisions + tasks         |
| GET    | `/workspaces/{slug}/tasks`    | key* | list (filter `?status=`)         |
| POST   | `/workspaces/{slug}/tasks`    | key* | create                           |
| PUT    | `/workspaces/{slug}/tasks/{id}`| key*| update status/title/assignee     |
| DELETE | `/workspaces/{slug}/tasks/{id}`| key*| delete a task                   |
| GET    | `/workspaces/{slug}/decisions`| key* | list recent (`?limit=`)          |
| POST   | `/workspaces/{slug}/decisions`| key* | record a decision                |
| DELETE | `/workspaces/{slug}/decisions/{id}`| key*| delete a decision           |
| GET    | `/workspaces/{slug}/handoffs` | key* | list handoffs (filter `?status=`, `?limit=`) |
| POST   | `/workspaces/{slug}/handoffs` | key* | create a session handoff         |
| GET    | `/workspaces/{slug}/handoffs/{id}`| key* | fetch one handoff            |
| POST   | `/workspaces/{slug}/handoffs/{id}/acknowledge`| key* | mark picked up (open → acknowledged) |
| POST   | `/workspaces/{slug}/handoffs/{id}/resolve`| key* | mark done (→ resolved)       |
| DELETE | `/workspaces/{slug}/handoffs/{id}`| key* | delete a handoff             |
| GET    | `/workspaces/{slug}/tasks/{id}/handoffs`| key* | handoffs linked to a task |
| GET    | `/workspaces/{slug}/claims`   | key* | active file claims (`?path=` to filter) |
| POST   | `/workspaces/{slug}/claims`   | key* | claim paths/globs (TTL, exclusive/shared); returns granted + conflicts |
| POST   | `/workspaces/{slug}/claims/check`| key* | who claims these paths (for pre-commit hooks) |
| POST   | `/workspaces/{slug}/claims/release`| key* | release your claims          |
| DELETE | `/workspaces/{slug}/claims/{id}`| key* | release one claim (yours, or any as admin) |
| GET    | `/workspaces/{slug}/audit`    | admin| audit trail (`?action=`, `?limit=`, `?offset=`) |
| GET    | `/workspaces/{slug}/presence` | key* | active collaborators             |
| POST   | `/workspaces/{slug}/presence` | key* | presence heartbeat (upsert)      |
| POST   | `/workspaces/{slug}/actors`   | admin| mint per-actor key (shown once)  |
| GET    | `/workspaces/{slug}/actors`   | admin| list actors (never keys)         |
| DELETE | `/workspaces/{slug}/actors/{id}`| admin | revoke an actor                |
| POST   | `/workspaces/{slug}/actors/{id}/oauth-invite`| admin | invite a Google/GitHub login to this actor (single-use) |
| GET    | `/auth/{provider}/login?slug=[&invite=]`| — | start social login (see [admission](#social-login-google--github-admission)) |
| POST   | `/workspaces/{slug}/token`    | key* | exchange a key for a JWT         |
| WS     | `/workspaces/{slug}/ws`       | key* | real-time event stream (`?since=<seq>` to resume) |
| POST   | `/mcp` (no `/api` prefix)     | key* | MCP over Streamable HTTP (`X-Erid-Workspace`) |

\* only when the workspace has a key configured; open workspaces skip auth —
unless `ERID_ALLOW_OPEN_WORKSPACES=0`, which makes an unknown slug 404 and a
keyless workspace inaccessible rather than open.
† unauthenticated by design (an open workspace has no admin to gate on), and
disabled entirely when `ERID_ALLOW_OPEN_WORKSPACES=0`.
‡ open unless `ERID_METRICS_TOKEN` is set (then `Authorization: Bearer <token>`).
§ open unless `ERID_ADMIN_TOKEN` is set (then `X-Admin-Token: <token>`).
Auth-sensitive routes are rate-limited per client IP across replicas, and all
routes per credential; see [`docs/production.md`](docs/production.md).
`admin` requires the `admin_keys` permission (owner or a granted admin). Each
route enforces a specific permission (`read`/`write_tasks`/`write_decisions`/
`presence`); a key/token must carry it.

## Real-time events

Mutations publish events (`task_created`, `task_updated`, `task_deleted`,
`decision_created`, `handoff_created`, `handoff_updated`, `presence_updated`, …)
onto the workspace's stream. Each frame is
`{"workspace", "type", "data", "ts", "seq"}`.

**Transactional outbox** (`api/app/services/events.py`). A service writes the
event to the `events` table in the *same transaction* as the change, so an event
exists exactly when its change committed. The row's id is the event's `seq`.
Presence heartbeats are live-only (no `seq`): storing them would fill the outbox
for no benefit. Rows are pruned after `ERID_EVENT_RETENTION_HOURS` (default 72).

**Fan-out** (`api/app/services/event_bus.py`). On Postgres, producers call
`pg_notify` inside that transaction, and Postgres delivers it only on commit, to
every API instance's `LISTEN` connection. So there's no publish-after-commit
window to lose an event in, and no extra broker. Events too large for a
notification travel by reference and are loaded from the outbox. With SQLite
(tests) the bus is in-process. Override with `EVENT_BUS_BACKEND=postgres|memory`.

**Resuming.** Clients remember the highest `seq` they've seen and reconnect with
`/ws?since=<seq>`: the server replays what they missed, then streams live. If it
can't (more than 500 events behind, or the gap was pruned) it sends
`{"type": "resync_required"}` first and the client reloads over REST. The
dashboard does this; it only falls back to a full reload when it has no `seq` yet.

## Testing

```bash
uv run pytest            # API routes + WebSocket + MCP tool round-trip

# The same suite against Postgres (schema built by the real Alembic migrations;
# also runs the LISTEN/NOTIFY bus and migration tests that SQLite skips):
ERID_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/erid_test \
  uv run pytest
```

By default `tests/` runs the app against an isolated in-memory SQLite DB (no
Postgres needed); CI runs it on both. Beyond unit and integration tests the
suite fuzzes every REST operation and MCP tool with hostile input (no 5xx
allowed), checks properties with Hypothesis, verifies the migrations against
the models, and on Postgres boots three real API processes to test
cross-replica fan-out, shared rate limits, claim races and recovery from lost
LISTEN connections. `scripts/loadtest.py` load-tests one or more instances;
results are in [`docs/production.md`](docs/production.md#testing). `tests/test_contract.py` fails if
`api/openapi.json` is stale or if `mcp-server/src/client.py` / `web/src/api.js`
call a route the API doesn't serve. `mcp-server/tests/`
boots a real API subprocess and drives the MCP client end-to-end; set
`ERID_LIVE_API` to target an already-running server instead.

## Configuration

Environment variables (see `api/app/core/settings.py`, `mcp-server/src/client.py`):

| Var                 | Default                                            | Used by   |
| ------------------- | -------------------------------------------------- | --------- |
| `DATABASE_URL`      | `postgresql+asyncpg://postgres:postgres@localhost:5432/erid` | api |
| `EVENT_BUS_BACKEND` | `auto`: `postgres` (LISTEN/NOTIFY) on Postgres, else `memory` | api |
| `ERID_EVENT_RETENTION_HOURS` | `72` — how long `/ws?since=` can replay | api |
| `CORS_ORIGINS`      | `http://localhost:5173,http://localhost:8000`      | api       |
| `ERID_ALLOW_OPEN_WORKSPACES` | `1` — set `0` on public deployments (see [Authentication](#closing-off-open-workspaces-public-deployments)) | api |
| `ERID_ENV`          | `development` — `production` refuses unsafe settings | api |
| `ERID_RATE_LIMIT_AUTH` / `_AUTH_FAILURES` / `_API` | `30/minute` / `20/minute` / `1200/minute` | api |
| `ERID_SECRET_SCANNING` | `redact` (`reject`, `off`)                      | api       |
| `ERID_MAX_INFLIGHT_REQUESTS` / `ERID_MAX_WEBSOCKETS` | `256` / `2000` per replica | api |
| `ERID_DB_POOL_SIZE` / `ERID_DB_MAX_OVERFLOW` | `10` / `10` per replica   | api       |

Every production setting (PgBouncer, metrics token, body limit, docs,
migrations, audit retention) is listed in [`docs/production.md`](docs/production.md)
and `.env.example`.
| `API_BASE`          | `http://localhost:8000`                            | mcp-server|
| `WORKSPACE_SLUG`    | —                                                  | mcp-server|
| `WORKSPACE_API_KEY` | —                                                  | mcp-server|

Docker Compose injects `DATABASE_URL` pointing at the container host; the
defaults target a local Postgres for native dev.

## Roadmap

Done (this iteration):

- [x] REST API for tasks / decisions / presence + summary + search
- [x] All 9 MCP tools wired end-to-end and config for Claude/Cursor/Codex
- [x] Event bus + WebSocket stream (now Postgres LISTEN/NOTIFY with a transactional outbox; Redis removed)
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
- [x] Dashboard auth flow (per-workspace key/token) + workspace switcher + quick task-create form
- [x] Test sweep: WS-auth happy/negative, non-decision event payloads, edge cases, MCP client error paths (90 tests)
- [x] Codex CLI config (`clients/codex.toml`); empty `mcp-server/src/tools/` stubs removed
- [x] OAuth providers (Google + GitHub social login, `ERID_OAUTH_*`/`ERID_SESSION_SECRET` plumbing)
- [x] Multi-instance MCP resources
- [x] Dashboard decision-create UI
- [x] Deploy/CI verification of the compose stack (healthchecked `docker-compose.yml`, `infra/deploy.sh`, `compose-verify` job)
- [x] **Session handoffs** — durable `handoffs` resource (summary, files changed, commands run, blockers, next action, branch/task/recipient links) with an `open → acknowledged → resolved` lifecycle, REST CRUD + lifecycle endpoints, `write_handoffs` permission, `handoff_created/updated/deleted` WS events, MCP tools (`create_handoff`, `recent_handoffs`, `acknowledge_handoff`, `resolve_handoff`), a `workspace://{slug}/handoffs` resource, a `catch_up` prompt that briefs on open handoffs, dashboard list/create/pick-up/resolve UI, and `open_handoff_count` in the workspace summary.

- [x] **Architecture consolidation** — service layer shared by REST and MCP; MCP served in-process at `/mcp`; transactional event outbox with `seq` and `/ws?since=` replay; Redis replaced by Postgres `LISTEN/NOTIFY`; hashed workspace keys; actor-bound attribution; test suite runs on Postgres in CI; OpenAPI contract checks for the hand-written clients.

- [x] **Production readiness** — horizontal scaling (advisory-locked
  migrations, readiness/metrics, load shedding, graceful drain, PgBouncer
  support), Kubernetes HPA manifests and Compose replicas, rate limits and
  brute-force lockout shared across replicas, audit trail, production config
  gate, security headers, Origin checks, log redaction, file claims, secret
  scanning, and fuzz/property/multi-process/load testing that found and fixed
  nine bugs. See [`docs/production.md`](docs/production.md).

All roadmap items complete.

### Recently closed gaps

These were open items tracked here; all are now done:

- [x] **Dashboard full mutations** — `web/src/api.js` has `put`/`del` (204-tolerant
  `request`) plus `updateTask`/`deleteTask`/`deleteDecision`; TaskList rows get a
  status select + delete and DecisionList a delete, all optimistic with rollback.
- [x] **Dashboard WebSocket resilience** — `web/src/useWorkspace.js` reconnects
  with exponential backoff (resyncing REST once per reconnect), applies events
  locally, refreshes only the summary on a trailing debounce (no more 4-collection
  reload per frame), and handles `task_deleted` / `decision_deleted` /
  `workspace_deleted` and the server's `ping` keepalive.
- [x] **MCP delete tools + shared client** — `server.py` registers `delete_task` /
  `delete_decision` and every tool/resource shares one process-wide `APIClient`
  (HTTP connection pooling) instead of a new `httpx.AsyncClient` per call.
  (secure / rotate-key / actor-management tools remain a possible follow-up.)
- [x] **JS/TS tests in CI** — the `web` job runs vitest (`npm test`) after the
  build, a `vscode-extension` job type-checks (`tsc --noEmit`) and compiles the
  extension, and a `jetbrains-plugin` job compiles the plugin.
- [x] **JetBrains plugin** — `editors/jetbrains/` drives the same
  `mcp-server/src/bridge.py` JSON-RPC protocol as the VS Code extension (minimal
  tool-window UI; see its README).
- [x] **API hardening & perf** — the `/ws` stream sends an app-level `ping`
  keepalive so dead clients drop instead of blocking forever, the SQLite search
  fallback escapes LIKE wildcards, and `/summary` aggregates counts in SQL.

Check out [Research Paper](https://drive.google.com/file/d/1gFSSAxbWy4txFI136YwJRoDZ-aqFqWOf/view?usp=sharing "Research Paper").

