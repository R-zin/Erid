package dev.erid.hub;

import com.google.gson.Gson;
import com.intellij.openapi.diagnostic.Logger;
import com.intellij.openapi.project.Project;
import com.intellij.ui.components.JBList;
import com.intellij.ui.components.JBScrollPane;
import com.intellij.ui.components.JBTabbedPane;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;
import javax.swing.DefaultListModel;
import javax.swing.JComponent;

/**
 * One tool window with Tasks/Decisions/Presence tabs. Fed by the bridge's snapshot
 * + event stream; event application mirrors the VS Code extension's
 * {@code state.applyEvent} (upsert by id; remove by id on the {@code *_deleted}
 * events; prepend decisions).
 */
public final class HubPanel {
    private static final Logger LOG = Logger.getInstance(HubPanel.class);
    private static final Gson GSON = new Gson();

    private final Project project;
    private final JBTabbedPane tabs = new JBTabbedPane();
    private final DefaultListModel<String> tasksModel = new DefaultListModel<>();
    private final DefaultListModel<String> decisionsModel = new DefaultListModel<>();
    private final DefaultListModel<String> presenceModel = new DefaultListModel<>();

    private List<BridgeProtocol.TaskOut> tasks = new ArrayList<>();
    private List<BridgeProtocol.DecisionOut> decisions = new ArrayList<>();
    private List<BridgeProtocol.PresenceOut> presence = new ArrayList<>();

    public HubPanel(Project project) {
        this.project = project;
        tabs.addTab("Tasks", new JBScrollPane(new JBList<>(tasksModel)));
        tabs.addTab("Decisions", new JBScrollPane(new JBList<>(decisionsModel)));
        tabs.addTab("Presence", new JBScrollPane(new JBList<>(presenceModel)));
    }

    public JComponent getComponent() {
        return tabs;
    }

    /** Replace all state from an authoritative snapshot (initial or post-reconnect). */
    public void applySnapshot(BridgeProtocol.Snapshot snap) {
        if (snap == null) return;
        tasks = snap.tasks != null ? new ArrayList<>(snap.tasks) : new ArrayList<>();
        decisions = snap.decisions != null ? new ArrayList<>(snap.decisions) : new ArrayList<>();
        presence = snap.presence != null ? new ArrayList<>(snap.presence) : new ArrayList<>();
        refresh();
    }

    /** Apply one live event. Unknown types (incl. the server {@code ping}) are ignored. */
    public void applyEvent(BridgeProtocol.EventFrame frame) {
        if (frame == null || frame.type == null) return;
        switch (frame.type) {
            case "task_created", "task_updated" -> {
                BridgeProtocol.TaskOut t = GSON.fromJson(frame.data, BridgeProtocol.TaskOut.class);
                tasks = upsertBy(tasks, t, x -> x.id.equals(t.id));
            }
            case "task_deleted" -> {
                String id = frame.data.get("id").getAsString();
                tasks = tasks.stream().filter(t -> !t.id.equals(id)).collect(Collectors.toList());
            }
            case "decision_created" -> {
                BridgeProtocol.DecisionOut d = GSON.fromJson(frame.data, BridgeProtocol.DecisionOut.class);
                List<BridgeProtocol.DecisionOut> next = new ArrayList<>();
                next.add(d);
                next.addAll(decisions.stream().filter(x -> !x.id.equals(d.id)).toList());
                decisions = next;
            }
            case "decision_deleted" -> {
                String id = frame.data.get("id").getAsString();
                decisions = decisions.stream().filter(d -> !d.id.equals(id)).collect(Collectors.toList());
            }
            case "presence_updated" -> {
                BridgeProtocol.PresenceOut p = GSON.fromJson(frame.data, BridgeProtocol.PresenceOut.class);
                presence = upsertBy(presence, p, x -> x.id.equals(p.id));
            }
            case "workspace_deleted" -> LOG.info("[hub] workspace was deleted: " + frame.workspace);
            default -> LOG.debug("[hub] ignoring event type " + frame.type);
        }
        refresh();
    }

    private void refresh() {
        tasksModel.clear();
        tasks.forEach(t -> tasksModel.addElement("[" + t.status + "] " + t.title
                + (t.assigned_to != null ? " @" + t.assigned_to : "")));
        decisionsModel.clear();
        decisions.forEach(d -> decisionsModel.addElement(
                d.title + (d.made_by != null ? " — " + d.made_by : "")));
        presenceModel.clear();
        presence.forEach(p -> presenceModel.addElement(
                p.actor_name + (p.current_task != null ? " → " + p.current_task : "")));
    }

    private static <T> List<T> upsertBy(List<T> list, T item, java.util.function.Predicate<T> match) {
        List<T> next = new ArrayList<>();
        boolean replaced = false;
        for (T x : list) {
            if (match.test(x)) {
                next.add(item);
                replaced = true;
            } else {
                next.add(x);
            }
        }
        if (!replaced) next.add(item);
        return next;
    }
}
