# Changelog

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
