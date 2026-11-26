# Erid on Kubernetes (autoscaling)

`base/` deploys the API and the dashboard with horizontal autoscaling:

| Object | What it does |
| --- | --- |
| `api` Deployment | Non-root, read-only root filesystem, every capability dropped. Spread across nodes and zones. Rolling updates never drop below the current replica count. |
| `api` HPA | 2–8 pods. Scales on CPU (70% of requests) and memory (80%). Scales out quickly (up to 2× every 30s) and in slowly (1 pod/min after a 5-minute calm). |
| `api` PDB | Keeps at least 1 API pod during node drains and upgrades. |
| `web` Deployment / HPA / PDB | The dashboard (unprivileged nginx), 2–6 pods. |
| Ingress | TLS via cert-manager. `/api` and `/mcp` go to the API, everything else to the dashboard. `/metrics`, `/ready` and `/docs` are not exposed. |
| NetworkPolicy | Only the ingress controller, the dashboard and Prometheus can reach the API. |
| Namespace | Enforces the `restricted` Pod Security Standard. |

Postgres is not included: use a managed Postgres (RDS, Cloud SQL, Azure, Neon…) or an operator such as CloudNativePG.

## Deploy

```bash
# 1. Images (the release workflow pushes them to GHCR on a v* tag), or build your own:
docker build -t ghcr.io/<you>/erid-api:v0.1.0 api && docker push ghcr.io/<you>/erid-api:v0.1.0
docker build -t ghcr.io/<you>/erid-web:v0.1.0 web && docker push ghcr.io/<you>/erid-web:v0.1.0
#    ...and point `images:` in base/kustomization.yaml at them.

# 2. Secrets (see optional/secret.example.yaml for every key)
kubectl create namespace erid
kubectl -n erid create secret generic erid-secrets --from-env-file=erid-secrets.env

# 3. Set your domain in base/ingress.yaml, then:
kubectl apply -k deploy/k8s/base
kubectl -n erid rollout status deploy/api
```

Production mode (`ERID_ENV=production`, set in the ConfigMap) refuses to start with an unsafe configuration. Check the pod logs if a rollout doesn't become ready.

## How scaling behaves

- **Stateless replicas.** All state lives in Postgres. Realtime events fan out across pods over Postgres `LISTEN/NOTIFY`, so a WebSocket client on pod A sees writes made through pod B.
- **Readiness.** `/ready` checks the database and the pod's LISTEN connection. A pod that loses either leaves the Service until it reconnects. Liveness (`/health`) never checks dependencies, so a database blip doesn't restart every pod.
- **Load shedding.** Past `ERID_MAX_INFLIGHT_REQUESTS` concurrent requests a pod returns `503` with `Retry-After: 1`. Past `ERID_MAX_WEBSOCKETS` it refuses new streams with close code 1013. A saturated pod therefore degrades quickly while the HPA adds pods.
- **Scale-in and rollouts.** `preStop` waits 10s for endpoints to update. Uvicorn then drains requests for up to 25s and closes WebSockets with code 1012. Clients reconnect to another pod with `?since=<seq>` and replay what they missed.
- **Migrations.** Pods run `alembic upgrade head` at startup, serialized by a Postgres advisory lock, so a rollout of N pods migrates once. To migrate once per release instead, run `optional/migrate-job.yaml` and set `ERID_RUN_MIGRATIONS: "0"`. Either way, keep migrations backward compatible (expand, then contract): old and new pods overlap during a rollout.

## Connection budget

Each API pod holds up to `ERID_DB_POOL_SIZE + ERID_DB_MAX_OVERFLOW` connections plus one for LISTEN. The defaults (5 + 5 + 1, at most 8 pods) total 88, under Postgres' default `max_connections` of 100. To go further:

1. Put PgBouncer in **transaction** mode in front of Postgres.
2. Point `DATABASE_URL` at PgBouncer and set `ERID_DB_PGBOUNCER=1`.
3. Set `ERID_DIRECT_DATABASE_URL` to Postgres itself. LISTEN and the migration lock need a real session.
4. Raise `maxReplicas`.

## Scaling on load instead of CPU

Agents hold WebSockets open and make many small requests, so CPU can lag behind real load. With Prometheus and prometheus-adapter installed, apply `optional/api-hpa-custom-metrics.yaml`. It also scales on average in-flight requests and WebSocket connections per pod. `optional/servicemonitor.yaml` sets up scraping for the Prometheus Operator.

## Metrics worth alerting on

| Metric | Alert when |
| --- | --- |
| `erid_load_shed_total` | increasing: pods are saturated faster than the HPA adds them; raise `maxReplicas` or the limits. |
| `erid_event_bus_connected == 0` | for > 1 min: realtime fan-out is down on that pod. |
| `erid_rate_limited_total` | spikes: abuse, or limits too tight. |
| `erid_auth_failures_total` | spikes: credential stuffing. |
| `histogram_quantile(0.95, rate(erid_http_request_duration_seconds_bucket[5m]))` | above 500ms. |
| `erid_db_pool_connections_in_use` | near pool size + overflow: requests are waiting on the database. |
