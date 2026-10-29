# Implementation Plan: Erid Code Review Quality Hardening

## Overview
This plan implements the critical security, correctness, architecture, and performance remediations identified in the multi-dimensional code review of the Erid AI Context Hub. It resolves arbitrary file traversal in static asset serving, fixes multi-workspace OAuth identity collision, extends the editor bridge with session handoff parity, hardens frontend optimistic UI reconciliation, consolidates `/summary` database queries, and resolves Alembic schema drift.

## Architecture Decisions
- **Path Traversal Security:** Use explicit path canonicalization (`.resolve()`) and check `is_relative_to(dist.resolve())` in `api/app/main.py` before serving any file via `FileResponse`.
- **OAuth Multi-Workspace Membership:** Scope `OAuthIdentity` by workspace (`workspace_id`) so a user authenticating via Google/GitHub into different workspaces receives separate, properly scoped `Actor` memberships rather than leaking across tenant boundaries.
- **Hub Bridge Handoff Support:** Extend `HubBridge.snapshot()` to include `handoffs` and add `m_listHandoffs`, `m_createHandoff`, `m_acknowledgeHandoff`, and `m_resolveHandoff` methods matching the FastMCP server and REST API contracts.
- **Frontend Optimistic Reconcile:** Instead of dropping optimistic items upon REST call completion and relying solely on WebSocket delivery, reconcile the temporary item with the actual returned record from the REST API to eliminate UI flickering and data loss during WebSocket reconnection.
- **Database Query Consolidation:** Consolidate task counts in `/summary` using SQL conditional aggregation (`func.count(Task.id).filter(...)`) to reduce round-trips from 4 sequential queries to 1-2.
- **Alembic Include Object Filter:** Configure `include_object` in `api/migrations/env.py` to ignore PostgreSQL-specific generated `search_vector` columns and indexes during automated drift detection.

---

## Task List

### Phase 1: Security & Database Integrity
- [x] **Task 1: Patch Path Traversal in Asset & SPA Serving (`api/app/main.py`)**
  - Implement path containment check (`is_relative_to`) in `serve_assets` and `serve_spa`.
  - Add security regression tests in `tests/test_frontend_integration.py` verifying path traversal attempts (`/../../`, `%2e%2e`, etc.) return 404/403.
- [x] **Task 2: Scope OAuth Identities by Workspace (`models.py`, `auth.py`)**
  - Add `workspace_id` foreign key to `OAuthIdentity` with `UniqueConstraint("provider", "provider_subject", "workspace_id")`.
  - Update `_resolve_or_create_oauth_actor` in `api/app/api/routes/auth.py` to query and bind identities per workspace.
  - Create Alembic migration `d7e8f9a0b1c2_scope_oauth_by_workspace.py`.
  - Add multi-workspace login test in `tests/test_oauth.py`.
- [x] **Task 3: Configure Alembic `include_object` for DB Search Vectors (`api/migrations/env.py`)**
  - Exclude unmapped `search_vector` and trigram indexes in `api/migrations/env.py` so `alembic check` passes without false positives.

### Checkpoint: Security & Schema
- [x] All security regression tests and OAuth tests pass: `uv run pytest tests/test_frontend_integration.py tests/test_oauth.py`
- [x] Schema drift check passes: `cd api && ../.venv/bin/alembic check`

### Phase 2: Protocol Parity & Backend Performance
- [x] **Task 4: Consolidate Sequential Aggregate Queries in `/summary` (`api/app/api/routes/context_misc.py`)**
  - Combine task counts in `workspace_summary` using SQL conditional aggregation.
  - Verify `tests/test_sec_search_agent2.py` and `tests/test_api.py` pass.
- [x] **Task 5: Implement Handoff Operations in Hub Bridge (`mcp-server/src/bridge.py`)**
  - Include handoffs in `HubBridge.snapshot()`.
  - Implement and register `m_listHandoffs`, `m_createHandoff`, `m_acknowledgeHandoff`, and `m_resolveHandoff` in `METHODS`.
  - Add integration tests in `mcp-server/tests/test_bridge.py`.

### Checkpoint: Backend & Bridge
- [x] Bridge and API tests pass: `uv run pytest mcp-server/tests/test_bridge.py tests/test_sec_search_agent2.py`

### Phase 3: Frontend Resilience & Cleanup
- [x] **Task 6: Reconcile Optimistic UI Updates with API Responses (`web/src/components/*`)**
  - Update `TaskCreateForm.jsx`, `DecisionCreateForm.jsx`, and `HandoffCreateForm.jsx` to replace `tempId` with the API returned record instead of discarding it.
  - Update `TaskList.jsx`, `DecisionList.jsx`, and `HandoffList.jsx` to support item reconciliation.
  - Verify `web/src/components.test.jsx` passes.
- [x] **Task 7: Extract Shared Agent Filtering Logic (`web/src/utils/filter.js`)**
  - Create shared `matchesAgentFilter(actorName, filter)` utility and adopt in `TaskList.jsx`, `DecisionList.jsx`, and `HandoffList.jsx`.
  - Verify vitest tests and build: `cd web && npm test && npm run build`.

### Final Verification Checkpoint
- [x] Full backend test suite passes: `uv run pytest` (all 152 tests)
- [x] Frontend test suite and build pass: `cd web && npm test && npm run build`
- [x] Linter checks pass: `uv run ruff check` and `uv run ruff format --check`
- [x] VS Code extension typecheck passes: `cd editors/vscode && npm run typecheck`

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Modifying `OAuthIdentity` schema could impact existing database rows | High | Write backward-compatible migration populating `workspace_id` from existing `actor.workspace_id`. |
| Reconciling optimistic items might duplicate items if WebSocket arrives concurrently | Medium | Use `id` mapping and deduplicate on upsert so replacing temporary IDs is idempotent. |
| Custom `include_object` in Alembic could inadvertently hide real schema drift | Low | Restrict exclusion strictly to column name `search_vector` and index names starting with `ix_` on trigram/tsvector. |

## Open Questions
- None. Requirements and contracts are well-defined by existing tests and schemas.
