#!/bin/bash
# Entrypoint for the single-container deployment (deploy/render/Dockerfile).
#
# Two processes:
#
#   web   Next.js on 0.0.0.0:$PORT — the only listener reachable from outside.
#   api   python -m textileops.serve: migrates, loads or refreshes the demo,
#         warms the first pages, then serves FastAPI on 127.0.0.1 with the
#         worker as a thread (see textileops/serve.py).
#
# The web server starts at once, so a visitor waking the demo sees TextileOps
# saying it is waking up, rather than a blank page, while the API prepares.
#
# If either process exits, stop the other and exit non-zero so the platform
# restarts the whole container rather than leaving a web front end that answers
# while the API behind it is dead.
#
# Configuration safety is enforced by the processes themselves: the API refuses
# to start with a development JWT secret, DEBUG on, a wildcard CORS origin, or
# demo mode together with pilot mode (textileops/core/config.py).
set -euo pipefail

API_PORT=8000
export API_PORT

cd /app/api
python -m textileops.serve &
api=$!

cd /app/web
API_ORIGIN="http://127.0.0.1:${API_PORT}" HOSTNAME=0.0.0.0 \
  node --max-old-space-size="${NODE_MAX_OLD_SPACE_MB:-192}" server.js &
web=$!

shutdown() {
  kill -TERM "$api" "$web" 2>/dev/null || true
  wait || true
}
trap 'shutdown; exit 0' TERM INT

# Whichever stops first, stop everything and let the platform restart us.
set +e
wait -n "$api" "$web"
status=$?
echo "textileops: a process exited (status $status); stopping the container" >&2
shutdown
# Even a clean exit of one process is a failure of the whole.
[ "$status" -eq 0 ] && status=1
exit "$status"
