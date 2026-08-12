---
name: hub:tasks
description: List tasks in the shared workspace, optionally filtered by status (todo, in_progress, done, blocked).
argument-hint: "[todo|in_progress|done|blocked]"
---

Call the context-hub `current_tasks` tool. If the user passed a status ($ARGUMENTS), filter on it.
Render the result as a list grouped by status with each task's id, title, and assignee, and note
anything blocked or unassigned.
