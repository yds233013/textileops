#!/bin/bash
# Entrypoint for the single-container deployment (deploy/render/Dockerfile).
#
#   1. migrate (advisory-locked) and, in demo mode, load or refresh the demo
#   2. start the API on loopback, the worker, and the web server on $PORT
#   3. if any of the three exits, stop the others and exit non-zero, so the
#      platform restarts the whole container rather than leaving a web front
#      end that answers while the API behind it is dead.
#
# Configuration safety is enforced by the processes themselves: the API refuses
# to start with a development JWT secret, DEBUG on, a wildcard CORS origin, or
# demo mode together with pilot mode (textileops/core/config.py).
set -euo pipefail

API_PORT=8000
cd /app/api

python -m textileops.cli migrate
if [ "${DEMO_MODE:-false}" = "true" ]; then
  python -m textileops.cli demo-refresh
fi

# Loopback only. Only the web server's port is reachable from outside the
# container; the API is reached through its /api/v1 proxy.
uvicorn textileops.api.main:app \
  --host 127.0.0.1 \
  --port "$API_PORT" \
  --proxy-headers \
  --forwarded-allow-ips 127.0.0.1 \
  --no-server-header \
  --workers "${WEB_CONCURRENCY:-1}" &
api=$!

python -m textileops.workers.runner &
worker=$!

cd /app/web
API_ORIGIN="http://127.0.0.1:${API_PORT}" HOSTNAME=0.0.0.0 \
  node --max-old-space-size="${NODE_MAX_OLD_SPACE_MB:-192}" server.js &
web=$!

shutdown() {
  kill -TERM "$api" "$worker" "$web" 2>/dev/null || true
  wait || true
}
trap 'shutdown; exit 0' TERM INT

# Whichever stops first, stop everything and let the platform restart us.
set +e
wait -n "$api" "$worker" "$web"
status=$?
echo "textileops: a process exited (status $status); stopping the container" >&2
shutdown
# Even a clean exit of one process is a failure of the whole.
[ "$status" -eq 0 ] && status=1
exit "$status"
