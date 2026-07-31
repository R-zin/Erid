import * as vscode from "vscode";
import { DecisionOut } from "../bridge/protocol";
import { WorkspaceState } from "../state";

export class DecisionItem extends vscode.TreeItem {
  constructor(readonly decision: DecisionOut) {
    super(decision.title, vscode.TreeItemCollapsibleState.None);
    this.id = `decision:${decision.id}`;
    this.contextValue = "decision";
    this.iconPath = new vscode.ThemeIcon("lightbulb");

    const md = new vscode.MarkdownString();
    md.appendMarkdown(`**${decision.title}**\n\n`);
    if (decision.reason) {
      md.appendMarkdown(`*Reason:* ${decision.reason}\n\n`);
    }
    if (decision.related_files) {
      md.appendMarkdown(`*Files:* \`${decision.related_files}\`\n\n`);
    }
    if (decision.made_by) {
      md.appendMarkdown(`*By:* ${decision.made_by}\n\n`);
    }
    if (decision.task_id) {
      md.appendMarkdown(`*Linked task:* \`${decision.task_id}\`\n\n`);
    }
    md.appendMarkdown(`*${decision.created_at}*`);
    this.tooltip = md;
    this.description = decision.made_by ?? "";
  }
}

export class DecisionsProvider implements vscode.TreeDataProvider<DecisionItem> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<DecisionItem | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private readonly state: WorkspaceState) {
    state.onDidChange(() => this._onDidChangeTreeData.fire());
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: DecisionItem): vscode.TreeItem {
    return element;
  }

  getChildren(): DecisionItem[] {
    if (!this.state.isConnected) {
      return [];
    }
    // Reverse-chronological; the state store already prepends new decisions, and
    // snapshots come back latest-first — sort defensively by created_at desc.
    return [...this.state.currentDecisions]
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
      .map((d) => new DecisionItem(d));
  }
}
