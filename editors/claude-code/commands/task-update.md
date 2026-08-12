---
name: hub:task-update
description: Update a task's status, title, or assignee.
argument-hint: "<task-id> [status|title|assignee value]"
---

The first token of $ARGUMENTS is the task id. Determine which fields to change from the rest
(status / title / assignee); if it's ambiguous, ask. Call the context-hub `update_task` tool with
the task id and the field updates, then confirm the new state.
