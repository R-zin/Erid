# AI Context Hub — Client Setup

Point your AI tool's MCP config at `mcp-server/src/server.py`. The server reads
its config from environment variables:

- `API_BASE` — REST API base URL (default `http://localhost:8000`)
- `WORKSPACE_SLUG` — default workspace so tools don't need a slug each call
- `WORKSPACE_API_KEY` — workspace or per-actor API key if the workspace is secured
- `WORKSPACE_TOKEN` — optional JWT access token (takes precedence over the key)

## Authentication

A workspace can be **open** (no key) or **secured**. For a secured workspace you
authenticate with either a **workspace key**, a **per-actor key**, or a **JWT**
minted from one. Per-actor keys carry fine-grained permissions (read, write
tasks, write decisions, presence, admin) so collaborators and bots can be scoped.

```bash
# Mint an actor (needs an owner/admin key); raw key shown once
curl -s -XPOST -H "X-API-Key: $OWNER_KEY" \
  -H 'Content-Type: application/json' \
  'http://localhost:8000/api/workspaces/myproj/actors' \
  -d '{"name":"claude","role":"writer"}' | jq -r .api_key    # ACTOR_KEY

# Exchange a key for a short-lived JWT
curl -s -XPOST -H 'Content-Type: application/json' \
  'http://localhost:8000/api/workspaces/myproj/token' \
  -d "{\"api_key\":\"$ACTOR_KEY\"}" | jq -r .access_token    # WORKSPACE_TOKEN
```

Set `WORKSPACE_API_KEY=$ACTOR_KEY` (long-lived) or `WORKSPACE_TOKEN=...`
(short-lived, preferred for shared/ephemeral setups) in the configs below.

## Claude Code

```bash
claude mcp add context-hub \
  --env API_BASE=http://localhost:8000 \
  --env WORKSPACE_SLUG=your-workspace \
  -- uv run python mcp-server/src/server.py --transport stdio
```

Or merge `clients/claude_code.json` into your settings.

## Cursor

In Cursor MCP settings, add the command from `clients/cursor.yaml`:

```
uv run python mcp-server/src/server.py --transport stdio
```

## Codex CLI

In the `codex` config, set the same stdio command pointing at
`mcp-server/src/server.py`.

Once connected, the tools `workspace_summary`, `search_context`,
`current_tasks`, `create_task`, `update_task`, `create_decision`,
`recent_decisions`, `active_developers`, and `update_presence` are available.
