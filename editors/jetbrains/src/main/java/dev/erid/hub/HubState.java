package dev.erid.hub;

import com.intellij.openapi.Disposable;
import com.intellij.openapi.components.Service;
import com.intellij.openapi.project.Project;
import com.intellij.util.concurrency.AppExecutorUtil;

/** Per-project holder for the bridge client so Connect + the tool window share one. */
@Service(Service.Level.PROJECT)
public final class HubState implements Disposable {
    private final HubRpcClient client;
    private HubPanel panel;

    public HubState(Project project) {
        String repoPath = project.getBasePath();
        client = new HubRpcClient(repoPath);
        client.onSnapshot = snap -> runOnEdt(() -> { if (panel != null) panel.applySnapshot(snap); });
        client.onEvent = frame -> runOnEdt(() -> { if (panel != null) panel.applyEvent(frame); });
    }

    public static HubState getInstance(Project project) {
        return project.getService(HubState.class);
    }

    public HubRpcClient getClient() {
        return client;
    }

    public void setPanel(HubPanel panel) {
        this.panel = panel;
    }

    private void runOnEdt(Runnable r) {
        AppExecutorUtil.getAppExecutorService().execute(() ->
                com.intellij.openapi.application.ApplicationManager.getApplication().invokeLater(r));
    }

    @Override
    public void dispose() {
        client.close();
    }
}
