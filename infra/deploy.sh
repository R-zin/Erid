#!/usr/bin/env bash
# Self-host deploy for the AI Context Hub: pull latest, rebuild, restart the
# web stack (postgres + api + web), and wait for the API to come up.
#
# Usage:  ./infra/deploy.sh            # dev stack, API on :8000, dashboard on :8080
#         ERID_ENV=prod ./infra/deploy.sh
#                                      # public stack behind Caddy/HTTPS
#                                      # (docker-compose.prod.yml)
# Expects to be run from the repo root on the deploy host (Docker + Compose
# installed). Configuration comes from `.env` (see `.env.example`); ERID_ENV
# may be set there or in the shell.
#
# The optional stdio MCP worker is NOT part of the default web stack; start it
# afterwards with:  docker compose --profile mcp up -d

set -euo pipefail

cd "$(dirname "$0")/.."   # run from repo root regardless of invocation path

if [[ -z "${ERID_ENV:-}" && -f .env ]]; then
  ERID_ENV=$(grep -E '^ERID_ENV=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' || true)
fi

if [[ "${ERID_ENV:-}" == "prod" ]]; then
  COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
  SERVICES=(postgres api web caddy)
  # api isn't published on a host port in prod; probe it from inside the container.
  health() {
    "${COMPOSE[@]}" exec -T api python -c \
      'import urllib.request; print(urllib.request.urlopen("http://localhost:8000/health").read().decode())'
  }
else
  COMPOSE=(docker compose)
  SERVICES=(postgres api web)
  health() { curl -sf http://localhost:8000/health; }
fi

echo "==> Pulling latest code"
git pull --ff-only

echo "==> Building api + web images"
"${COMPOSE[@]}" build api web

echo "==> Starting ${SERVICES[*]}"
"${COMPOSE[@]}" up -d "${SERVICES[@]}"

echo "==> Waiting for the API to become healthy"
for i in $(seq 1 60); do
  if out=$(health 2>/dev/null); then
    echo "==> API is healthy: $out"
    if [[ "${ERID_ENV:-}" == "prod" ]]; then
      echo "==> Deploy complete. Caddy is serving https://${ERID_DOMAIN:-<ERID_DOMAIN>} (certificate issuance can take a minute)."
    else
      echo "==> Deploy complete. Dashboard: http://localhost:8080  API: http://localhost:8000"
    fi
    exit 0
  fi
  sleep 2
done

echo "ERROR: API did not become healthy within ~120s" >&2
"${COMPOSE[@]}" logs --tail 50 api >&2 || true
exit 1
