#!/usr/bin/env bash
# One-time setup: infrastructure, Python environment, migrations, seed data,
# and the web app's dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v docker >/dev/null || { echo "Docker is required."; exit 1; }
command -v node >/dev/null || { echo "Node 20+ is required."; exit 1; }

[[ -f .env ]] || cp .env.example .env

echo "→ Starting PostgreSQL"
docker compose -f infra/docker-compose.yml up -d
until docker compose -f infra/docker-compose.yml exec -T postgres \
  pg_isready -U textileops -d textileops >/dev/null 2>&1; do
  sleep 1
done

echo "→ Creating the test database"
docker compose -f infra/docker-compose.yml exec -T postgres \
  psql -U textileops -d postgres -c "CREATE DATABASE textileops_test" 2>/dev/null || true

echo "→ Python environment"
cd apps/api
if command -v uv >/dev/null; then
  uv venv .venv
  uv pip install -e ".[dev]"
else
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -e ".[dev]"
fi

echo "→ Migrations"
.venv/bin/alembic upgrade head

echo "→ Seeding the demo business"
.venv/bin/python -m textileops.cli seed --reset

cd ../web
echo "→ Web dependencies"
npm install
[[ -f .env.local ]] || cp .env.local.example .env.local

cd "$ROOT"
cat <<'MESSAGE'

TextileOps is ready.

  ./scripts/dev.sh        start the API, the worker and the web app
  open http://localhost:3000

  Sign in with  owner@kaveriknits.example  /  textileops
MESSAGE
