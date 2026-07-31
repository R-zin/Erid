import * as vscode from "vscode";
import { HubBridgeClient } from "../bridge/HubBridgeClient";
import { resolveActorName } from "../util/git";

const EDITOR_DEBOUNCE_MS = 2000;

/**
 * Reports the human's presence to the hub.
 *
 * - Debounced (~2 s) post on each active-editor change, carrying the workspace-relative
 *   path of the focused file.
 * - A heartbeat at `heartbeatSeconds` (default 240; below the 10-minute staleness
 *   window) keeps the entry alive even when the file does not change.
 *
 * Actor name resolution: `contextHub.actorName` → `git config user.name` → OS username.
 */
export class PresenceReporter implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private heartbeat: NodeJS.Timeout | undefined;
  private debounce: NodeJS.Timeout | undefined;
  private actorName: string | undefined;
  private running = false;

  constructor(
    private readonly bridge: HubBridgeClient,
    private readonly output: vscode.OutputChannel,
  ) {}

  async start(): Promise<void> {
    if (this.running) {
      return;
    }
    this.running = true;
    const cfg = vscode.workspace.getConfiguration("contextHub");
    this.actorName = await resolveActorName(cfg.get<string>("actorName"), this.workspaceFolder());

    const heartbeatSeconds = Math.max(15, cfg.get<number>("heartbeatSeconds", 240));
    this.heartbeat = setInterval(() => void this.post(), heartbeatSeconds * 1000);
    this.heartbeat.unref?.();

    const listener = vscode.window.onDidChangeActiveTextEditor(() => {
      if (this.debounce) {
        clearTimeout(this.debounce);
      }
      this.debounce = setTimeout(() => void this.post(), EDITOR_DEBOUNCE_MS);
      this.debounce.unref?.();
    });
    this.disposables.push(listener);

    // Post immediately for whatever is currently focused.
    void this.post();
  }

  private workspaceFolder(): string | undefined {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  }

  /** Current editor's workspace-relative path, or undefined when nothing/no file is open. */
  private currentRelativeFile(): string | undefined {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.uri.scheme !== "file") {
      return undefined;
    }
    const rel = vscode.workspace.asRelativePath(editor.document.uri, false);
    return rel || undefined;
  }

  private async post(): Promise<void> {
    if (!this.running || !this.bridge.running || !this.actorName) {
      return;
    }
    const cfg = vscode.workspace.getConfiguration("contextHub");
    if (!cfg.get<boolean>("autoPresence", true)) {
      return;
    }
    try {
      await this.bridge.postPresence(this.actorName, this.currentRelativeFile(), "human");
    } catch (err) {
      this.output.appendLine(`[presence] post failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  dispose(): void {
    this.running = false;
    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = undefined;
    }
    if (this.debounce) {
      clearTimeout(this.debounce);
      this.debounce = undefined;
    }
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables.length = 0;
  }
}
