#!/usr/bin/env bash
# Start everything needed for local development: PostgreSQL, the API, the
# worker and the web app. Ctrl-C stops all of them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.example"
  cp .env.example .env
fi

echo "→ Starting PostgreSQL"
docker compose -f infra/docker-compose.yml up -d
until docker compose -f infra/docker-compose.yml exec -T postgres \
  pg_isready -U textileops -d textileops >/dev/null 2>&1; do
  sleep 1
done

echo "→ Applying migrations"
(cd apps/api && .venv/bin/alembic upgrade head)

pids=()
cleanup() {
  echo
  echo "→ Stopping"
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

echo "→ API on http://localhost:8000"
(cd apps/api && .venv/bin/uvicorn textileops.api.main:app --reload --port 8000) &
pids+=($!)

echo "→ Worker"
(cd apps/api && .venv/bin/python -m textileops.workers.runner) &
pids+=($!)

echo "→ Web on http://localhost:3000"
(cd apps/web && npm run dev) &
pids+=($!)

wait
