#!/usr/bin/env bash
# Everything that must pass before the work is considered done.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Backend: lint ==="
(cd apps/api && .venv/bin/ruff check .)

echo "=== Backend: types ==="
(cd apps/api && .venv/bin/mypy textileops)

echo "=== Backend: tests ==="
(cd apps/api && .venv/bin/python -m pytest -q -m "not ai_live")

echo "=== AI evaluations (deterministic stub) ==="
# Pinned to the stub on purpose. This gate is meant to be deterministic and
# offline; with AI_PROVIDER=auto it silently became a live, billable API call
# for anyone who had configured a key, and a flaky model response would then
# fail an unrelated verification run. The live suite is a separate, deliberate
# command: `python -m textileops.evals.live`.
(cd apps/api && AI_PROVIDER=stub .venv/bin/python -m textileops.evals.runner >/dev/null \
  && echo "evals passed (stub)")

echo "=== Data integrity ==="
(cd apps/api && .venv/bin/python -m textileops.cli check)

echo "=== Frontend: types ==="
(cd apps/web && npx tsc --noEmit)

echo "=== Frontend: lint ==="
(cd apps/web && npx next lint --dir app --dir components --dir lib)

echo "=== Frontend: tests ==="
(cd apps/web && npx vitest run)

echo "=== Frontend: production build ==="
(cd apps/web && npm run build >/dev/null && echo "build ok")

echo
echo "All checks passed."
