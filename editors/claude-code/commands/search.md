---
name: hub:search
description: Search the shared workspace's decisions and tasks by free-text query.
argument-hint: "<query>"
---

Call the context-hub `search_context` tool with $ARGUMENTS as the query (ask for it if missing).
Summarize the matching decisions and tasks, highlighting anything already decided that the user
might otherwise re-decide.
