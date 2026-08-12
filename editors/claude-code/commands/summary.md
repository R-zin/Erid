---
name: hub:summary
description: Show a live summary of the shared AI Context Hub workspace (task/decision counts and who's active).
---

Call the context-hub `workspace_summary` tool for the workspace. If it returns counts, also call
`current_tasks` and `recent_decisions` for extra color. Then write a concise summary: overall
health, open vs. done tasks, what was decided recently, and anything that looks blocked or stale.

Pass a different workspace slug only if the user supplies one ($ARGUMENTS); otherwise rely on the
server's configured default `WORKSPACE_SLUG`.
