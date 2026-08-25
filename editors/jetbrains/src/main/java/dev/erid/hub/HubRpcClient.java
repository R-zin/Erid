package dev.erid.hub;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.intellij.openapi.diagnostic.Logger;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Scanner;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;

/**
 * Client for the Python hub bridge mirroring the VS Code {@code HubBridgeClient}:
 * NDJSON JSON-RPC 2.0 over the bridge subprocess's stdio. Responses correlate by
 * {@code id}; id-less frames route to the {@code event}/{@code snapshot}/{@code status}
 * listeners. Request timeout 30 s (mirrors the extension).
 */
public final class HubRpcClient implements AutoCloseable {
    private static final Logger LOG = Logger.getInstance(HubRpcClient.class);
    private static final Gson GSON = new Gson();
    private static final long REQUEST_TIMEOUT_SECS = 30;

    private final HubProcess hubProcess;
    private final Map<Long, CompletableFuture<JsonObject>> pending = new ConcurrentHashMap<>();
    private final AtomicLong nextId = new AtomicLong(1);

    private Process process;
    private BufferedWriter stdin;
    private Thread reader;

    public Consumer<BridgeProtocol.EventFrame> onEvent = f -> {};
    public Consumer<BridgeProtocol.Snapshot> onSnapshot = s -> {};
    public Consumer<BridgeProtocol.StatusFrame> onStatus = s -> {};
    public Consumer<Integer> onExit = code -> {};

    public HubRpcClient(String repoPath) {
        this.hubProcess = new HubProcess(repoPath);
    }

    public boolean isRunning() {
        return hubProcess.isRunning();
    }

    /** Pre-flight and spawn the bridge, then start the NDJSON reader. */
    public synchronized void connect(
            String slug,
            String apiBase,
            String apiKey,
            String token,
            String repoPath) throws IOException {
        if (isRunning()) return;
        String err = hubProcess.preflightError(apiBase);
        if (err != null) {
            throw new IOException(err);
        }
        Map<String, String> env = Map.of(
                "API_BASE", apiBase,
                "WORKSPACE_SLUG", slug == null ? "" : slug,
                "WORKSPACE_API_KEY", apiKey == null ? "" : apiKey,
                "WORKSPACE_TOKEN", token == null ? "" : token);
        process = hubProcess.start(env);
        stdin = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
        startReader();
    }

    /** Send {@code connect} so the bridge starts its WS supervisor and returns a snapshot. */
    public CompletableFuture<BridgeProtocol.Snapshot> openWorkspace(String slug) {
        JsonObject params = new JsonObject();
        if (slug != null && !slug.isEmpty()) params.addProperty("slug", slug);
        return request("connect", params)
                .thenApply(j -> GSON.fromJson(j.get("result"), BridgeProtocol.Snapshot.class));
    }

    public CompletableFuture<JsonObject> request(String method, JsonObject params) {
        if (!isRunning() || stdin == null) {
            return CompletableFuture.failedFuture(
                    new IllegalStateException("bridge is not running (connect first)"));
        }
        long id = nextId.getAndIncrement();
        JsonObject req = new JsonObject();
        req.addProperty("jsonrpc", "2.0");
        req.addProperty("id", id);
        req.addProperty("method", method);
        if (params != null) req.add("params", params);

        CompletableFuture<JsonObject> fut = new CompletableFuture<JsonObject>()
                .orTimeout(REQUEST_TIMEOUT_SECS, TimeUnit.SECONDS);
        pending.put(id, fut);
        try {
            stdin.write(GSON.toJson(req));
            stdin.write("\n");
            stdin.flush();
        } catch (IOException e) {
            pending.remove(id);
            fut.completeExceptionally(e);
        }
        return fut;
    }

    private void startReader() {
        reader = new Thread(() -> {
            try (Scanner sc = new Scanner(process.getInputStream(), StandardCharsets.UTF_8)
                    .useDelimiter("\n")) {
                while (sc.hasNext()) {
                    handleLine(sc.next());
                }
            } catch (Exception e) {
                LOG.debug("[hub] reader stopped", e);
            }
            Integer code = process.isAlive() ? null : process.exitValue();
            failAll(new IOException("bridge exited (code " + code + ")"));
            onExit.accept(code);
        });
        reader.setDaemon(true);
        reader.start();
    }

    private void handleLine(String raw) {
        String text = raw.trim();
        if (text.isEmpty()) return;
        JsonObject msg;
        try {
            msg = JsonParser.parseString(text).getAsJsonObject();
        } catch (Exception e) {
            LOG.warn("[hub] dropping unparseable line: " + text);
            return;
        }
        if (msg.has("id") && !msg.get("id").isJsonNull()) {
            CompletableFuture<JsonObject> fut = pending.remove(msg.get("id").getAsLong());
            if (fut == null) {
                LOG.warn("[hub] response for unknown id " + msg.get("id"));
                return;
            }
            if (msg.has("error") && !msg.get("error").isJsonNull()) {
                JsonObject error = msg.getAsJsonObject("error");
                fut.completeExceptionally(new IOException(
                        "bridge error " + error.get("code") + ": " + error.get("message").getAsString()));
            } else {
                fut.complete(msg);
            }
            return;
        }
        // Notification (no id): route by method.
        String method = msg.has("method") ? msg.get("method").getAsString() : "";
        switch (method) {
            case "event" -> {
                JsonObject params = msg.getAsJsonObject("params");
                JsonObject frame = params != null && params.has("event")
                        ? params.getAsJsonObject("event")
                        : params;
                onEvent.accept(GSON.fromJson(frame, BridgeProtocol.EventFrame.class));
            }
            case "snapshot" -> onSnapshot.accept(
                    GSON.fromJson(msg.get("params"), BridgeProtocol.Snapshot.class));
            case "status" -> onStatus.accept(
                    GSON.fromJson(msg.get("params"), BridgeProtocol.StatusFrame.class));
            default -> LOG.warn("[hub] unknown notification: " + text);
        }
    }

    private void failAll(Throwable t) {
        pending.values().forEach(f -> f.completeExceptionally(t));
        pending.clear();
    }

    @Override
    public synchronized void close() {
        try {
            if (isRunning()) {
                request("shutdown", new JsonObject());
            }
        } catch (Exception ignored) {
            // The bridge may exit before answering; treat as success.
        }
        hubProcess.stop();
        failAll(new IOException("bridge closed"));
    }
}
