"""The worker process. ``python -m textileops.workers.runner``"""

from __future__ import annotations

import signal
import sys
import time
from types import FrameType

from textileops.core.config import settings
from textileops.core.db import SessionLocal
from textileops.core.logging import configure_logging, get_logger
from textileops.workers import tasks  # noqa: F401  (registers handlers)
from textileops.workers.queue import claim, registered_tasks, run_job, worker_identity

logger = get_logger("textileops.worker")
_running = True


def _stop(signum: int, _frame: FrameType | None) -> None:
    global _running
    logger.info("worker_stopping", signal=signum)
    _running = False


def main() -> int:
    configure_logging()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    logger.info(
        "worker_started", identity=worker_identity(), tasks=registered_tasks()
    )

    while _running:
        session = SessionLocal()
        try:
            # One at a time: claiming a batch marks every job in it RUNNING on
            # disk, so a crash mid-batch would strand the rest.
            jobs = claim(session, limit=1)
            if not jobs:
                session.commit()
                time.sleep(settings.worker_poll_seconds)
                continue
            for job in jobs:
                run_job(session, job)
                session.commit()
        except Exception as exc:
            logger.error("worker_loop_error", error=str(exc))
            session.rollback()
            time.sleep(settings.worker_poll_seconds)
        finally:
            session.close()

    logger.info("worker_stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
