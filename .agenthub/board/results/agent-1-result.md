# agent-1 (backend-api) — Results

Worktree: `/Users/razinm/PycharmProjects/Erid/.claude/worktrees/agent-ac6e3e72e73185f4e`
Branch: `worktree-agent-ac6e3e72e73185f4e`

## Task #7 — DB indexes + presence upsert — DONE ✅

- Unique constraint `uq_presence_workspace_actor` on `presence (workspace_id, actor_name)`
  → `api/app/models/models.py` (`Presence.__table_args__`), + migration.
- `update_presence` rewritten as a true atomic `INSERT ... ON CONFLICT (workspace_id, actor_name)
  DO UPDATE`, dialect-selected (`pg_insert` vs `sqlite_insert`) → `api/app/api/routes/context.py`
  (`update_presence`, ~line 475).
- `decisions.made_by` index and `tasks.assigned_to` index via `index=True` on the two columns
  → `api/app/models/models.py`.

## Task #8 — DELETE endpoints — DONE ✅

| Endpoint | Method | Permission | Notes |
|---|---|---|---|
| `/workspaces/{slug}/tasks/{task_id}` | DELETE | `write_tasks` | 204 / 404 |
| `/workspaces/{slug}/decisions/{decision_id}` | DELETE | `write_decisions` | 204 / 404 |
| `/workspaces/{slug}` | DELETE | `owner` | 204; cascades |

Locations: `api/app/api/routes/context.py` — `delete_task` (~348), `delete_decision` (~436),
`delete_workspace` (~109).

**Cascade behavior (decision):** workspace deletion cascades via the ORM
`cascade="all, delete-orphan"` on `Workspace.tasks/decisions/presences/actors`. These four FKs
carry `ondelete="CASCADE"` too, but SQLite tests never enable `PRAGMA foreign_keys`, so the ORM
`delete-orphan` is the actual mechanism (the ORM loads and bulk-deletes children); `actor_grants`
has no workspace relationship so it relies on its own `ON DELETE CASCADE` from `actor_id` (and the
test uses no grants-bearing actors, avoiding the SQLite FK-off edge). Deleting a **task** SET NULLs
`decisions.task_id` (decision kept) — verified by test.

## Task #9 — Workspace management — DONE ✅

| Endpoint | Method | Auth | Notes |
|---|---|---|---|
| `/workspaces` | GET | **public (none)** | directory of slugs/names + `secured` flag |
| `/workspaces/{slug}/secure` | POST | **open (none)** | claim an OPEN workspace; key shown once |
| `/workspaces/{slug}/rotate-key` | POST | `owner` | regenerates key; old key stops working |

Locations: `api/app/api/routes/context.py` — `list_workspaces` (~127), `secure_workspace` (~143),
`rotate_workspace_key` (~163). Schemas: `WorkspaceListItem`, `WorkspaceSecured`,
`WorkspaceKeyRotated` in `api/app/schemas/schemas.py`.

## Migration

- Revision id: **`2c3bc1c08eea`**, `down_revision = "b8c9d0e1f2a3"`.
- File: `api/migrations/versions/2c3bc1c08eea_presence_unique_and_lookup_indexes.py`.
- Does: (1) dedupe existing presence rows per `(workspace_id, actor_name)` so the constraint can be
  created cleanly; (2) add `uq_presence_workspace_actor` (via `batch_alter_table` for SQLite
  copy-and-move, plain `ALTER TABLE` on PG); (3) `CREATE INDEX ix_decisions_made_by`,
  `CREATE INDEX ix_tasks_assigned_to`. Portable across both dialects — no Postgres-only DDL, so no
  dialect gate needed.
- Validated: offline SQL render on the PG dialect produces exactly
  `ALTER TABLE presence ADD CONSTRAINT uq_presence_workspace_actor UNIQUE (workspace_id, actor_name)`
  + the two `CREATE INDEX` statements; model metadata inspected for consistency (no stray
  `workspace_id` indexes on decisions/tasks/presence → no autogen drift).

## Tests — 19 added (`tests/test_backend_api_agent1.py`)

Presence upsert idempotency, concurrent heartbeats (no conflict), presence unique-constraint on
model + reflected in DB, lookup indexes present + reflected in DB; delete task/decision/workspace
(204/404/permission), task-delete → decision task_id SET NULL; list public directory, secure
discloses-key-once / not-rekeyed / 404, rotate-key owner-only / old-key-stops / open-workspace.

## Gates

- `uv run ruff check api/ tests/` → **All checks passed!**
- `uv run ruff format api/ tests/` → clean.
- `uv run pytest -q` → **57 passed** (baseline 38 + 19 new; no regressions, no warnings).

## Auth-design justification (assumptions)

- **`GET /workspaces` is intentionally public.** Principals are per-workspace (there is no
  instance-wide identity to gate on), a directory is needed to *discover* workspaces, and only
  non-secret metadata (slug/name/created_at/secured) is exposed — keys are never returned. Keyless
  workspaces must stay discoverable so they can be secured.
- **`POST /workspaces/{slug}/secure` intentionally takes no `Depends`.** An open workspace has no
  admin/owner at all, so there is no credential to require. **Anyone may secure an open workspace**;
  the first caller becomes the de-facto owner by taking the disclosed key. This matches the existing
  open `POST /workspaces` provisioning model. For an **already-secured** workspace it is
  **idempotent and returns HTTP 200 with `api_key=null`** — it does NOT re-key and never re-discloses
  the key (re-keying is `rotate-key`'s job, owner-gated). Verified by tests.

## Assumptions / notes

- Rotation on an open (unknown) slug resolves via `require_action` to a full-access open principal
  and so succeeds (auto-creating/securing the workspace) — consistent with the open-workspace model.
- `secure` and `rotate-key` are the only ways to mint/rotate the workspace key besides `POST
  /workspaces`; per-actor keys are unaffected by rotation.

## Files changed

- `api/app/models/models.py`
- `api/app/schemas/schemas.py`
- `api/app/api/routes/context.py`
- `api/migrations/versions/2c3bc1c08eea_presence_unique_and_lookup_indexes.py` (new)
- `tests/test_backend_api_agent1.py` (new)

## Commit

`1c14517` — feat(api): presence upsert + lookup indexes (#7), delete endpoints (#8), workspace management (#9)

**Deviation:** the three tasks share `context.py`/`models.py`/`schemas.py`, so their edits are not
independently committable without hunk surgery; they are delivered in one commit whose message
documents all three task areas (rather than three broken intermediate commits).
