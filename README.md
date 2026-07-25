# AI Context Hub

**Git for AI context.** A shared, real-time memory layer for every AI coding assistant on your team — Claude Code, Cursor, Codex CLI, and anything else that speaks MCP.

Instead of re-explaining your architecture to a fresh AI conversation every session, connected assistants can query a shared context graph: who's working on what, what's been decided, what's still open, and why.

---

## The problem

Every AI coding session starts from zero. Switch from Claude Code to Cursor, or open a new conversation, and you're re-explaining the same architecture decisions, the same "why we use Redis here," the same list of open tasks — every single time. Meanwhile a teammate's AI assistant has no idea what your AI assistant just figured out five minutes ago.

## What this does

AI Context Hub sits between your AI tools and a shared context server. Any connected assistant can:

- See who (human or AI) is currently working on what, and in which file
- Pull a full workspace summary — active developers, open tasks, recent decisions — in one call
- Record an architecture/implementation decision so it's never re-litigated or contradicted later
- Search past decisions and tasks instead of asking you to re-explain
- Create and update shared tasks that sync instantly across every connected client

It works the same way regardless of which AI tool is asking, because every client talks to the same MCP server over the same protocol.

---

## Architecture

```
Claude Code / Cursor / Codex CLI   (one MCP connection per developer, over stdio)
              │
              ▼
       mcp-server              stateless — translates MCP tool calls into HTTP calls
              │
              ▼
       api (FastAPI)           owns all state: workspaces, tasks, decisions, presence
              │
   ┌──────────┴──────────┐
   ▼                     ▼
PostgreSQL          Event bus (WebSocket)
                    in-process for MVP, swappable for Redis pub/sub to scale
```

- **`mcp-server/`** — The MCP server every AI client connects to. Exposes tools like `workspace_summary`, `search_context`, `create_decision`, `current_tasks`, and `active_developers`. Holds no state itself; every call is a thin HTTP request to `api/`. This is what makes it work identically across Claude Code, Cursor, and Codex — they all just spawn/connect to this one server.
- **`api/`** — FastAPI backend. Owns workspaces, tasks, decisions, and presence in Postgres, and pushes real-time updates over a WebSocket.
- **`clients/`** — Ready-to-use MCP configs for Claude Code, Cursor, and Codex CLI, plus setup instructions.
- **`web/`** — Dashboard frontend (not built yet — the API/WebSocket layer is ready for one).

---

## Quickstart

**1. Start the backend**

```bash
docker compose up -d postgres redis api
```

API docs (interactive, via Swagger) are then live at `http://localhost:8000/docs`.

**2. Connect your AI client**

See [`clients/README.md`](clients/README.md) for Claude Code, Cursor, and Codex CLI setup — each just needs a few lines added to a config file pointing at `mcp-server/src/server.py`.

**3. Try it**

Ask your AI assistant something like:

> What's the current state of this workspace?

It should call `workspace_summary` and answer from real, shared project state instead of asking you to explain the project from scratch.

---

## Example: what a shared decision looks like

Instead of losing this in 500 lines of chat history, `create_decision` stores it as structured data every connected assistant can retrieve later:

```json
{
  "title": "Introduce ProviderFactory",
  "reason": "Reduce duplicated provider initialization",
  "related_files": ["provider.py", "factory.py", "config.py"],
  "made_by": "Claude Code"
}
```

Any assistant — in any tool — can later call `search_context("provider")` or `recent_decisions()` and get this back, instead of rediscovering or contradicting it.

---

## Tech stack

| Layer          | Choice                                   |
|----------------|-------------------------------------------|
| MCP server     | Python, official `mcp` SDK (FastMCP)      |
| Backend API    | FastAPI, async SQLAlchemy                 |
| Database       | PostgreSQL                                |
| Real-time      | WebSocket (in-process event bus; Redis pub/sub-ready) |
| Deployment     | Docker / Docker Compose                   |

---

## 
---

## Local development (without Docker)

```bash
# API
cd api
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# point DATABASE_URL at a local Postgres instance, then:
uvicorn app.main:app --reload

# MCP server
cd mcp-server
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 src/server.py --transport stdio
```

## Project structure

```
ai-context-hub/
├── api/                  FastAPI backend
│   └── app/
│       ├── models/       SQLAlchemy models (Workspace, Task, Decision, Presence)
│       ├── schemas/      Pydantic request/response schemas
│       ├── services/     event bus, workspace resolution
│       └── api/          REST routes + WebSocket gateway
├── mcp-server/           MCP server exposed to AI clients
│   └── src/
│       ├── tools/        one module per tool group (tasks, decisions, presence, context)
│       ├── client.py     HTTP client to the api/ backend
│       └── server.py     entrypoint (stdio / sse / streamable-http)
├── clients/              example MCP configs per AI tool
├── web/                  dashboard frontend (planned)
├── infra/                deployment configs
└── docker-compose.yml
```
