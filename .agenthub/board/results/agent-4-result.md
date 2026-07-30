# agent-4 (test-sweep) — Task #14: Expand test coverage

**Worktree:** `/Users/razinm/PycharmProjects/Erid/.claude/worktrees/agent-a6c15e8a4d395a9c4`
**Branch:** `worktree-agent-a6c15e8a4d395a9c4`
**Scope honored:** Tests only. No production source, no existing test files, no config/docs touched.

## Totals
- **Before:** 38 passed
- **After:** 63 passed (+25 new tests)
- **Green runs:** 3 consecutive (≥2 required). 63/63 each run, no flakes.
- **ruff:** `All checks passed!` on `tests/` + `mcp-server/tests/`; both new files `already formatted` (line-length 120).

## Commits
- `fa12871` test(api): WS auth + non-decision event payloads + edge cases (#14)
- `17f9513` test(mcp): client header-selection + error paths (#14)

## New tests — `tests/test_coverage_agent4.py` (16)

WS auth (live uvicorn server, mirrors `test_websocket.py` live_server fixture; bounded `asyncio.wait_for`, no wall-clock sleeps in assertions):
- `test_ws_open_workspace_streams_event` — open WS connects, receives `task_created`.
- `test_ws_secured_without_credentials_closed_1008` — no creds → close code 1008.
- `test_ws_secured_with_valid_api_key_connects` — valid key via `X-API-Key` header → connects.
- `test_ws_secured_with_valid_api_key_query_param` — valid `?api_key=` → connects.
- `test_ws_secured_with_bad_key_closed_1008` — wrong `?api_key=` → 1008.
- `test_ws_secured_with_valid_token_query_param` — valid `?token=` (JWT from login) → connects + streams.

Non-decision bus payloads (deterministic ASGI `client` + in-process bus `subscribe` pattern):
- `test_event_task_created_payload` — `task_created` shape: title/status/created_by/assigned_to/id/created_at + routing slug.
- `test_event_task_updated_payload` — `task_updated` shape incl. `updated_at` non-null.
- `test_event_presence_updated_payload` — `presence_updated` carries actor_name/type/file/task/last_seen.
- `test_event_fanout_scoped_per_workspace` — events are scoped per slug; a different slug's subscriber is NOT notified (negative-delivery assertion, bounded).

Edge/validation:
- `test_search_on_empty_workspace` — empty search returns empty task/decision buckets.
- `test_summary_on_empty_workspace` — zero counts, no active developers.
- `test_presence_heartbeat_advances_last_seen` — second heartbeat updates `last_seen`, no duplicate row.
- `test_update_nonexistent_task_404` — PUT missing task → 404 with "not found".
- `test_decision_with_out_of_scope_task_404` — decision linked to a task in a *different* workspace → 404.
- `test_task_status_filter_empty_result` — status filter with no matches → empty list, not error.

## New tests — `mcp-server/tests/test_client_agent4.py` (9)
Offline, `httpx.MockTransport`-stubbed (no real server). Hermetic vs ambient env (empty strings override `WORKSPACE_TOKEN`/`WORKSPACE_API_KEY`).
- `test_bearer_token_preferred_over_api_key` — both set → only `Authorization: Bearer` sent.
- `test_api_key_only_when_no_token` — no token → `X-API-Key`, no Bearer.
- `test_no_auth_header_when_neither_set` — neither → no auth header.
- `test_empty_token_falls_back_to_api_key` — empty-string token is falsy → api key used.
- `test_get_raises_for_4xx` — 403 propagates as `HTTPStatusError`.
- `test_get_raises_for_5xx` — 500 propagates.
- `test_write_raises_for_422` — 422 on write propagates.
- `test_auth_header_reaches_server_on_request` — configured Bearer header actually sent on the wire.
- `test_request_targets_workspace_root_and_path` — URL built as `/api/workspaces/{slug}/<path>`.

## Intentionally OMITTED (concurrent-feature dependent)
- No WS/REST tests for DELETE-task / DELETE-decision endpoints, `/workspaces` list-all, or workspace-management config — those are being built concurrently by agent-1 and do not exist in this worktree. Not tested, per scope.
- MCP client tests stay unit-level (no live MCP server round-trip) since the MCP server wiring was out of scope; only client header/error logic is covered.

## Deviations
- None significant. One deviation in approach worth noting: WS-auth happy-path tests use the *live* uvicorn server (auth happens on the real WS handshake via query params, which the ASGI-transport `client` can't drive), while non-decision *payload* tests use the deterministic in-process bus `subscribe` pattern from `test_websocket.py` — avoiding a live server and wall-clock sleeps for payload assertions.
