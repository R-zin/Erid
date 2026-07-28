#!/usr/bin/env bash
# Local CI sequence mirroring .github/workflows/tests.yml.
# Requires `uv` on PATH (and Node/npm for the web build).
#
# Usage:
#   ./scripts/ci.sh                 # run everything
#   ./scripts/ci.sh --only pytest   # run a subset (ruff-format|ruff-check|pytest|web)
#   ./scripts/ci.sh --skip web
#   ./scripts/ci.sh --dry-run       # print commands without running

set -euo pipefail
cd "$(dirname "$0")/.."

ONLY=""
SKIP=()
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --only) ONLY="$2"; shift 2 ;;
    --skip) SKIP+=("$2"); shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

want() {
  local step="$1"
  [[ -z "$ONLY" || "$ONLY" == "$step" ]] || return 1
  for s in "${SKIP[@]:-}"; do [[ "$s" == "$step" ]] && return 1; done
  return 0
}

run() {
  echo "+ $*"
  [[ $DRY_RUN -eq 1 ]] || "$@"
}

if want ruff-format; then run uv run ruff format --check api mcp-server tests; fi
if want ruff-check;  then run uv run ruff check api mcp-server tests; fi
if want pytest;      then run uv run pytest -v --tb=short; fi
if want web; then
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "+ (cd web && npm ci && npm run build)"
  else
    (cd web && run npm ci && run npm run build)
  fi
fi

echo "CI OK"
