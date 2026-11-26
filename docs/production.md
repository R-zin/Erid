# Running Erid in production

This guide covers how Erid scales, the security controls it ships with, the settings that matter, and the testing behind them, with measured results.

- Kubernetes autoscaling: [`deploy/k8s/README.md`](../deploy/k8s/README.md).
- Single-host Docker Compose: the README's *Public deployment* section.
- Soft-launch checklist: [`softlaunch.md`](softlaunch.md).

## Architecture for scale

```
            clients (Claude Code, Cursor, Codex, dashboard, editors)
                                   │  HTTPS
                     ┌─────────────┴─────────────┐
                     │ Caddy / Ingress (TLS, LB) │
                     └──┬──────────┬──────────┬──┘
                        ▼          ▼          ▼
                     ┌─────┐    ┌─────┐    ┌─────┐   stateless API replicas
                     │ API │    │ API │ …  │ API │   (HPA: 2–8 pods)
                     └──┬──┘    └──┬──┘    └──┬──┘
                        └─────── Postgres ────┘     state, outbox, rate limits,
                                                    audit, LISTEN/NOTIFY fan-out
```

All state lives in Postgres, so any replica can serve any request.

- **Realtime.** Each replica holds one `LISTEN` connection, and every committed event is `NOTIFY`'d to all of them. A WebSocket client on one replica sees writes made through another. Clients reconnect with `?since=<seq>` to replay what they missed.
- **Migrations.** Startup runs `alembic upgrade head` under a Postgres advisory lock. Several replicas booting at once migrate once; without the lock, 4 of 6 concurrent migrators crashed in testing. `ERID_RUN_MIGRATIONS=0` plus `python -m app.migrate` (or the Kubernetes Job) moves this to a release step.
- **Housekeeping.** Outbox pruning, expired rate-limit windows, old audit events and stale claims are cleaned hourly. An advisory lock lets one replica do it per round.

### Probes

- **`GET /health` (liveness).** Never touches dependencies, so a database blip doesn't restart every pod.
- **`GET /ready` (readiness).** Returns 503 unless the database answers *and* the replica's LISTEN connection is up. A replica that can't fan out events leaves rotation instead of serving WebSockets that silently miss events.

### Load shedding and graceful shutdown

- **Load shedding.** Past `ERID_MAX_INFLIGHT_REQUESTS` concurrent requests, a replica answers `503` with `Retry-After: 1`. Past `ERID_MAX_WEBSOCKETS`, new streams are refused with close code 1013. Probes and `/metrics` are never shed. This keeps a saturated replica responsive while the autoscaler adds capacity; see the load test below.
- **Graceful shutdown.** On SIGTERM, uvicorn stops accepting, drains requests for up to 25s, and closes WebSockets with code 1012 ("service restart"). Kubernetes adds a 10s `preStop` so endpoints update first.

### Autoscaling

- **Kubernetes.** An HPA scales on CPU and memory: fast out, slow in. An optional HPA also scales on in-flight requests and WebSocket count per pod, via prometheus-adapter.
- **Compose.** Run `ERID_API_REPLICAS` replicas behind Caddy, which re-resolves them, balances on least connections and retries another replica on failure. Compose doesn't autoscale.

### Database connections

Each replica uses up to `ERID_DB_POOL_SIZE + ERID_DB_MAX_OVERFLOW` connections, plus 1 for LISTEN. Budget that against Postgres `max_connections`, or put PgBouncer in transaction mode in front (`ERID_DB_PGBOUNCER=1`) and give LISTEN and the migration lock a direct connection (`ERID_DIRECT_DATABASE_URL`).

## Security controls

| Control | What it does |
| --- | --- |
| Production mode (`ERID_ENV=production`) | Refuses to start with open workspaces, a missing or short admin token, no stable JWT keypair (tokens must verify on every replica), OAuth without a session secret, CORS `*`, or rate limits off. Development logs the same problems as warnings. Interactive docs are off unless `ERID_EXPOSE_DOCS=1`. |
| Operator-only provisioning | `ERID_ADMIN_TOKEN` gates `POST /api/workspaces`. `ERID_PUBLIC_WORKSPACE_DIRECTORY=0` hides the workspace list. |
| Token binding | Workspace-key JWTs carry the workspace id and a fingerprint of the key. Rotating the key, or deleting the workspace, kills them, and they never work on a new workspace that reuses the slug. |
| Rate limits | **Shared across replicas** (Postgres counters): key→token login, provisioning, claiming and OAuth, per client IP (`ERID_RATE_LIMIT_AUTH`). **Per replica**: general REST and MCP traffic per workspace and credential (`ERID_RATE_LIMIT_API`). 429 with `Retry-After`. |
| Brute-force lockout | After `ERID_RATE_LIMIT_AUTH_FAILURES` rejected credentials, a client is refused for the rest of the window before further guesses are evaluated. Applies to REST, MCP, WebSockets and login. Valid requests pay no database round trip for this. |
| Audit trail | `GET /api/workspaces/{slug}/audit` (admins): provisioning, claiming, key rotation, deletion, actor create/revoke, token issued/denied, OAuth login/invite, rejected credentials, secret findings. Each entry has the client IP and outcome. Kept `ERID_AUDIT_RETENTION_DAYS` days; never visible to a workspace that reuses a slug. |
| Secret scanning | Text written to tasks, decisions, handoffs, presence and claims is scanned for credentials (AWS, GitHub, Anthropic, OpenAI, Slack, Stripe, Google, npm, private keys, JWTs, URL passwords, bearer headers). They're redacted (default) or the write is rejected (`ERID_SECRET_SCANNING=reject`). Findings are audited by rule, never by value. |
| Input limits | Every field has a length limit matching its column; slugs are validated; NUL characters are refused; bodies over `ERID_MAX_BODY_BYTES` get 413; offsets are bounded. Validation errors never echo the input. |
| Headers | API responses get `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, a `default-src 'none'` CSP, and HSTS over HTTPS. |
| Origin checks | `/mcp` (per the MCP spec, against DNS rebinding) and WebSocket handshakes (cross-site hijacking) refuse browser origins outside `CORS_ORIGINS`. CLI and editor clients send no Origin and are unaffected. |
| Log hygiene | `api_key`, `token`, `code` and `state` query values are redacted from access logs. MCP errors never include driver or SQL text. |
| Containers | Non-root, read-only root filesystem, all capabilities dropped, seccomp `RuntimeDefault`, `restricted` Pod Security, NetworkPolicies. |
| Supply chain | CI audits locked Python dependencies (pip-audit) and the dashboard's runtime npm dependencies. |

## File claims

Agents claim paths before editing them, and an overlapping claim held by someone else is reported with who holds it and why. Claims are advisory: they coordinate, they don't block writes. See [Research](#research-behind-the-features) for the projects this follows.

- **What can be claimed.** Files, directories (`src/auth/`) or globs (`src/**/*.py`). Each claim has a time limit (1 minute to 24 hours), is exclusive or shared, and has an optional reason and task. Claiming again renews it.
- **REST.** `POST /claims`, `GET /claims`, `POST /claims/check`, `POST /claims/release`, `DELETE /claims/{id}`.
- **MCP tools.** `claim_files`, `release_files`, `list_claims`, `check_files`.
- **Pre-commit hook.** Have it call `POST /claims/check` with the staged files, and fail when `claimed_by_others` is true.
- **Races.** Concurrent claims for the same path have exactly one winner. In testing, 12 agents racing on one replica and 9 spread across three replicas each produced one winner; without the lock, all 12 won.

## Testing

Run everything with:

```bash
uv run pytest                                                     # SQLite
ERID_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/erid_test \
  EVENT_BUS_BACKEND=memory uv run pytest                          # Postgres (+14 Postgres-only tests)
```

| Suite | What it proves |
| --- | --- |
| `test_api_fuzz.py` | Every REST operation receives about 30 hostile variants (huge, empty, NUL, emoji and injection strings; absurd numbers; wrong types; bad UUIDs; unknown fields; raw garbage bodies) with an owner credential. Any 5xx fails. |
| `test_mcp_fuzz.py` | Every MCP tool receives hostile arguments; errors must not leak internals. |
| `test_properties.py` | Hypothesis properties for path rules, overlap, redaction, log redaction and limit parsing. |
| `test_hardening_bugs.py` | Regressions for every bug this work found (below), tenant isolation, and a sweep that every workspace route refuses anonymous callers. |
| `test_security_hardening.py`, `test_secret_scanning.py`, `test_claims.py`, `test_scaling.py` | The controls and features above. |
| `test_migrations.py` | The migrated schema matches the models; new migrations downgrade and re-apply. |
| `test_multi_instance.py` | Three real uvicorn processes booted at once on a fresh database. Covers racing migrations, cross-replica WebSocket fan-out, tokens valid on every replica, shared rate limit and lockout, a claim race decided once, recovery after every LISTEN connection is killed, and SIGTERM closing WebSockets with 1012. |
| `test_deploy_manifests.py` | Kubernetes and Compose consistency: selectors, HPA targets, probe ports, security context, grace period, ConfigMap keys, connection budget. CI also runs kubeconform. |

CI additionally:

- runs a load smoke test against a live API, failing on any error or lost realtime event;
- starts the production Compose overlay with 3 replicas behind Caddy, in production mode, to verify TLS, headers, operator-only provisioning, cross-replica events, and scaling 3 → 1 → 4.

### Bugs found by this testing (all fixed, all with regression tests)

1. Over-long values for many fields reached Postgres and returned **500** (for example a 600-character `assigned_to`).
2. Workspace-key JWTs **survived key rotation** and carried over to a **new workspace reusing the slug**.
3. Concurrent startup migrations **crashed 4 of 6 replicas**.
4. `offset=2**63` overflowed the database integer (500).
5. A lone UTF-16 surrogate in JSON made the 422 response unencodable (500).
6. NUL characters in bodies, paths or queries reached Postgres (500).
7. MCP tool errors **exposed raw asyncpg/SQLAlchemy messages**.
8. The event bus could **silently fall back to in-process delivery**, dropping cross-replica events.
9. `GET /tasks` had no limit.

### Load test results

Measured with `scripts/loadtest.py` on a single 4-core VM that also ran Postgres and the load generators. Real deployments give each replica its own cores, so read these as relative numbers.

| Scenario | Successful req/s | p50 | p95 | p99 | Errors | Realtime delivery |
| --- | --- | --- | --- | --- | --- | --- |
| 60 agents, 1 replica | 175 | 289 ms | 943 ms | 1.49 s | 0 | 581/581 |
| 60 agents, 3 replicas | 279 (+60%) | 170 ms | 577 ms | 798 ms | 0 | 910/910 |
| 150 agents, 1 replica, no shedding | 194 | 739 ms | 2.42 s | 3.82 s | 0 | 575/575 |
| 150 agents, 1 replica, shedding at 24 in flight | 163 (+11.5k fast 503s) | 270 ms | 762 ms | 1.23 s | 3 connection resets / 14.8k | 499/499 |

What the numbers say:

- **Per-replica capacity.** One replica tops out at roughly 170–200 req/s of this mix, CPU-bound at about 5ms of Python per request. Plan around 150 req/s per replica (about 1 vCPU) and let the HPA add replicas; its 70% CPU target leaves headroom.
- **Scaling out works.** Three replicas cut p99 latency nearly in half even while sharing the same 4 cores. Realtime delivery was 100% in every run, with p95 fan-out under 140ms across replicas.
- **Load shedding protects latency.** Under 2.5× overload, refusing the excess immediately kept accepted requests about 3× faster at p95 and p99, at the cost of about 15% throughput (CPU spent on 503s). Clients that honour `Retry-After` (the bundled clients do) back off instead of piling on.

## Research behind the features

| Source | Takeaway for Erid |
| --- | --- |
| [MCP Agent Mail](https://github.com/Dicklesworthstone/mcp_agent_mail): advisory, TTL'd, exclusive or shared file reservations with a pre-commit guard | File claims |
| [CoordMCP](https://glama.ai/mcp/servers/siddiquesahabaj/CoordMCP) and [agent-orchestration](https://github.com/madebyaris/agent-orchestration): file locking and resource locks next to shared memory and decision tracking | File claims are the coordination primitive Erid lacked |
| [Shared memory for multiple AI coding agents](https://dev.to/alfredoizjr/shared-memory-for-multiple-ai-coding-agents-what-they-already-share-and-what-they-dont-3p7f) | Shared state is fed straight into prompts → secret scanning |
| [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization); [Checkmarx](https://checkmarx.com/learn/mcp-security-risks-real-world-incidents-and-security-controls/), [Corgea](https://corgea.com/learn/mcp-security-best-practices) and [Practical DevSecOps](https://www.practical-devsecops.com/mcp-security-vulnerabilities/) MCP security guides | Origin validation, least privilege, log tool use with caller identity (audit trail), never leak internals |
| [OpenRouter secret formats](https://openrouter.ai/docs/guides/features/guardrails/secret-formats); gitleaks rules | Secret-scanning patterns (prefix-anchored to keep false positives rare) |
| [Render FastAPI production practices](https://render.com/articles/fastapi-production-best-practices); [HPA for FastAPI](https://dev.to/ptp2308/setting-up-kubernetes-hpa-for-a-fastapi-application-made-easy-4ncn) | One process per container, migrations not racing on boot, HPA with stabilization |
| [Postgres vs Redis for rate limits](https://codenote.net/en/posts/rate-limit-storage-postgresql-vs-redis/); [Redis rate-limiting patterns](https://redis.io/tutorials/howtos/ratelimiting/) | Fixed-window counters in Postgres for low-volume auth routes (no new stateful service); in-memory for high-volume routes |

### Not done yet

- **OAuth 2.1 resource-server auth for `/mcp`.** The spec's Protected Resource Metadata (RFC 9728). Today MCP clients use API keys or JWTs in headers, which every major client supports.
- **Semantic (embedding) search.** Postgres full-text and trigram search remain.
- **Error reporting** (Sentry or similar) and distributed tracing.
- **Dev-tool CVEs in the dashboard toolchain.** vite and vitest need upgrading; the shipped dashboard is clean. npm 10.9.9 crashes resolving the upgrade, so it needs a newer npm.
