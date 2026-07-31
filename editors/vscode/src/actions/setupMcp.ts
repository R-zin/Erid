import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";

const SERVER_NAME = "context-hub";

/**
 * Build the MCP server entry shared by the VS Code and Cursor config shapes.
 * Secret values are left blank by default so the user pastes the key themselves.
 */
function serverEntry(apiBase: string, slug: string): Record<string, unknown> {
  return {
    command: "uv",
    args: ["run", "python", "mcp-server/src/server.py", "--transport", "stdio"],
    env: {
      API_BASE: apiBase,
      WORKSPACE_SLUG: slug,
      WORKSPACE_API_KEY: "",
      WORKSPACE_TOKEN: "",
    },
  };
}

/** Read a JSON file tolerantly; returns `{}` when missing or unparseable. */
function readJson(file: string): Record<string, unknown> {
  try {
    const raw = fs.readFileSync(file, "utf8");
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** Merge-write `config[topKey][SERVER_NAME] = entry`, preserving other entries. */
function mergeWrite(file: string, topKey: string, entry: Record<string, unknown>): void {
  const config = readJson(file);
  const existing = (config[topKey] as Record<string, unknown> | undefined) ?? {};
  existing[SERVER_NAME] = entry;
  config[topKey] = existing;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(config, null, 2) + "\n", "utf8");
}

/**
 * `contextHub.setupMcp` command.
 *
 * Merge-writes `<workspaceFolder>/.vscode/mcp.json` (top-level `"servers"`) with the
 * context-hub MCP server pointing at `mcp-server/src/server.py`. Existing entries are
 * preserved. Optionally also writes a Cursor config (`.cursor/mcp.json`, top-level
 * `"mcpServers"`) when the user opts in. Prompts to reload the window afterward.
 */
export async function setupMcp(output: vscode.OutputChannel): Promise<void> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    vscode.window.showErrorMessage("AI Context Hub: open a workspace folder before setting up MCP.");
    return;
  }
  const cfg = vscode.workspace.getConfiguration("contextHub");
  const apiBase = cfg.get<string>("apiBase", "http://localhost:8000");
  const slug = cfg.get<string>("workspaceSlug", "");
  const entry = serverEntry(apiBase, slug);

  const vscodeFile = path.join(folder.uri.fsPath, ".vscode", "mcp.json");
  try {
    mergeWrite(vscodeFile, "servers", entry);
    output.appendLine(`[setupMcp] wrote ${vscodeFile}`);
  } catch (err) {
    vscode.window.showErrorMessage(`AI Context Hub: failed to write .vscode/mcp.json — ${err instanceof Error ? err.message : String(err)}`);
    return;
  }

  // Gate any Cursor write behind a QuickPick until its `mcpServers` shape is verified.
  const target = await vscode.window.showQuickPick(
    [
      { label: "$(check) VS Code only", detail: "wrote .vscode/mcp.json", cursor: false },
      { label: "Also write Cursor config", detail: ".cursor/mcp.json (mcpServers) — preview/verify", cursor: true },
    ],
    { placeHolder: "VS Code MCP config written. Also configure Cursor?", ignoreFocusOut: true },
  );

  let wroteCursor = false;
  if (target?.cursor) {
    const cursorFile = path.join(folder.uri.fsPath, ".cursor", "mcp.json");
    try {
      mergeWrite(cursorFile, "mcpServers", entry);
      wroteCursor = true;
      output.appendLine(`[setupMcp] wrote ${cursorFile}`);
    } catch (err) {
      vscode.window.showWarningMessage(`AI Context Hub: failed to write .cursor/mcp.json — ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  const files = [".vscode/mcp.json", ...(wroteCursor ? [".cursor/mcp.json"] : [])].join(" and ");
  const choice = await vscode.window.showInformationMessage(
    `AI Context Hub: wrote ${files}. Add your WORKSPACE_API_KEY, then reload to start the MCP server.`,
    "Reload Window",
    "Open Config",
  );
  if (choice === "Reload Window") {
    await vscode.commands.executeCommand("workbench.action.reloadWindow");
  } else if (choice === "Open Config") {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(vscodeFile));
    await vscode.window.showTextDocument(doc, { preview: false });
  }
}
