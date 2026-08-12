---
name: hub:task-create
description: Create a task in the shared workspace so every tool can see it.
argument-hint: "<title> [assignee]"
---

Ask for the task title if it isn't in $ARGUMENTS (the first token is the title; an optional second
token is the assignee). Then call the context-hub `create_task` tool with that title (and `assigned_to`
if an assignee was given), and `created_by` set to the current developer. Confirm the created task id.
