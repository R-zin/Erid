import * as vscode from "vscode";
import { HubBridgeClient } from "./bridge/HubBridgeClient";
import { WorkspaceState } from "./state";
import { TasksProvider } from "./views/TasksProvider";
import { DecisionsProvider } from "./views/DecisionsProvider";
import { PresenceProvider } from "./views/PresenceProvider";
import { SummaryStatusBar } from "./views/summaryStatus";
import { registerQuickActions } from "./actions/quickActions";
import { PresenceReporter } from "./actions/presence";
import { setupMcp } from "./actions/setupMcp";

const SECRET_API_KEY = "contextHub.apiKey";
const SECRET_TOKEN = "contextHub.token";

let output: vscode.OutputChannel;
let state: WorkspaceState;
let presenceReporter: PresenceReporter | undefined;

/** The live bridge, recreated on every connect. */
type BridgeHolder = { current: HubBridgeClient | undefined };

/** Resolve `${workspaceFolder}` (and friends) against the real folder path. */
function resolveRepoPath(configured: string): string {
  const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "";
  return configured.replace(/\$\{workspaceFolder\}/g, folder);
}

/** `${workspaceFolder}` is meaningless without an open folder. */
function folderRequired(): vscode.WorkspaceFolder | undefined {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    vscode.window.showErrorMessage("AI Context Hub: open a workspace folder to use the hub.");
  }
  return folder;
}

/** Prompt for and persist a secret in SecretStorage. Returns the stored value. */
async function ensureSecret(
  secrets: vscode.SecretStorage,
  key: string,
  title: string,
  optional: boolean,
): Promise<string> {
  const existing = await secrets.get(key);
  if (existing) {
    return existing;
  }
  const value = await vscode.window.showInputBox({
    title,
    prompt: optional ? "Optional — press Enter to skip (open workspace)" : "Required",
    password: true,
    ignoreFocusOut: true,
  });
  if (value === undefined) {
    return ""; // cancelled
  }
  await secrets.store(key, value);
  return value;
}

async function connect(
  bridge: BridgeHolder,
  secrets: vscode.SecretStorage,
  globalState: vscode.Memento,
  outputChannel: vscode.OutputChannel,
): Promise<void> {
  if (!folderRequired()) {
    return;
  }
  const cfg = vscode.workspace.getConfiguration("contextHub");
  const slug = cfg.get<string>("workspaceSlug", "").trim();
  if (!slug) {
    const entered = await vscode.window.showInputBox({
      title: "Connect to AI Context Hub",
      prompt: "Workspace slug to connect to",
      ignoreFocusOut: true,
      validateInput: (v) => (v.trim().length === 0 ? "A workspace slug is required" : undefined),
    });
    if (!entered) {
      return;
    }
    await vscode.workspace.getConfiguration("contextHub").update("workspaceSlug", entered.trim(), vscode.ConfigurationTarget.Workspace);
  }

  const apiKey = await ensureSecret(secrets, SECRET_API_KEY, "AI Context Hub — Workspace API Key", true);
  if (apiKey === "") {
    // User cancelled the key prompt; do not half-connect.
    return;
  }
  const token = await secrets.get(SECRET_TOKEN);

  const resolvedSlug = vscode.workspace.getConfiguration("contextHub").get<string>("workspaceSlug", "").trim();
  const spawnCfg = {
    repoPath: resolveRepoPath(cfg.get<string>("repoPath", "${workspaceFolder}")),
    apiBase: cfg.get<string>("apiBase", "http://localhost:8000"),
    workspaceSlug: resolvedSlug,
    apiKey: apiKey || undefined,
    token: token || undefined,
  };
  await globalState.update("contextHub.lastSlug", resolvedSlug);

  // Tear down any previous bridge, then spawn a fresh one.
  presenceReporter?.dispose();
  presenceReporter = undefined;
  await bridge.current?.shutdown();
  const client = new HubBridgeClient(outputChannel);
  bridge.current = client;

  try {
    await client.start(spawnCfg);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    state.setError(msg);
    const pick = await vscode.window.showErrorMessage(`AI Context Hub: ${msg}`, "Show Output");
    if (pick === "Show Output") {
      outputChannel.show();
    }
    return;
  }

  wireBridgenotifications(client, state, outputChannel);

  try {
    const snap = await client.connect();
    state.applySnapshot(snap, resolvedSlug);
    outputChannel.appendLine(`[hub] connected to '${resolvedSlug}' (${snap.tasks?.length ?? 0} tasks, ${snap.decisions?.length ?? 0} decisions)`);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    state.setError(msg);
    const pick = await vscode.window.showErrorMessage(
      `AI Context Hub: failed to connect to '${resolvedSlug}' — ${msg}`,
      "Show Output",
    );
    if (pick === "Show Output") {
      outputChannel.show();
    }
    return;
  }

  // Start auto-presence once connected.
  presenceReporter = new PresenceReporter(client, outputChannel);
  await presenceReporter.start();
}

function wireBridgenotifications(
  client: HubBridgeClient,
  theState: WorkspaceState,
  outputChannel: vscode.OutputChannel,
): void {
  client.onEvent((frame) => theState.applyEvent(frame));
  client.onSnapshot((snap) => theState.applySnapshot(snap));
  client.onStatus((status) => {
    theState.applyStatus(status);
    outputChannel.appendLine(
      `[hub] status: connected=${status.connected} slug=${status.slug}${status.error ? ` error=${status.error}` : ""}`,
    );
  });
  client.onExit((code) => {
    theState.setConnected(false);
    theState.setError(code === 0 ? undefined : `Bridge exited (code ${code}). Use Connect to restart.`);
  });
}

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel("AI Context Hub");
  state = new WorkspaceState();
  const bridge: BridgeHolder = { current: undefined };

  // Sidebar tree views.
  const tasksProvider = new TasksProvider(state);
  const decisionsProvider = new DecisionsProvider(state);
  const presenceProvider = new PresenceProvider(state);
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("contextHub.tasks", tasksProvider),
    vscode.window.registerTreeDataProvider("contextHub.decisions", decisionsProvider),
    vscode.window.registerTreeDataProvider("contextHub.presence", presenceProvider),
    presenceProvider,
  );

  // Status-bar summary.
  context.subscriptions.push(new SummaryStatusBar(state));

  // Bridge-agnostic commands assembled here (connect/disconnect/output/setup).
  context.subscriptions.push(
    vscode.commands.registerCommand("contextHub.connect", () =>
      connect(bridge, context.secrets, context.globalState, output),
    ),
    vscode.commands.registerCommand("contextHub.disconnect", async () => {
      presenceReporter?.dispose();
      presenceReporter = undefined;
      await bridge.current?.shutdown();
      bridge.current = undefined;
      state.clear();
      state.setConnected(false);
      state.setError(undefined);
      output.appendLine("[hub] disconnected");
    }),
    vscode.commands.registerCommand("contextHub.showOutput", () => output.show()),
    vscode.commands.registerCommand("contextHub.setupMcp", () => setupMcp(output)),
  );

  // Quick actions that need the *current* bridge resolve it lazily via the holder.
  const quickActionBridgeProxy = new Proxy({} as HubBridgeClient, {
    get(_target, prop) {
      const real = bridge.current as unknown as Record<string | symbol, unknown> | undefined;
      if (!real) {
        if (prop === "running") {
          return false;
        }
        return undefined;
      }
      const value = real[prop];
      return typeof value === "function" ? (value as (...args: unknown[]) => unknown).bind(real) : value;
    },
  }) as HubBridgeClient;
  context.subscriptions.push(...registerQuickActions(quickActionBridgeProxy, state, output));

  context.subscriptions.push(output, state, { dispose: () => void bridge.current?.shutdown() });

  output.appendLine("[hub] AI Context Hub extension activated. Run 'AI Context Hub: Connect' to begin.");
}

export function deactivate(): void {
  presenceReporter?.dispose();
  presenceReporter = undefined;
}
