#!/bin/sh
# API entrypoint: migrate, then serve.
#
# `textileops migrate` takes a database advisory lock, so when several API
# instances start together only one applies migrations and the rest wait and
# find nothing to do. The process then refuses to start if the configuration
# is unsafe for production (development JWT secret, DEBUG on, a wildcard CORS
# origin, or demo mode together with pilot mode) — see core/config.py.
set -eu

python -m textileops.cli migrate

# A demo deployment loads its fictional company on first boot. This does
# nothing unless DEMO_MODE is on, and refuses any database the demo seed did
# not create — see textileops/seed/refresh.py.
if [ "${DEMO_MODE:-false}" = "true" ]; then
  python -m textileops.cli demo-refresh
fi

# TLS is terminated by the platform in front of this process; trust its
# forwarded headers so request logs and URLs carry the real scheme and client.
exec uvicorn textileops.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --no-server-header \
  --workers "${WEB_CONCURRENCY:-2}"
