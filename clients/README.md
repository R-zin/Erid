# AI Context Hub — Client Setup

Point your AI tool at `mcp-server/src/server.py`.

## Claude Code
Add to `.claude/settings.json` or `claude_desktop_config.json`:
```json
{"mcpServers":{"ai-context-hub":{"command":"python3","args":["mcp-server/src/server.py","--transport","stdio"]}}}
```

## Cursor
In Cursor MCP settings, add command: `python3 mcp-server/src/server.py --transport stdio`

## Codex CLI
In `codex` config, set the same stdio command pointing at `mcp-server/src/server.py`.
