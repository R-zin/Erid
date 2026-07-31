import * as vscode from "vscode";
import { isStale, PresenceOut } from "../bridge/protocol";
import { WorkspaceState } from "../state";

export class PresenceItem extends vscode.TreeItem {
  constructor(readonly presence: PresenceOut) {
    super(presence.actor_name, vscode.TreeItemCollapsibleState.None);
    this.id = `presence:${presence.actor_name}`;
    this.contextValue = "presence";

    const stale = isStale(presence.last_seen);
    const icon = presence.actor_type === "human" ? "person" : "hubot";
    // Dim stale (>10 min) actors; a grey circle conveys "not live".
    this.iconPath = new vscode.ThemeIcon(stale ? "circle-slash" : icon);
    this.description = presence.actor_type;

    const lines: string[] = [`**${presence.actor_name}** (${presence.actor_type})`];
    if (presence.current_file) {
      lines.push(`File: \`${presence.current_file}\``);
    }
    if (presence.current_task) {
      lines.push(`Task: ${presence.current_task}`);
    }
    lines.push(`Last seen: ${presence.last_seen}${stale ? "  •  *(stale)*" : ""}`);
    const md = new vscode.MarkdownString(lines.join("\n\n"));
    this.tooltip = md;

    if (stale) {
      // Grey it out; the description slot already shows the type, so push the marker.
      this.description = `${presence.actor_type} · stale`;
    }
  }
}

export class PresenceProvider implements vscode.TreeDataProvider<PresenceItem> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<PresenceItem | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private readonly ticker: NodeJS.Timeout;

  constructor(private readonly state: WorkspaceState) {
    state.onDidChange(() => this._onDidChangeTreeData.fire());
    // Re-render periodically so items cross the 10-minute staleness threshold even
    // without any new events.
    this.ticker = setInterval(() => this._onDidChangeTreeData.fire(), 30_000);
    this.ticker.unref?.();
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  dispose(): void {
    clearInterval(this.ticker);
    this._onDidChangeTreeData.dispose();
  }

  getTreeItem(element: PresenceItem): vscode.TreeItem {
    return element;
  }

  getChildren(): PresenceItem[] {
    if (!this.state.isConnected) {
      return [];
    }
    // Live actors first, then stale; alphabetical within each band.
    return [...this.state.currentPresence]
      .sort((a, b) => {
        const sa = isStale(a.last_seen) ? 1 : 0;
        const sb = isStale(b.last_seen) ? 1 : 0;
        if (sa !== sb) {
          return sa - sb;
        }
        return a.actor_name.localeCompare(b.actor_name);
      })
      .map((p) => new PresenceItem(p));
  }
}
