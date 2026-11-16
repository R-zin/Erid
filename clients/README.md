# Erid — Client Setup

The API serves MCP over **Streamable HTTP at `/mcp`**, so an AI tool connects
by URL with nothing installed locally. Two headers configure it:

- `X-Erid-Workspace` — default workspace so tools don't need a slug each call
  (or append `?workspace=<slug>` to the URL)
- `X-API-Key: <key>` or `Authorization: Bearer <jwt>` — only for a secured workspace

Every tool enforces the same permission as the matching REST route, and writes
made with a per-actor key are attributed to that actor.

**stdio alternative.** For a client that can only launch a local process,
`mcp-server/src/server.py` exposes the identical tool set over REST. It reads
`API_BASE`, `WORKSPACE_SLUG`, `WORKSPACE_API_KEY`, and `WORKSPACE_TOKEN` from the
environment; the stdio snippets below show it.

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
claude mcp add --transport http erid http://localhost:8000/mcp \
  --header "X-Erid-Workspace: your-workspace" \
  --header "X-API-Key: $ERID_API_KEY"
```

Or merge `clients/claude_code.json` into your settings. stdio alternative:

```bash
claude mcp add context-hub \
  --env API_BASE=http://localhost:8000 \
  --env WORKSPACE_SLUG=your-workspace \
  -- uv run python mcp-server/src/server.py --transport stdio
```

**In-repo plugin (alternative).** Instead of the global server above, you can install the
bundled plugin from [`editors/claude-code/`](../editors/claude-code) — it registers this same
MCP server *and* adds `/hub:*` slash commands (`/hub:summary`, `/hub:catch-up`, …). It's
project-scoped to this repo:

```bash
# from a Claude Code session started at the repo root
/plugin install ./editors/claude-code      # or: /plugin marketplace add . && /plugin install context-hub@erid
```

Use one or the other (the global server for every project, the plugin for command shortcuts in
this repo).

## Cursor

Add the server from `clients/cursor.yaml` (URL + headers). stdio alternative:

```
uv run python mcp-server/src/server.py --transport stdio
```

Cursor reads MCP config from `.cursor/mcp.json` (project) or `~/.cursor/mcp.json`
(global), top-level key `mcpServers` — same inner shape as `claude_code.json`.

## VS Code

VS Code reads workspace MCP servers from `.vscode/mcp.json`, top-level key
`servers` (note: **`servers`**, not `mcpServers`). Over HTTP, with the key
prompted for rather than stored in the file:

```json
{
  "inputs": [{ "id": "erid-key", "type": "promptString", "description": "Erid API key", "password": true }],
  "servers": {
    "erid": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": { "X-Erid-Workspace": "your-workspace", "X-API-Key": "${input:erid-key}" }
    }
  }
}
```

stdio alternative:

```json
{
  "servers": {
    "context-hub": {
      "command": "uv",
      "args": ["run", "python", "mcp-server/src/server.py", "--transport", "stdio"],
      "env": {
        "API_BASE": "http://localhost:8000",
        "WORKSPACE_SLUG": "your-workspace",
        "WORKSPACE_API_KEY": "",
        "WORKSPACE_TOKEN": ""
      }
    }
  }
}
```

The VS Code extension (`editors/vscode/`) writes this for you via the
`AI Context Hub: Setup MCP` command (merging existing servers, leaving the secret
values blank for you to fill in).

## Codex CLI

Codex CLI has no plugin/extension UI — its only integration surface is MCP
config, so this is the whole "extension" for Codex. Merge `clients/codex.toml`
into your Codex config (`~/.codex/config.toml`). It points Codex at the `/mcp`
URL and reads the key from the `ERID_API_KEY` environment variable:

```toml
[mcp_servers.erid]
url = "http://localhost:8000/mcp"
http_headers = { "X-Erid-Workspace" = "your-workspace" }
env_http_headers = { "X-API-Key" = "ERID_API_KEY" }
```

stdio alternative (run Codex from the repo root so the relative path resolves):

```toml
[mcp_servers.context-hub]
command = "uv"
args = ["run", "python", "mcp-server/src/server.py", "--transport", "stdio"]

[mcp_servers.context-hub.env]
API_BASE = "http://localhost:8000"
WORKSPACE_SLUG = "your-workspace"
WORKSPACE_API_KEY = ""
WORKSPACE_TOKEN = ""
```

Once connected, the tools `workspace_summary`, `search_context`,
`current_tasks`, `create_task`, `update_task`, `delete_task`, `create_decision`,
`delete_decision`, `task_decisions`, `recent_decisions`, `active_developers`,
`update_presence`, `list_workspaces`, `create_handoff`, `recent_handoffs`,
`acknowledge_handoff`, and `resolve_handoff` are available, plus read-only
resources (`workspace://index`, `workspace://{slug}/summary`, `.../tasks`,
`.../decisions`, `.../handoffs`, `.../presence`) and the prompts
`summarize_workspace`, `standup_report`, and `catch_up`.
