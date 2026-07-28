# Docs

See the [README](../README.md) for full architecture, auth, real-time events,
and configuration.

Quick start:

```bash
docker compose up -d postgres redis api
curl http://localhost:8000/health   # {"status":"ok"}
```

- API docs (OpenAPI): http://localhost:8000/docs
- Dashboard: `cd web && npm install && npm run dev` → http://localhost:5173
- Client setup: [clients/README.md](../clients/README.md)
- Tests: `uv run pytest`
