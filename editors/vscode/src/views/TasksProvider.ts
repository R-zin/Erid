import * as vscode from "vscode";
import { TaskOut } from "../bridge/protocol";
import { WorkspaceState } from "../state";

/** A task node (leaf) or a status group header (branch). */
export type TaskNode = TaskItem | TaskGroupItem;

const STATUS_ORDER = ["todo", "in_progress", "blocked", "done"];

export class TaskItem extends vscode.TreeItem {
  constructor(readonly task: TaskOut) {
    super(task.title, vscode.TreeItemCollapsibleState.None);
    this.id = `task:${task.id}`;
    this.contextValue = "task";
    this.iconPath = new vscode.ThemeIcon(iconForStatus(task.status));
    const bits: string[] = [`status: ${task.status}`];
    if (task.assigned_to) {
      bits.push(`assigned: ${task.assigned_to}`);
    }
    if (task.created_by) {
      bits.push(`by: ${task.created_by}`);
    }
    bits.push(`updated: ${task.updated_at}`);
    this.tooltip = new vscode.MarkdownString(`**${task.title}**\n\n${bits.join(" · ")}`);
    this.description = task.assigned_to ?? "";
    // Set the status in the description only when it is not obvious from grouping.
    this.command = {
      command: "contextHub.completeTask",
      title: "Complete Task",
      arguments: [this],
    };
  }
}

class TaskGroupItem extends vscode.TreeItem {
  constructor(readonly status: string, count: number) {
    super(`${labelForStatus(status)} (${count})`, vscode.TreeItemCollapsibleState.Expanded);
    this.id = `task-group:${status}`;
    this.contextValue = "taskGroup";
    this.iconPath = new vscode.ThemeIcon(iconForStatus(status));
    this.collapsibleState = vscode.TreeItemCollapsibleState.Expanded;
  }
}

function iconForStatus(status: string): string {
  switch (status) {
    case "done":
      return "pass";
    case "in_progress":
      return "sync~spin";
    case "blocked":
      return "error";
    default:
      return "circle-large-outline";
  }
}

function labelForStatus(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export class TasksProvider implements vscode.TreeDataProvider<TaskNode> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<TaskNode | undefined | null | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private readonly state: WorkspaceState) {
    state.onDidChange(() => this._onDidChangeTreeData.fire());
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: TaskNode): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TaskNode): TaskNode[] {
    const tasks = this.state.currentTasks;
    if (!this.state.isConnected) {
      return [];
    }
    if (!element) {
      // Group by status, in a stable known order then any extras.
      const groups = new Map<string, TaskOut[]>();
      for (const t of tasks) {
        const key = t.status || "todo";
        groups.set(key, [...(groups.get(key) ?? []), t]);
      }
      const keys = [...STATUS_ORDER.filter((s) => groups.has(s)), ...[...groups.keys()].filter((s) => !STATUS_ORDER.includes(s))];
      return keys.map((s) => new TaskGroupItem(s, groups.get(s)!.length));
    }
    if (element instanceof TaskGroupItem) {
      return tasks
        .filter((t) => (t.status || "todo") === element.status)
        .map((t) => new TaskItem(t));
    }
    return [];
  }
}
