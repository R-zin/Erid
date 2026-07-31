import * as vscode from "vscode";
import {
  DecisionOut,
  EventFrame,
  PresenceOut,
  Snapshot,
  StatusFrame,
  TaskOut,
  WorkspaceSummary,
} from "./bridge/protocol";

/**
 * Single source of truth for the connected workspace's state.
 *
 * Holds the latest authoritative snapshot and applies `event` deltas from the bridge.
 * Providers and the status bar subscribe to `onDidChange` to re-render.
 */
export class WorkspaceState implements vscode.Disposable {
  private summary: WorkspaceSummary | undefined;
  private tasks: TaskOut[] = [];
  private decisions: DecisionOut[] = [];
  private presence: PresenceOut[] = [];
  private connected = false;
  private slug = "";
  private lastError: string | undefined;

  private readonly _onDidChange = new vscode.EventEmitter<void>();
  readonly onDidChange = this._onDidChange.event;

  get currentSummary(): WorkspaceSummary | undefined {
    return this.summary;
  }
  get currentTasks(): readonly TaskOut[] {
    return this.tasks;
  }
  get currentDecisions(): readonly DecisionOut[] {
    return this.decisions;
  }
  get currentPresence(): readonly PresenceOut[] {
    return this.presence;
  }
  get isConnected(): boolean {
    return this.connected;
  }
  get currentSlug(): string {
    return this.slug;
  }
  get error(): string | undefined {
    return this.lastError;
  }

  /** Replace all state with a fresh snapshot (on connect / WS reconnect). */
  applySnapshot(snap: Snapshot, slug?: string): void {
    this.summary = snap.summary;
    this.slug = snap.summary?.slug ?? slug ?? this.slug;
    this.tasks = [...(snap.tasks ?? [])];
    this.decisions = [...(snap.decisions ?? [])];
    this.presence = [...(snap.presence ?? [])];
    this.connected = true;
    this.lastError = undefined;
    this._onDidChange.fire();
  }

  /** Apply one live `event` frame delta. */
  applyEvent(frame: EventFrame): void {
    switch (frame.type) {
      case "task_created":
      case "task_updated": {
        const t = frame.data as TaskOut;
        this.tasks = upsertBy(this.tasks, t, (x) => x.id === t.id);
        break;
      }
      case "task_deleted": {
        const { id } = frame.data as { id: string };
        this.tasks = this.tasks.filter((x) => x.id !== id);
        break;
      }
      case "decision_created": {
        const d = frame.data as DecisionOut;
        // Decisions render reverse-chronologically: newest first.
        this.decisions = [d, ...this.decisions.filter((x) => x.id !== d.id)];
        break;
      }
      case "decision_deleted": {
        const { id } = frame.data as { id: string };
        this.decisions = this.decisions.filter((x) => x.id !== id);
        break;
      }
      case "presence_updated": {
        const p = frame.data as PresenceOut;
        this.presence = upsertBy(this.presence, p, (x) => x.actor_name === p.actor_name);
        break;
      }
      case "workspace_deleted": {
        this.clear();
        this.lastError = `Workspace '${(frame.data as { slug?: string })?.slug ?? frame.workspace}' was deleted.`;
        this.connected = false;
        break;
      }
    }
    this._onDidChange.fire();
  }

  applyStatus(status: StatusFrame): void {
    this.connected = status.connected;
    if (status.slug) {
      this.slug = status.slug;
    }
    this.lastError = status.error;
    this._onDidChange.fire();
  }

  setError(message: string | undefined): void {
    this.lastError = message;
    this._onDidChange.fire();
  }

  setConnected(connected: boolean): void {
    this.connected = connected;
    this._onDidChange.fire();
  }

  clear(): void {
    this.summary = undefined;
    this.tasks = [];
    this.decisions = [];
    this.presence = [];
    this._onDidChange.fire();
  }

  dispose(): void {
    this._onDidChange.dispose();
  }
}

function upsertBy<T>(list: T[], item: T, match: (x: T) => boolean): T[] {
  const idx = list.findIndex(match);
  if (idx === -1) {
    return [...list, item];
  }
  const next = list.slice();
  next[idx] = item;
  return next;
}
