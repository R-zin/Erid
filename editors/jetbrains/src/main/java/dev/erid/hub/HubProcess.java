package dev.erid.hub;

import com.intellij.openapi.diagnostic.Logger;
import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * Owns the {@code uv run python mcp-server/src/bridge.py} subprocess the same way the
 * VS Code extension's {@code HubBridgeClient.start} does: cwd = the repo holding
 * {@code mcp-server/src/bridge.py}, hub credentials passed in the environment,
 * stderr folded into the IDE log (stdout is the JSON-RPC channel).
 */
public final class HubProcess {
    private static final Logger LOG = Logger.getInstance(HubProcess.class);

    private final String repoPath;
    private Process process;

    public HubProcess(String repoPath) {
        this.repoPath = repoPath;
    }

    /** Pre-flight: {@code uv} resolvable and the repo holds the bridge + root pyproject. */
    public String preflightError(String apiBase) {
        if (repoPath == null || repoPath.isEmpty()) {
            return "No repository path configured — open the Erid checkout (needs mcp-server/).";
        }
        File bridge = new File(repoPath, "mcp-server/src/bridge.py");
        if (!bridge.isFile()) {
            return "No hub bridge at " + bridge + " — point the plugin at the repo root containing mcp-server/.";
        }
        if (!new File(repoPath, "pyproject.toml").isFile()) {
            return "No pyproject.toml in " + repoPath + " — `uv run` needs the repo root.";
        }
        if (apiBase == null || apiBase.isEmpty()) {
            return "No hub API base URL configured (API_BASE, e.g. http://localhost:8000).";
        }
        return null;
    }

    /** Spawn the bridge; throws {@link IOException} when the process cannot start. */
    public synchronized Process start(Map<String, String> env) throws IOException {
        ProcessBuilder pb = new ProcessBuilder("uv", "run", "python", "mcp-server/src/bridge.py");
        pb.directory(new File(repoPath));
        pb.environment().putAll(env);
        pb.redirectErrorStream(false);
        process = pb.start();
        LOG.info("[hub] spawned bridge (cwd=" + repoPath + ")");
        drainStderr(process);
        return process;
    }

    public synchronized boolean isRunning() {
        return process != null && process.isAlive();
    }

    /** Ask for a clean shutdown, then hard-kill if it does not exit promptly. */
    public synchronized void stop() {
        if (process == null) return;
        process.destroy();
        try {
            if (!process.waitFor(5, TimeUnit.SECONDS)) {
                process.destroyForcibly();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
        }
        process = null;
    }

    private void drainStderr(Process p) {
        Thread t = new Thread(() -> {
            try (BufferedReader r =
                    new BufferedReader(new InputStreamReader(p.getErrorStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = r.readLine()) != null) {
                    LOG.info("[hub:bridge] " + line);
                }
            } catch (IOException e) {
                LOG.debug("[hub] bridge stderr closed", e);
            }
        });
        t.setDaemon(true);
        t.start();
    }
}
