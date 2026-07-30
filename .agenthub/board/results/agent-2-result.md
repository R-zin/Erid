# agent-2 result (infra / MCP / config)

Worktree: `/Users/razinm/PycharmProjects/Erid/.claude/worktrees/agent-a9cf4b850adbd1ed4`
Branch: `worktree-agent-a9cf4b850adbd1ed4`. Baseline was 38 passed → final 46 passed (38 + 8 new).

## #6 MCP resources + prompts — ✅

- `mcp-server/src/server.py`: 4 resources + 3 prompts added; all 10 existing tools untouched (verified 10 tools
  registered post-change).
- Resources (`@mcp.resource`, JSON mime): `workspace://{slug}/summary`, `workspace://{slug}/tasks`,
  `workspace://{slug}/decisions`, `workspace://{slug}/presence`.
- Prompts (`@mcp.prompt`): `summarize_workspace`, `standup_report`, `catch_up` (agent-that-just-joined briefing).
- REGISTRATION CHECK: `mcp._resource_manager._templates` shows the 4 URIs; `_prompt_manager._prompts` the 3 names;
  `_tool_manager._tools` still 10.
- No new REST calls needed in `client.py` — resources reuse the existing auth-aware `APIClient` methods
  (`workspace_summary`, `current_tasks`, `recent_decisions`, `active_developers`).
- Commit `f7cc18f`.

## #10 CORS + scoped search/summary — ✅ (with explicit coordinator action required)

- CORS (`api/app/main.py`): replaced invalid `allow_origins=["*"] + allow_credentials=True` with
  `allow_origins=settings.cors_origins` + `allow_credentials=True`. Resolution: keep credentials, enumerate
  origins (wildcard+credentials is invalid per CORS spec).
- `api/app/core/settings.py`: new `cors_origins` list, env `CORS_ORIGINS` (comma-separated), default
  `["http://localhost:5173","http://localhost:8000"]`.
- `api/app/api/routes/context_misc.py` (new): secured copies of `/search` + `/summary`, copied handler-for-handler
  from `context.py`, both behind `Depends(require_action(Permission.read))` using `principal.workspace` (NOT
  `get_or_create_workspace`). FTS/SQLite branches unchanged; reuses `STALE_AFTER`/`_search_vector` from context.py.
- `main.py`: `context.router` included first, `context_misc.router` AFTER (deterministic ordering as instructed).
- **DUPLICATION EXISTS — coordinator action required**: both routers currently register
  `/workspaces/{slug}/search` and `/workspaces/{slug}/summary` (open handlers in `context.py`, secured in
  `context_misc.py`). Starlette matches in registration order, so the OPEN handlers in `context.py` take runtime
  precedence until the coordinator deletes them. Startup unaffected (verified import; "Duplicate Operation ID"
  warnings in OpenAPI only). My tests therefore mount `context_misc.router` in isolation to prove the secured
  behavior.
- Tests (`tests/test_sec_search_agent2.py`, 8 tests): open ws → 200 anon; secured no-creds → 401; bad creds → 403;
  valid owner key → 200; reader-role actor key → 200; seeded-data search/summary; CORS origins not wildcard;
  preflight from :5173 echoed with credentials, evil origin excluded.
- Commit `0df6fdc`.

## #12 web Dockerfile + compose — ✅ (statically validated; runtime NOT verifiable)

- `web/Dockerfile` (new): two stages — `node:22-alpine` build (`npm ci` from lockfile → `npm run build` → dist)
  → `nginx:1.27-alpine` serving `dist` from `/usr/share/nginx/html`, proxying `/api/` (REST + WS) to
  `http://api:8000`. `EXPOSE 80`.
- `web/.dockerignore` (new): node_modules, dist, .vite, env, docker self-files.
- **DEVIATION**: created two additional non-exclusive files `web/nginx.conf` (server block) and
  `web/nginx.websocket.conf` (http-context `map $http_upgrade $connection_upgrade`) — the Dockerfile is broken
  without them; flagged here and in the commit message.
- `docker-compose.yml`: dropped obsolete top-level `version:`; added explicit `REDIS_URL: redis://redis:6379/0`
  for api; `CORS_ORIGINS: http://localhost:8080` (web origin); mcp env contract
  `API_BASE/WORKSPACE_SLUG/WORKSPACE_API_KEY/WORKSPACE_TOKEN` (host-env with defaults); added `web` service
  (build `./web`, `8080:80`, depends_on api).
- VALIDATION (static only — **docker CLI unavailable, no `docker build` possible**): compose YAML parsed &→
  asserted (5 services, no version key, env contracts); Dockerfile stages asserted (node first, nginx serve,
  `AS build`, `COPY --from=build`, `EXPOSE 80`); nginx directives asserted (proxy target, WS map in http context,
  `try_files` SPA fallback). Runtime build/boot NOT verified.
- Commit `017ebab`.

## #13 Codex config + cleanup — ✅

- `clients/codex.toml` (new): TOML MCP config (`[mcp_servers.context-hub]` command/args/env), mirrors
  claude_code.json/cursor.yaml; parse-validated with tomllib.
- Deleted 4 zero-byte stubs `mcp-server/src/tools/{context,decisions,presence,tasks}.py` after confirming 0 bytes
  and ZERO importers anywhere in the repo; removed empty `tools/` dir (nothing tracked under it now).
- `clients/README.md`: Codex section now points at codex.toml; tools/resources/prompts listed.
- Root `README.md` (my sections only): resources/prompts added to the tools paragraph; `web` compose quick-start;
  `CORS_ORIGINS` config row; search/summary table rows `open`→`key*`; roadmap updated.
- Commits `81f1d32` (stubs) + `a664687` (codex.toml + READMEs — second commit because the first `git add` aborted
  on the deleted tools/ pathspec).

## Gates

- `uv run ruff check api/ mcp-server/` → **All checks passed!** (`ruff format` clean on my files.)
- `uv run pytest -q` → **46 passed, 2 warnings in ~6.7s** (warnings = expected Duplicate Operation ID from the
  intentional search/summary duplication; no failures, no regressions vs 38 baseline).
- Commits: `f7cc18f` (#6), `0df6fdc` (#10), `017ebab` (#12), `81f1d32` + `a664687` (#13).

## For the coordinator

1. DELETE the open `/search` & `/summary` handlers from `api/app/api/routes/context.py` — duplication is
   intentional per the split; secured versions live in `context_misc.py`.
2. web/nginx.conf + web/nginx.websocket.conf exist despite not being on my exclusive list (Dockerfile needs them).
3. Docker images were never built — environment had no docker CLI; verify `docker compose up` on a machine with
   docker before merging #12.
