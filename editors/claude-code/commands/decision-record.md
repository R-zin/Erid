---
name: hub:decision-record
description: Record an architectural/implementation decision so every tool can see it.
argument-hint: "<title> [reason]"
---

Call the context-hub `create_decision` tool. Take the title (and optional reason) from $ARGUMENTS,
asking for anything missing. Pre-fill `related_files` with the file currently being edited/discussed
and `made_by` with the current developer. If the decision relates to an open task, offer to link it
via `task_id`. Confirm the recorded decision id.
