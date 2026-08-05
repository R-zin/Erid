#!/usr/bin/env bash
# Self-host deploy for the AI Context Hub: pull latest, rebuild, restart the
# web stack (postgres + redis + api + web), and wait for the API to come up.
#
# Usage:  ./infra/deploy.sh
# Expects to be run from the repo root on the deploy host (Docker + Compose
# installed). Configuration comes from `.env` (see `.env.example`).
#
# The optional stdio MCP worker is NOT part of the default web stack; start it
# afterwards with:  docker compose --profile mcp up -d

set -euo pipefail

cd "$(dirname "$0")/.."   # run from repo root regardless of invocation path

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building api + web images"
docker compose build api web

echo "==> Starting postgres, redis, api, web"
docker compose up -d postgres redis api web

echo "==> Waiting for the API to become healthy"
for i in $(seq 1 60); do
  if curl -sf http://localhost:8000/health >/dev/null; then
    echo "==> API is healthy: $(curl -sf http://localhost:8000/health)"
    echo "==> Deploy complete. Dashboard: http://localhost:8080  API: http://localhost:8000"
    exit 0
  fi
  sleep 2
done

echo "ERROR: API did not become healthy within ~120s" >&2
docker compose logs --tail 50 api >&2 || true
exit 1
