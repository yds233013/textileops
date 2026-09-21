#!/bin/sh
# Worker entrypoint. Several can run at once: jobs are claimed with
# FOR UPDATE SKIP LOCKED, so each is taken exactly once.
set -eu
exec python -m textileops.workers.runner
