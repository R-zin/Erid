# AI Context Hub — Client Setup

Point your AI tool's MCP config at `mcp-server/src/server.py`. The server reads
its config from environment variables:

- `API_BASE` — REST API base URL (default `http://localhost:8000`)
- `WORKSPACE_SLUG` — default workspace so tools don't need a slug each call
- `WORKSPACE_API_KEY` — API key if the workspace is secured

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
