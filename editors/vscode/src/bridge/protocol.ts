/**
 * Wire-protocol types shared with the Python hub bridge (`mcp-server/src/bridge.py`).
 *
 * The extension speaks JSON-RPC 2.0 as NDJSON over stdio to the bridge, which in
 * turn owns all hub I/O (REST + WebSocket) via `APIClient`. These interfaces mirror
 * the backend schemas in `api/app/schemas/schemas.py`. Do not add fields the bridge
 * does not send.
 */

/** A shared-workspace task. */
export interface TaskOut {
  id: string;
  title: string;
  status: string;
  assigned_to: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

/** A recorded architecture/implementation decision. */
export interface DecisionOut {
  id: string;
  title: string;
  reason: string | null;
  related_files: string | null;
  made_by: string | null;
  task_id: string | null;
  created_at: string;
}

/** One actor's (human or AI) presence entry, keyed server-side by `actor_name`. */
export interface PresenceOut {
  id: string;
  actor_name: string;
  actor_type: string;
  current_file: string | null;
  current_task: string | null;
  last_seen: string;
}

/** Aggregate counts for a workspace; drives the status-bar item. */
export interface WorkspaceSummary {
  slug: string;
  name: string;
  task_count: number;
  open_task_count: number;
  decision_count: number;
  active_developers: string[];
}

/** One workspace in the hub-level listing. */
export interface WorkspaceListItem {
  slug: string;
  name: string;
  created_at: string;
  secured: boolean;
}

/**
 * A live WebSocket frame forwarded 1:1 by the bridge. `data` is a full
 * `TaskOut`/`DecisionOut`/`PresenceOut` for create/update events, `{id, workspace_id}`
 * for the `*_deleted` events, and `{slug}` for `workspace_deleted`.
 */
export interface EventFrame {
  workspace: string;
  type:
    | "task_created"
    | "task_updated"
    | "task_deleted"
    | "decision_created"
    | "decision_deleted"
    | "presence_updated"
    | "workspace_deleted";
  data: unknown;
}

/** Authoritative resync payload, sent on connect and on each WS reconnect. */
export interface Snapshot {
  summary: WorkspaceSummary;
  tasks: TaskOut[];
  decisions: DecisionOut[];
  presence: PresenceOut[];
}

/** Bridge→editor `status` notification (`params`). */
export interface StatusFrame {
  connected: boolean;
  slug: string;
  error?: string;
}

/** Result of the `search` method (manually typed — the endpoint has no response_model). */
export interface SearchResult {
  query: string;
  decisions: DecisionOut[];
  tasks: TaskOut[];
}

/** JSON-RPC 2.0 request envelope (extension → bridge). */
export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id: number;
  method: string;
  params?: Record<string, unknown>;
}

/** JSON-RPC 2.0 error object. `data.status` carries the HTTP status on hub errors. */
export interface JsonRpcError {
  code: number;
  message: string;
  data?: { status?: number };
}

/** JSON-RPC 2.0 response envelope (bridge → extension). */
export interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: number;
  result?: unknown;
  error?: JsonRpcError;
}

/** Bridge→extension notification envelope (no `id`). */
export interface JsonRpcNotification {
  jsonrpc: "2.0";
  method: "event" | "snapshot" | "status";
  params?: unknown;
}

/** Well-known JSON-RPC / bridge error codes. */
export const RPC_ERROR = {
  PARSE: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  /** Hub HTTP error; `error.data.status` carries the HTTP status. */
  SERVER: -32000,
} as const;

/** Presence entries older than this are considered stale (mirrors backend STALE_AFTER). */
export const STALE_AFTER_MS = 10 * 60 * 1000;

/** True if a `last_seen` ISO timestamp is older than the staleness window. */
export function isStale(lastSeen: string, now: number = Date.now()): boolean {
  const t = Date.parse(lastSeen);
  if (Number.isNaN(t)) {
    return false;
  }
  return now - t > STALE_AFTER_MS;
}
