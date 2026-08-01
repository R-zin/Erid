import * as vscode from "vscode";
import { HubBridgeClient } from "../bridge/HubBridgeClient";
import { DecisionOut, TaskOut } from "../bridge/protocol";
import { WorkspaceState } from "../state";
import { resolveActorName } from "../util/git";
import { TaskItem } from "../views/TasksProvider";
import { DecisionItem } from "../views/DecisionsProvider";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function workspaceFolder(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

function activeRelativeFile(): string | undefined {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== "file") {
    return undefined;
  }
  const rel = vscode.workspace.asRelativePath(editor.document.uri, false);
  return rel || undefined;
}

/** Guard: only run `body` when the bridge is up; otherwise prompt to connect. */
async function withBridge(bridge: HubBridgeClient, body: () => Promise<void>): Promise<void> {
  if (!bridge.running) {
    const pick = await vscode.window.showWarningMessage("AI Context Hub is not connected.", "Connect");
    if (pick === "Connect") {
      await vscode.commands.executeCommand("contextHub.connect");
    }
    return;
  }
  try {
    await body();
  } catch (err) {
    vscode.window.showErrorMessage(`AI Context Hub: ${errorMessage(err)}`);
  }
}

/** Register all quick-action commands. Returns disposables. */
export function registerQuickActions(
  bridge: HubBridgeClient,
  state: WorkspaceState,
  output: vscode.OutputChannel,
): vscode.Disposable[] {
  const d: vscode.Disposable[] = [];

  d.push(
    vscode.commands.registerCommand("contextHub.refresh", async () => {
      await withBridge(bridge, async () => {
        const [summary, tasks, decisions, presence] = await Promise.all([
          bridge.getSummary(),
          bridge.listTasks(),
          bridge.listDecisions(),
          bridge.listPresence(),
        ]);
        state.applySnapshot({ summary, tasks, decisions, presence });
        state.setConnected(true);
      });
    }),
  );

  d.push(
    vscode.commands.registerCommand("contextHub.createTask", async () => {
      const title = await vscode.window.showInputBox({
        prompt: "Task title",
        placeHolder: "e.g. Wire bridge reconnect backoff",
        ignoreFocusOut: true,
        validateInput: (v) => (v.trim().length === 0 ? "Title is required" : undefined),
      });
      if (title === undefined) {
        return;
      }
      const assignee = await vscode.window.showInputBox({
        prompt: "Assign to (optional)",
        placeHolder: "actor name — leave blank to skip",
        ignoreFocusOut: true,
      });
      if (assignee === undefined) {
        return;
      }
      await withBridge(bridge, async () => {
        const createdBy = await resolveActorName(vscode.workspace.getConfiguration("contextHub").get("actorName"), workspaceFolder());
        const task = await bridge.createTask(title.trim(), assignee.trim() || undefined, createdBy);
        vscode.window.showInformationMessage(`Created task "${task.title}".`);
      });
    }),
  );

  d.push(
    vscode.commands.registerCommand("contextHub.completeTask", async (item?: TaskItem) => {
      const task = item?.task ?? (await pickTask(state, "Complete which task?"));
      if (!task) {
        return;
      }
      await withBridge(bridge, async () => {
        await bridge.updateTask(task.id, { status: "done" });
        vscode.window.showInformationMessage(`Completed "${task.title}".`);
      });
    }),
  );

  d.push(
    vscode.commands.registerCommand("contextHub.deleteTask", async (item?: TaskItem) => {
      const task = item?.task ?? (await pickTask(state, "Delete which task?"));
      if (!task) {
        return;
      }
      const confirm = await vscode.window.showWarningMessage(
        `Delete task "${task.title}"? This cannot be undone.`,
        { modal: true },
        "Delete",
      );
      if (confirm !== "Delete") {
        return;
      }
      await withBridge(bridge, async () => {
        await bridge.deleteTask(task.id);
        vscode.window.showInformationMessage(`Deleted task "${task.title}".`);
      });
    }),
  );

  d.push(
    vscode.commands.registerCommand("contextHub.createDecision", async () => {
      const title = await vscode.window.showInputBox({
        prompt: "Decision title",
        placeHolder: "e.g. Use NDJSON for the bridge wire format",
        ignoreFocusOut: true,
        validateInput: (v) => (v.trim().length === 0 ? "Title is required" : undefined),
      });
      if (title === undefined) {
        return;
      }
      const reason = await vscode.window.showInputBox({
        prompt: "Reason (optional)",
        placeHolder: "why this decision was made",
        ignoreFocusOut: true,
      });
      if (reason === undefined) {
        return;
      }

      const prefill = activeRelativeFile();
      const relatedFiles = await vscode.window.showInputBox({
        prompt: "Related files (optional)",
        value: prefill ?? "",
        placeHolder: "comma-separated workspace-relative paths",
        ignoreFocusOut: true,
      });
      if (relatedFiles === undefined) {
        return;
      }

      // Offer linking the decision to a task.
      const taskId = await pickTaskForLink(state);
      if (taskId === "cancelled") {
        return;
      }

      await withBridge(bridge, async () => {
        const madeBy = await resolveActorName(vscode.workspace.getConfiguration("contextHub").get("actorName"), workspaceFolder());
        const decision = await bridge.createDecision({
          title: title.trim(),
          reason: reason.trim() || undefined,
          related_files: relatedFiles.trim() || undefined,
          made_by: madeBy,
          task_id: taskId === "none" ? undefined : taskId,
        });
        vscode.window.showInformationMessage(`Recorded decision "${decision.title}".`);
      });
    }),
  );

  d.push(
    vscode.commands.registerCommand("contextHub.deleteDecision", async (item?: DecisionItem) => {
      const decision = item?.decision ?? (await pickDecision(state, "Delete which decision?"));
      if (!decision) {
        return;
      }
      const confirm = await vscode.window.showWarningMessage(
        `Delete decision "${decision.title}"? This cannot be undone.`,
        { modal: true },
        "Delete",
      );
      if (confirm !== "Delete") {
        return;
      }
      await withBridge(bridge, async () => {
        await bridge.deleteDecision(decision.id);
        vscode.window.showInformationMessage(`Deleted decision "${decision.title}".`);
      });
    }),
  );

  d.push(
    vscode.commands.registerCommand("contextHub.search", async () => {
      await withBridge(bridge, async () => {
        const qp = vscode.window.createQuickPick<vscode.QuickPickItem & { payload?: unknown; kindLabel?: string }>();
        qp.placeholder = "Search tasks and decisions across the workspace";
        qp.matchOnDescription = true;
        qp.matchOnDetail = true;
        let reqSeq = 0;
        let current: SearchItems = { tasks: [], decisions: [] };

        const setItems = async () => {
          const taskItems = current.tasks.map((t) => ({
            label: `$(checklist) ${t.title}`,
            description: `task · ${t.status}`,
            detail: t.assigned_to ? `assigned: ${t.assigned_to}` : undefined,
            payload: t,
            kindLabel: "task",
          }));
          const decisionItems = current.decisions.map((x) => ({
            label: `$(lightbulb) ${x.title}`,
            description: "decision",
            detail: x.reason ?? undefined,
            payload: x,
            kindLabel: "decision",
          }));
          qp.items = [...taskItems, ...decisionItems];
        };

        qp.onDidChangeValue(async (value) => {
          const seq = ++reqSeq;
          if (value.trim().length < 2) {
            current = { tasks: [], decisions: [] };
            await setItems();
            return;
          }
          qp.busy = true;
          try {
            const res = await bridge.search(value.trim(), 20);
            if (seq !== reqSeq) {
              return; // a newer query superseded this one
            }
            current = { tasks: res.tasks, decisions: res.decisions };
            await setItems();
          } catch (err) {
            output.appendLine(`[search] ${errorMessage(err)}`);
          } finally {
            qp.busy = false;
          }
        });

        qp.onDidAccept(async () => {
          const sel = qp.selectedItems[0];
          qp.hide();
          if (!sel?.payload) {
            return;
          }
          if (sel.kindLabel === "decision") {
            const x = sel.payload as DecisionOut;
            const doc = await vscode.workspace.openTextDocument({
              content: `# ${x.title}\n\n${x.reason ?? ""}\n\nFiles: ${x.related_files ?? "—"}\nBy: ${x.made_by ?? "—"}\nTask: ${x.task_id ?? "—"}\n${x.created_at}`,
            });
            await vscode.window.showTextDocument(doc, { preview: true });
          } else {
            const t = sel.payload as TaskOut;
            const doc = await vscode.workspace.openTextDocument({
              content: `# ${t.title}\n\nStatus: ${t.status}\nAssigned: ${t.assigned_to ?? "—"}\nCreated by: ${t.created_by ?? "—"}\nUpdated: ${t.updated_at}`,
            });
            await vscode.window.showTextDocument(doc, { preview: true });
          }
        });

        qp.onDidHide(() => qp.dispose());
        qp.show();
      });
    }),
  );

  return d;
}

interface SearchItems {
  tasks: TaskOut[];
  decisions: DecisionOut[];
}

async function pickTask(state: WorkspaceState, placeHolder: string): Promise<TaskOut | undefined> {
  const tasks = state.currentTasks;
  if (tasks.length === 0) {
    vscode.window.showInformationMessage("No tasks in the workspace.");
    return undefined;
  }
  const pick = await vscode.window.showQuickPick(
    tasks.map((t) => ({ label: t.title, description: t.status, task: t })),
    { placeHolder },
  );
  return pick?.task;
}

/** Interactive task picker for linking a decision; `"none"` skips, `"cancelled"` aborts. */
async function pickTaskForLink(state: WorkspaceState): Promise<string | "none" | "cancelled" | undefined> {
  const tasks = state.currentTasks;
  const picks = await vscode.window.showQuickPick(
    [
      { label: "$(circle-slash) Don't link to a task", id: "none" as const },
      ...tasks.map((t) => ({ label: t.title, description: t.status, id: t.id })),
    ],
    { placeHolder: "Link this decision to a task? (optional)", ignoreFocusOut: true },
  );
  if (!picks) {
    return "cancelled";
  }
  return picks.id;
}

async function pickDecision(state: WorkspaceState, placeHolder: string): Promise<DecisionOut | undefined> {
  const decisions = state.currentDecisions;
  if (decisions.length === 0) {
    vscode.window.showInformationMessage("No decisions in the workspace.");
    return undefined;
  }
  const pick = await vscode.window.showQuickPick(
    decisions.map((x) => ({ label: x.title, description: x.made_by ?? "", decision: x })),
    { placeHolder },
  );
  return pick?.decision;
}
