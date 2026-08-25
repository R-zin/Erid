package dev.erid.hub;

import com.google.gson.JsonObject;
import java.util.List;

/** Wire types mirroring {@code editors/vscode/src/bridge/protocol.ts} (Gson POJOs). */
public final class BridgeProtocol {
    private BridgeProtocol() {}

    /** JSON-RPC error codes (subset of the spec the bridge emits). */
    public static final class RpcError {
        public static final int PARSE_ERROR = -32700;
        public static final int METHOD_NOT_FOUND = -32601;
        public static final int BAD_PARAMS = -32602;
        /** The hub bridge maps {@link #HTTP_STATUS} onto this; {@code data.status} carries it. */
        public static final int SERVER = -32000;
        private RpcError() {}
    }

    public static final class TaskOut {
        public String id;
        public String title;
        public String status;
        public String assigned_to;
    }

    public static final class DecisionOut {
        public String id;
        public String title;
        public String reason;
        public String made_by;
        public String created_at;
        public String task_id;
    }

    public static final class PresenceOut {
        public String id;
        public String actor_name;
        public String actor_type;
        public String current_file;
        public String current_task;
    }

    public static final class WorkspaceSummary {
        public String slug;
        public String name;
        public int task_count;
        public int open_task_count;
        public int decision_count;
        public List<String> active_developers;
    }

    /** A raw {@code {workspace,type,data}} frame forwarded 1:1 from the hub WS. */
    public static final class EventFrame {
        public String workspace;
        public String type;
        public JsonObject data;
    }

    /** Authoritative state pushed by the bridge after a (re)connect. */
    public static final class Snapshot {
        public WorkspaceSummary summary;
        public List<TaskOut> tasks;
        public List<DecisionOut> decisions;
        public List<PresenceOut> presence;
    }

    public static final class StatusFrame {
        public boolean connected;
    }
}
