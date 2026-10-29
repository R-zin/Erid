# Tasks: Erid Code Review Quality Hardening

## Task 1: Patch Path Traversal in Asset & SPA Serving

**Description:** Harden `serve_assets` and `serve_spa` in `api/app/main.py` against path traversal vulnerabilities by enforcing canonical path resolution and `is_relative_to(dist.resolve())` check. Add security regression tests.

**Acceptance criteria:**
- [x] Requests with relative segments (e.g. `/assets/../../.env` or `/../../pyproject.toml`) cannot access files outside `dist`
- [x] Valid asset requests and legitimate SPA client routes continue serving correctly
- [x] Security regression tests in `tests/test_frontend_integration.py` verify path traversal attempts return 404 or 403

**Verification:**
- [x] Tests pass: `.venv/bin/pytest tests/test_frontend_integration.py`
- [x] Linter clean: `uv run ruff check api/app/main.py tests/test_frontend_integration.py`

**Dependencies:** None

**Files likely touched:**
- `api/app/main.py`
- `tests/test_frontend_integration.py`

**Estimated scope:** S (2 files)

---

## Task 2: Scope OAuth Identities by Workspace

**Description:** Scope `OAuthIdentity` to a specific workspace by adding `workspace_id` foreign key and unique constraint `uq_oauth_provider_subject_workspace`. Update `_resolve_or_create_oauth_actor` to query by `(provider, provider_subject, workspace_id)` so users logging into multiple workspaces receive appropriate workspace-scoped actors. Create an Alembic migration and test.

**Acceptance criteria:**
- [x] `OAuthIdentity` includes `workspace_id` foreign key referencing `workspaces.id` with `ondelete="CASCADE"`
- [x] Unique constraint is on `(provider, provider_subject, workspace_id)`
- [x] `_resolve_or_create_oauth_actor` in `auth.py` creates or resolves actors per workspace
- [x] A user logging into workspace A and then workspace B with the same OAuth account succeeds in both workspaces without 403 errors or actor collisions
- [x] Alembic migration generated and applied

**Verification:**
- [x] Tests pass: `.venv/bin/pytest tests/test_oauth.py`
- [x] Migration check: `cd api && ../.venv/bin/alembic check`

**Dependencies:** None

**Files likely touched:**
- `api/app/models/models.py`
- `api/app/api/routes/auth.py`
- `api/migrations/versions/d7e8f9a0b1c2_scope_oauth_by_workspace.py`
- `tests/test_oauth.py`

**Estimated scope:** M (4 files)

---

## Task 3: Configure Alembic `include_object` for DB Search Vectors

**Description:** Add an `include_object` hook to `api/migrations/env.py` to ignore PostgreSQL-specific computed `search_vector` columns and trigram indexes during autogenerate and drift checks (`alembic check`).

**Acceptance criteria:**
- [x] `include_object` in `api/migrations/env.py` ignores column `search_vector` and trigram indexes on `tasks` and `decisions`
- [x] `alembic check` passes cleanly without reporting false positive column/index deletions

**Verification:**
- [x] Check command: `cd api && ../.venv/bin/alembic check`

**Dependencies:** Task 2

**Files likely touched:**
- `api/migrations/env.py`

**Estimated scope:** XS (1 file)

---

## Checkpoint: Security & Schema (Tasks 1-3)
- [x] All security regression tests pass: `.venv/bin/pytest tests/test_frontend_integration.py tests/test_oauth.py`
- [x] Alembic check passes: `cd api && ../.venv/bin/alembic check`
- [x] Linter clean: `uv run ruff check`

---

## Task 4: Consolidate Sequential Aggregate Queries in `/summary`

**Description:** Refactor `workspace_summary` in `api/app/api/routes/context_misc.py` to combine multiple sequential count queries into a consolidated query using SQL conditional aggregation, reducing database round-trips.

**Acceptance criteria:**
- [x] Task count and open task count are retrieved in a single query via `func.count(Task.id)` and `func.count(Task.id).filter(Task.status != TaskStatus.done)`
- [x] Response schema `WorkspaceSummary` and returned values remain 100% identical
- [x] Existing summary tests continue to pass

**Verification:**
- [x] Tests pass: `.venv/bin/pytest tests/test_sec_search_agent2.py tests/test_api.py`

**Dependencies:** None

**Files likely touched:**
- `api/app/api/routes/context_misc.py`

**Estimated scope:** S (1 file)

---

## Task 5: Implement Handoff Operations in Hub Bridge

**Description:** Add session handoff support to `mcp-server/src/bridge.py`. Include `handoffs` in `HubBridge.snapshot()` and implement JSON-RPC handlers `m_listHandoffs`, `m_createHandoff`, `m_acknowledgeHandoff`, and `m_resolveHandoff` in `METHODS`. Add integration tests.

**Acceptance criteria:**
- [x] `HubBridge.snapshot(slug)` includes `"handoffs": await self.client.list_handoffs(slug)`
- [x] Handlers `m_listHandoffs`, `m_createHandoff`, `m_acknowledgeHandoff`, and `m_resolveHandoff` are implemented and registered
- [x] Bridge tests in `mcp-server/tests/test_bridge.py` verify all handoff methods over stdio JSON-RPC

**Verification:**
- [x] Tests pass: `.venv/bin/pytest mcp-server/tests/test_bridge.py`
- [x] Linter clean: `uv run ruff check mcp-server/src/bridge.py`

**Dependencies:** None

**Files likely touched:**
- `mcp-server/src/bridge.py`
- `mcp-server/tests/test_bridge.py`

**Estimated scope:** S (2 files)

---

## Checkpoint: Backend & Bridge (Tasks 4-5)
- [x] All bridge and summary tests pass: `.venv/bin/pytest mcp-server/tests/test_bridge.py tests/test_sec_search_agent2.py`
- [x] Linter clean: `uv run ruff check`

---

## Task 6: Reconcile Optimistic UI Updates with API Responses

**Description:** Update `TaskCreateForm.jsx`, `DecisionCreateForm.jsx`, and `HandoffCreateForm.jsx` to replace the temporary optimistic item (`tempId`) with the server-returned object from `client.createX()` rather than dropping the placeholder and relying exclusively on WebSocket delivery. Update parent list components to support item reconciliation.

**Acceptance criteria:**
- [x] When task/decision/handoff creation succeeds via HTTP, the temporary item is reconciled with the real server record
- [x] Items do not flicker or disappear if the WebSocket is delayed or reconnecting
- [x] On HTTP error, optimistic items are rolled back cleanly
- [x] Frontend Vitest tests in `web/src/components.test.jsx` verify reconciliation behavior

**Verification:**
- [x] Tests pass: `cd web && npm test`
- [x] Frontend build succeeds: `cd web && npm run build`

**Dependencies:** None

**Files likely touched:**
- `web/src/components/TaskCreateForm.jsx`
- `web/src/components/TaskList.jsx`
- `web/src/components/DecisionCreateForm.jsx`
- `web/src/components/DecisionList.jsx`
- `web/src/components/HandoffCreateForm.jsx`
- `web/src/components/HandoffList.jsx`
- `web/src/components.test.jsx`

**Estimated scope:** M (7 files)

---

## Task 7: Extract Shared Agent Filtering Logic in Frontend

**Description:** Deduplicate regex agent filtering across `TaskList.jsx`, `DecisionList.jsx`, and `HandoffList.jsx` by creating a shared utility function `matchesAgentFilter(actorName, filter)` in `web/src/utils/filter.js`.

**Acceptance criteria:**
- [x] `matchesAgentFilter(actorName, filter)` handles `'all'`, `'human'`, `'claude'`, `'cursor'`, `'codex'` consistently
- [x] All three list components use the shared utility
- [x] Frontend tests pass and build succeeds

**Verification:**
- [x] Tests pass: `cd web && npm test`
- [x] Build succeeds: `cd web && npm run build`

**Dependencies:** Task 6

**Files likely touched:**
- `web/src/utils/filter.js`
- `web/src/components/TaskList.jsx`
- `web/src/components/DecisionList.jsx`
- `web/src/components/HandoffList.jsx`

**Estimated scope:** S (4 files)

---

## Final Verification Checkpoint
- [x] Full backend test suite passes: `.venv/bin/pytest` (all 152 tests)
- [x] Full frontend test suite passes: `cd web && npm test`
- [x] Frontend production build succeeds: `cd web && npm run build`
- [x] Ruff format and lint checks pass: `uv run ruff format --check api mcp-server tests` & `uv run ruff check api mcp-server tests`
- [x] VS Code extension typecheck passes: `cd editors/vscode && npm run typecheck`
- [x] Alembic schema drift check passes: `cd api && ../.venv/bin/alembic check`
