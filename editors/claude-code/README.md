# AI Context Hub — Claude Code plugin

A Claude Code plugin that brings the hub into the CLI. It bundles the hub's **MCP server**
(shared tasks / decisions / presence) and a set of **`/hub:*` slash commands** that drive it, so
your Claude Code sessions read from and write to the same project state as Cursor, Codex, and the
web dashboard. This is the Claude Code counterpart to the VS Code/Cursor extension in
[`../vscode`](../vscode) — in a terminal there's no sidebar, so the surface is MCP + commands.

> **In-repo, project-scoped.** The plugin's MCP config points at this repo's
> `mcp-server/src/server.py` via `${CLAUDE_PROJECT_DIR}` (the directory you launched `claude`
> from). It works from any clone of this repo, but is not a portable/marketplace bundle — the
> server code is referenced, not vendored.

## What's inside

```
editors/claude-code/
├── .claude-plugin/plugin.json   # plugin manifest (name: context-hub)
├── .mcp.json                    # launches the hub MCP server over stdio
├── commands/                    # /hub:* slash commands
└── README.md
```

## Install

The plugin lives in the repo (project-scoped). From a Claude Code session started at the repo
root:

```
/plugin install ./editors/claude-code
```

…or pick it up via the repo marketplace (`.` is the repo root, which has
`.claude-plugin/marketplace.json`):

```
/plugin marketplace add .
/plugin install context-hub@erid
```

Plugins written into the repo load after the same trust gate as `.claude/settings.json`, and the
bundled MCP server goes through the normal per-server approval. Run `/reload-plugins` (or restart)
after pulling changes to `.mcp.json`.

## Configure

The server reads its config from environment variables (see [`../../clients/README.md`](../../clients/README.md)).
The `.mcp.json` interpolation means your **real** shell env supplies the values — export them
before launching `claude` (nothing is committed):

| Var                 | What                                          | Default                |
| ------------------- | --------------------------------------------- | ---------------------- |
| `API_BASE`          | Hub REST API base URL                         | `http://localhost:8000` |
| `WORKSPACE_SLUG`    | Default workspace so commands need no slug    | *(required)*           |
| `WORKSPACE_API_KEY` | Workspace / per-actor key (secured workspace) | *(empty = open)*       |
| `WORKSPACE_TOKEN`   | Optional JWT (takes precedence over the key)  | *(empty)*              |

```bash
export WORKSPACE_SLUG=your-workspace
export WORKSPACE_API_KEY=...     # only if the workspace is secured
```

Requires [`uv`](https://astral.sh/uv) on PATH and the hub API running
(`docker compose up -d postgres redis api`).

## Commands

| Command                | What it does                                                        |
| ---------------------- | ------------------------------------------------------------------- |
| `/hub:summary`         | Workspace health: open vs. done tasks, recent decisions, activity.   |
| `/hub:tasks [status]`  | List tasks (optionally filtered by `todo`/`in_progress`/`done`/`blocked`). |
| `/hub:decisions [n]`   | Most recent decisions.                                              |
| `/hub:task-create`     | Create a task (title, optional assignee).                           |
| `/hub:task-update`     | Update a task's status / title / assignee.                          |
| `/hub:decision-record` | Record a decision (pre-fills `related_files` from the active file). |
| `/hub:search <query>`  | Full-text search over decisions + tasks.                            |
| `/hub:presence`        | Who's working on what right now.                                    |
| `/hub:catch-up`        | Brief a fresh session on the whole workspace.                       |

The MCP server also exposes the read-only `workspace://{slug}/{summary,tasks,decisions,presence}`
resources and the `summarize_workspace` / `standup_report` / `catch_up` prompts.

## The rest of the family

| Tool        | Surface                                                        |
| ----------- | -------------------------------------------------------------- |
| Claude Code | This plugin (MCP + `/hub:*` commands).                         |
| Cursor      | The [`../vscode`](../vscode) extension, installed as a `.vsix`. |
| Codex CLI   | MCP config only — [`../../clients/codex.toml`](../../clients/codex.toml). |
