import * as vscode from "vscode";
import { WorkspaceState } from "../state";

/**
 * Status-bar item showing the workspace summary and connection liveness.
 *
 * Live:   `$(plug) <slug>: N open / M tasks · D decisions` with the active actors in
 *         the tooltip.
 * Offline: `$(debug-disconnect) Hub: offline`, plus the last error if any.
 */
export class SummaryStatusBar implements vscode.Disposable {
  private readonly item: vscode.StatusBarItem;

  constructor(private readonly state: WorkspaceState) {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "contextHub.refresh";
    this.state.onDidChange(() => this.render());
    this.render();
    this.item.show();
  }

  private render(): void {
    const s = this.state.currentSummary;
    if (!this.state.isConnected || !s) {
      this.item.text = "$(debug-disconnect) Hub: offline";
      const tip = new vscode.MarkdownString("**AI Context Hub** — not connected.");
      if (this.state.error) {
        tip.appendMarkdown(`\n\n$(error) ${this.state.error}`);
      }
      tip.appendMarkdown("\n\nClick to retry / refresh.");
      this.item.tooltip = tip;
      this.item.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
      this.item.command = "contextHub.connect";
      this.item.show();
      return;
    }

    this.item.text = `$(plug) ${s.slug}: ${s.open_task_count}/${s.task_count} tasks · ${s.decision_count} decisions`;
    const tip = new vscode.MarkdownString(`**AI Context Hub** — *${s.name}* (\`${s.slug}\`)\n\n`);
    tip.appendMarkdown(`- Tasks: **${s.open_task_count}** open / ${s.task_count} total\n`);
    tip.appendMarkdown(`- Decisions: ${s.decision_count}\n`);
    tip.appendMarkdown(`- Active: ${s.active_developers.length > 0 ? s.active_developers.join(", ") : "—"}\n`);
    tip.appendMarkdown("\nLive · click to refresh");
    this.item.tooltip = tip;
    this.item.backgroundColor = undefined;
    this.item.command = "contextHub.refresh";
  }

  dispose(): void {
    this.item.dispose();
  }
}
