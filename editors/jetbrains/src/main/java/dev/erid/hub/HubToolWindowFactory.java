package dev.erid.hub;

import com.intellij.openapi.project.Project;
import com.intellij.openapi.wm.ToolWindow;
import com.intellij.openapi.wm.ToolWindowFactory;
import com.intellij.ui.content.Content;
import org.jetbrains.annotations.NotNull;

/** Registers the single AI Context Hub tool window. */
public final class HubToolWindowFactory implements ToolWindowFactory {
    @Override
    public void createToolWindowContent(@NotNull Project project, @NotNull ToolWindow toolWindow) {
        HubPanel panel = new HubPanel(project);
        HubState.getInstance(project).setPanel(panel);
        Content content = toolWindow.getContentManager()
                .getFactory()
                .createContent(panel.getComponent(), "", false);
        toolWindow.getContentManager().addContent(content);
    }
}
