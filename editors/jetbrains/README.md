# AI Context Hub — JetBrains plugin

Minimal IntelliJ-platform plugin that connects any JetBrains IDE to the same
[hub bridge](../../mcp-server/src/bridge.py) the VS Code/Cursor extension uses
(`editors/vscode`). It spawns `uv run python mcp-server/src/bridge.py` and speaks
stdio NDJSON JSON-RPC 2.0, showing Tasks / Decisions / Presence in one tool window.

## Status

**Minimal by design** — this closes the "JetBrains plugin" known-gap with the
smallest useful surface (connect + three live views). It intentionally mirrors the
VS Code extension's `HubBridgeClient`/`state.applyEvent` behavior rather than adding
new UI. CRUD actions (create/complete/delete) ride the same bridge methods and are
trivial to add later.

## Layout

- `src/main/java/dev/erid/hub/`
  - `HubProcess` — spawn/drain/stop the bridge subprocess (mirrors `HubBridgeClient.start/preflight`)
  - `HubRpcClient` — stdio NDJSON JSON-RPC 2.0 (pending-requests map by `id`, 30 s timeout)
  - `BridgeProtocol` — Gson POJOs mirroring `editors/vscode/src/bridge/protocol.ts`
  - `HubPanel` — Tasks/Decisions/Presence tabs fed by snapshot+events (same upsert/remove semantics)
  - `HubState` / `HubToolWindowFactory` / `ConnectAction` — wiring
- `src/main/resources/META-INF/plugin.xml` — tool window + Connect action (Tools menu)

## Build

Requires **JDK 17+** (the 2023.2+ platform; 2024.3 is the compile target and wants 21).

```sh
# One-time, on a machine with gradle ≥ 8 (regenerates the wrapper jar; the repo
# ships only gradle-wrapper.properties, not the binary jar):
gradle wrapper

./gradlew buildPlugin   # packaged plugin in build/distributions/
./gradlew runIde        # sandbox IDE with the plugin installed
```

CI compiles with `./gradlew compileJava` (see `.github/workflows/tests.yml`,
`jetbrains-plugin` job) — `buildPlugin`'s IDE download is heavyweight.

## Notes

- Java package `dev.erid.hub` (repo is **Erid**); JSON via **Gson** (ships with
  the platform — no bundled dependency).
- The bridge needs `uv` resolvable on the IDE's PATH and the opened project to be
  the Erid checkout (or `mcp-server/src/bridge.py` reachable from its base path).
