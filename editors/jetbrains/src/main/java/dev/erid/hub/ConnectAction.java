package dev.erid.hub;

import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.Messages;
import org.jetbrains.annotations.NotNull;

/** Prompts for the hub credential and connects the bridge (Tools → AI Context Hub). */
public final class ConnectAction extends AnAction {
    @Override
    public void actionPerformed(@NotNull AnActionEvent e) {
        Project project = e.getProject();
        if (project == null) return;

        String apiBase = Messages.showInputDialog(
                project, "Hub API base URL:", "AI Context Hub", null, "http://localhost:8000", null);
        if (apiBase == null || apiBase.isBlank()) return;
        String slug = Messages.showInputDialog(project, "Workspace slug:", "AI Context Hub", null);
        if (slug == null || slug.isBlank()) return;
        String apiKey = Messages.showPasswordDialog(project, "Workspace API key:", "AI Context Hub");
        if (apiKey == null) return;

        String repoPath = project.getBasePath();
        try {
            HubState state = HubState.getInstance(project);
            state.getClient().connect(slug, apiBase, apiKey, "", repoPath);
            state.getClient().openWorkspace(slug);
        } catch (Exception ex) {
            Messages.showErrorDialog(project, ex.getMessage(), "AI Context Hub connect failed");
        }
    }
}
