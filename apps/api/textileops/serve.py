"""One process for the single-container demo: migrate, prepare, serve, work.

    python -m textileops.serve

The hosted demo runs on a free instance with a tenth of a CPU and puts itself
to sleep when idle, so every wake-up is a cold start that a visitor waits
through. Starting four Python processes (migrate, demo refresh, API, worker)
paid for importing the application four times — about 17 seconds each at that
speed. This does it once:

1. apply migrations (under the same advisory lock as `textileops migrate`);
2. in demo mode, reload the demo if it is stale or a visitor changed it —
   waking up is the evidence that they left (seed/refresh.py);
3. in demo mode, warm the pages a visitor opens first by requesting them
   in-process, so the first real request is not the one that pays for every
   lazy import and query compilation;
4. run the worker loop in a thread, and the API on loopback in this thread.

The API binds 127.0.0.1 only: the web server beside it is the only thing
reachable from outside (deploy/render/start.sh). Separate processes remain the
right shape for a real deployment — `textileops.workers.runner` and uvicorn —
and nothing here changes what the API or the worker does.
"""

from __future__ import annotations

import os
import sys
import threading
import time

from textileops.core.config import settings
from textileops.core.logging import configure_logging, get_logger

logger = get_logger("textileops.serve")

API_HOST = "127.0.0.1"

#: The pages a visitor sees first after "Explore the demo".
WARM_PATHS = (
    "/api/v1/dashboard",
    "/api/v1/orders",
    "/api/v1/inventory/positions",
    "/api/v1/system/counts",
    "/api/v1/proposals",
    "/api/v1/exceptions",
    "/api/v1/production/batches",
    "/api/v1/suppliers",
    "/api/v1/purchase-orders",
    "/api/v1/audit?limit=8",
    "/api/v1/settings",
)


def prepare() -> None:
    from textileops.cli import migrate

    started = time.monotonic()
    migrate()
    if settings.demo_mode:
        from textileops.core.db import session_scope
        from textileops.seed.refresh import refresh_demo_if_stale

        with session_scope() as session:
            result = refresh_demo_if_stale(session, just_started=True)
        logger.info("demo_checked", refreshed=result.refreshed, reason=result.reason)
    logger.info("prepared", seconds=round(time.monotonic() - started, 1))


def warm(app: object) -> None:
    """Request the first pages in-process. Reads only; best effort."""
    if not settings.demo_mode:
        return
    from fastapi.testclient import TestClient

    started = time.monotonic()
    try:
        client = TestClient(app)  # type: ignore[arg-type]
        login = client.post("/api/v1/auth/demo-login")
        token = login.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for path in WARM_PATHS:
            client.get(path, headers=headers)
    except Exception as exc:  # warming is an optimisation, never a reason not to serve
        logger.warning("warm_up_failed", error=str(exc))
    logger.info("warmed", seconds=round(time.monotonic() - started, 1))


def main() -> int:
    configure_logging()
    settings.assert_consistent()

    import uvicorn

    from textileops.api.main import app
    from textileops.workers.runner import DEMO_REFRESH_EVERY_SECONDS, run_loop

    prepare()
    warm(app)

    stop = threading.Event()
    worker = threading.Thread(
        target=run_loop,
        args=(lambda: not stop.is_set(),),
        # The demo was just checked in prepare(); the next check is the worker's.
        kwargs={"first_demo_check_in": DEMO_REFRESH_EVERY_SECONDS},
        name="worker",
        daemon=True,
    )
    worker.start()

    try:
        uvicorn.run(
            app,
            host=API_HOST,
            port=int(os.environ.get("API_PORT", "8000")),
            proxy_headers=True,
            # Only the web server beside it forwards requests.
            forwarded_allow_ips=API_HOST,
            server_header=False,
            log_config=None,
        )
    finally:
        stop.set()
        worker.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
