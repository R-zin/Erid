import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import * as readline from "node:readline";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import {
  DecisionOut,
  EventFrame,
  JsonRpcNotification,
  JsonRpcRequest,
  JsonRpcResponse,
  PresenceOut,
  RPC_ERROR,
  SearchResult,
  Snapshot,
  StatusFrame,
  TaskOut,
  WorkspaceListItem,
  WorkspaceSummary,
} from "./protocol";

const REQUEST_TIMEOUT_MS = 30_000;

/** Thrown when a hub call fails; `status` carries the HTTP status when known. */
export class BridgeError extends Error {
  readonly code: number;
  readonly status?: number;

  constructor(message: string, code: number, status?: number) {
    super(message);
    this.name = "BridgeError";
    this.code = code;
    this.status = status;
  }
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
  timer: NodeJS.Timeout;
  method: string;
}

export interface BridgeSpawnConfig {
  repoPath: string;
  apiBase: string;
  workspaceSlug: string;
  apiKey?: string;
  token?: string;
}

/**
 * Client for the Python hub bridge.
 *
 * Spawns `uv run python mcp-server/src/bridge.py` with `cwd = repoPath` and the hub
 * credentials in the environment, then exchanges JSON-RPC 2.0 NDJSON over stdio.
 * Responses are correlated to requests by `id`; bridge pushes (`event` / `snapshot` /
 * `status`) are surfaced as EventEmitters.
 */
export class HubBridgeClient implements vscode.Disposable {
  private proc: ChildProcessWithoutNullStreams | undefined;
  private rl: readline.Interface | undefined;
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();
  private readonly output: vscode.OutputChannel;
  private stopped = false;

  private readonly _onEvent = new vscode.EventEmitter<EventFrame>();
  private readonly _onSnapshot = new vscode.EventEmitter<Snapshot>();
  private readonly _onStatus = new vscode.EventEmitter<StatusFrame>();
  private readonly _onExit = new vscode.EventEmitter<number | null>();

  readonly onEvent = this._onEvent.event;
  readonly onSnapshot = this._onSnapshot.event;
  readonly onStatus = this._onStatus.event;
  /** Fires when the bridge process exits (crash, error, or `shutdown`). */
  readonly onExit = this._onExit.event;

  constructor(output: vscode.OutputChannel) {
    this.output = output;
  }

  get running(): boolean {
    return this.proc !== undefined && !this.stopped;
  }

  /** Pre-flight check: `uv` resolvable and `repoPath` holds a root `pyproject.toml`. */
  async preflight(config: BridgeSpawnConfig): Promise<{ ok: boolean; error?: string }> {
    const uv = await this.which("uv");
    if (!uv) {
      return {
        ok: false,
        error:
          "`uv` was not found on PATH. The AI Context Hub bridge runs via `uv run python " +
          "mcp-server/src/bridge.py`. Install uv (https://docs.astral.sh/uv/) and reload.",
      };
    }
    if (!config.repoPath) {
      return {
        ok: false,
        error: "`contextHub.repoPath` is empty. Set it to the repo root that contains `mcp-server/`.",
      };
    }
    const bridgePy = path.join(config.repoPath, "mcp-server", "src", "bridge.py");
    if (!fs.existsSync(bridgePy)) {
      return {
        ok: false,
        error:
          `No hub bridge found at ${bridgePy}.\n` +
          "`contextHub.repoPath` must point at the repo root containing `mcp-server/src/bridge.py`.",
      };
    }
    if (!fs.existsSync(path.join(config.repoPath, "pyproject.toml"))) {
      return {
        ok: false,
        error:
          `No pyproject.toml found in ${config.repoPath}.\n` +
          "`uv run` needs the repo root (with the root pyproject.toml) to resolve the bridge environment.",
      };
    }
    return { ok: true };
  }

  /** Spawn the bridge subprocess and start the NDJSON reader. Throws on preflight failure. */
  async start(config: BridgeSpawnConfig): Promise<void> {
    if (this.running) {
      return;
    }
    const pf = await this.preflight(config);
    if (!pf.ok) {
      this.output.appendLine(`[bridge] preflight failed: ${pf.error}`);
      throw new BridgeError(pf.error ?? "bridge preflight failed", RPC_ERROR.SERVER);
    }

    this.stopped = false;
    const env = {
      ...process.env,
      API_BASE: config.apiBase,
      WORKSPACE_SLUG: config.workspaceSlug,
      WORKSPACE_API_KEY: config.apiKey ?? "",
      WORKSPACE_TOKEN: config.token ?? "",
    };

    this.output.appendLine(
      `[bridge] spawning: uv run python mcp-server/src/bridge.py (cwd=${config.repoPath}, slug=${config.workspaceSlug})`,
    );
    this.proc = spawn("uv", ["run", "python", "mcp-server/src/bridge.py"], {
      cwd: config.repoPath,
      env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    this.rl = readline.createInterface({ input: this.proc.stdout, terminal: false });
    this.rl.on("line", (line) => this.handleLine(line));

    this.proc.stderr.on("data", (chunk: Buffer) => {
      for (const l of chunk.toString("utf8").split(/\r?\n/)) {
        if (l.trim().length > 0) {
          this.output.appendLine(`[bridge:stderr] ${l}`);
        }
      }
    });

    this.proc.on("error", (err) => {
      this.output.appendLine(`[bridge] process error: ${err.message}`);
      this.failAllPending(new BridgeError(`bridge process error: ${err.message}`, RPC_ERROR.SERVER));
    });

    this.proc.on("exit", (code) => {
      this.output.appendLine(`[bridge] exited with code ${code}`);
      const wasStopped = this.stopped;
      this.proc = undefined;
      this.rl?.close();
      this.rl = undefined;
      if (!wasStopped) {
        this.failAllPending(new BridgeError(`bridge exited unexpectedly (code ${code})`, RPC_ERROR.SERVER));
      }
      this._onExit.fire(code);
    });
  }

  /** Parse one NDJSON line off stdout and route it by shape. */
  private handleLine(line: string): void {
    const text = line.trim();
    if (text.length === 0) {
      return;
    }
    let msg: JsonRpcResponse & JsonRpcNotification & { id?: number };
    try {
      msg = JSON.parse(text);
    } catch {
      this.output.appendLine(`[bridge] dropping unparseable line: ${text}`);
      return;
    }

    if (typeof msg.id === "number") {
      this.handleResponse(msg as JsonRpcResponse);
      return;
    }
    // Notification (no id): route by method.
    switch (msg.method) {
      case "event":
        this._onEvent.fire((msg.params as { event: EventFrame }).event ?? (msg.params as unknown as EventFrame));
        break;
      case "snapshot":
        this._onSnapshot.fire(msg.params as unknown as Snapshot);
        break;
      case "status":
        this._onStatus.fire(msg.params as unknown as StatusFrame);
        break;
      default:
        this.output.appendLine(`[bridge] unknown notification: ${text}`);
    }
  }

  private handleResponse(msg: JsonRpcResponse): void {
    const entry = this.pending.get(msg.id);
    if (!entry) {
      this.output.appendLine(`[bridge] response for unknown id ${msg.id}`);
      return;
    }
    this.pending.delete(msg.id);
    clearTimeout(entry.timer);
    if (msg.error) {
      entry.reject(new BridgeError(msg.error.message, msg.error.code, msg.error.data?.status));
    } else {
      entry.resolve(msg.result);
    }
  }

  /** Send a request and await its correlated response (30 s timeout). */
  private request<T>(method: string, params?: Record<string, unknown>): Promise<T> {
    if (!this.running || !this.proc) {
      return Promise.reject(new BridgeError("bridge is not running (call connect first)", RPC_ERROR.SERVER));
    }
    const id = this.nextId++;
    const req: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
    const line = JSON.stringify(req);

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new BridgeError(`bridge request '${method}' timed out after ${REQUEST_TIMEOUT_MS}ms`, RPC_ERROR.SERVER));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer, method });
      this.proc!.stdin.write(line + "\n", (err) => {
        if (err) {
          clearTimeout(timer);
          this.pending.delete(id);
          reject(new BridgeError(`failed to write request '${method}': ${err.message}`, RPC_ERROR.SERVER));
        }
      });
    });
  }

  private failAllPending(err: BridgeError): void {
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(err);
      this.pending.delete(id);
    }
  }

  private which(bin: string): Promise<string | undefined> {
    return new Promise((resolve) => {
      const checker = process.platform === "win32" ? "where" : "which";
      const p = spawn(checker, [bin], { stdio: ["ignore", "pipe", "ignore"] });
      let out = "";
      p.stdout.on("data", (d: Buffer) => (out += d.toString("utf8")));
      p.on("error", () => resolve(undefined));
      p.on("close", (code) => resolve(code === 0 ? out.trim() : undefined));
    });
  }

  // -- typed method wrappers -------------------------------------------------
  // `slug` is threaded through as optional on every call; the bridge falls back to
  // its WORKSPACE_SLUG default when omitted.

  connect(slug?: string): Promise<Snapshot> {
    return this.request<Snapshot>("connect", slug ? { slug } : {});
  }
  getSummary(slug?: string): Promise<WorkspaceSummary> {
    return this.request<WorkspaceSummary>("getSummary", slug ? { slug } : {});
  }
  listTasks(status?: string, slug?: string): Promise<TaskOut[]> {
    return this.request<TaskOut[]>("listTasks", { ...(status ? { status } : {}), ...(slug ? { slug } : {}) });
  }
  createTask(title: string, assignedTo?: string, createdBy?: string, slug?: string): Promise<TaskOut> {
    return this.request<TaskOut>("createTask", {
      title,
      ...(assignedTo ? { assigned_to: assignedTo } : {}),
      ...(createdBy ? { created_by: createdBy } : {}),
      ...(slug ? { slug } : {}),
    });
  }
  updateTask(
    taskId: string,
    patch: { status?: string; title?: string; assigned_to?: string },
    slug?: string,
  ): Promise<TaskOut> {
    return this.request<TaskOut>("updateTask", { task_id: taskId, ...patch, ...(slug ? { slug } : {}) });
  }
  deleteTask(taskId: string, slug?: string): Promise<null> {
    return this.request<null>("deleteTask", { task_id: taskId, ...(slug ? { slug } : {}) });
  }
  taskDecisions(taskId: string, slug?: string): Promise<DecisionOut[]> {
    return this.request<DecisionOut[]>("taskDecisions", { task_id: taskId, ...(slug ? { slug } : {}) });
  }
  listDecisions(limit?: number, slug?: string): Promise<DecisionOut[]> {
    return this.request<DecisionOut[]>("listDecisions", {
      ...(limit !== undefined ? { limit } : {}),
      ...(slug ? { slug } : {}),
    });
  }
  createDecision(
    fields: {
      title: string;
      reason?: string;
      related_files?: string;
      made_by?: string;
      task_id?: string;
    },
    slug?: string,
  ): Promise<DecisionOut> {
    return this.request<DecisionOut>("createDecision", { ...fields, ...(slug ? { slug } : {}) });
  }
  deleteDecision(decisionId: string, slug?: string): Promise<null> {
    return this.request<null>("deleteDecision", { decision_id: decisionId, ...(slug ? { slug } : {}) });
  }
  listPresence(slug?: string): Promise<PresenceOut[]> {
    return this.request<PresenceOut[]>("listPresence", slug ? { slug } : {});
  }
  postPresence(
    actorName: string,
    currentFile?: string,
    actorType: string = "human",
    currentTask?: string,
    slug?: string,
  ): Promise<PresenceOut> {
    return this.request<PresenceOut>("postPresence", {
      actor_name: actorName,
      actor_type: actorType,
      ...(currentFile ? { current_file: currentFile } : {}),
      ...(currentTask ? { current_task: currentTask } : {}),
      ...(slug ? { slug } : {}),
    });
  }
  search(q: string, limit?: number, slug?: string): Promise<SearchResult> {
    return this.request<SearchResult>("search", { q, ...(limit !== undefined ? { limit } : {}), ...(slug ? { slug } : {}) });
  }
  listWorkspaces(): Promise<WorkspaceListItem[]> {
    return this.request<WorkspaceListItem[]>("listWorkspaces", {});
  }

  /** Ask the bridge to shut down, then hard-kill if it does not exit promptly. */
  async shutdown(): Promise<void> {
    if (!this.proc) {
      return;
    }
    this.stopped = true;
    try {
      await this.request<null>("shutdown", {});
    } catch {
      // The bridge may exit before answering; treat that as success.
    }
    this.dispose();
  }

  dispose(): void {
    this.stopped = true;
    this.failAllPending(new BridgeError("bridge disposed", RPC_ERROR.SERVER));
    this.rl?.close();
    this.rl = undefined;
    if (this.proc) {
      this.proc.kill("SIGTERM");
      this.proc = undefined;
    }
    this._onEvent.dispose();
    this._onSnapshot.dispose();
    this._onStatus.dispose();
    this._onExit.dispose();
  }
}
