"""Durable job queue on PostgreSQL.

Why not Redis/Celery: the whole product already depends on PostgreSQL being
correct and available, and ``SELECT ... FOR UPDATE SKIP LOCKED`` gives
at-least-once delivery, retries, backoff and crash recovery without a second
piece of infrastructure to run, monitor and explain. A textile business running
this on one box should not need a broker.

**Jobs are idempotent by contract.** At-least-once delivery means a handler can
run twice: either it is naturally idempotent (recomputation) or it is guarded by
an idempotency key (stock movements, executions).
"""

from __future__ import annotations

import datetime as dt
import os
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.logging import get_logger
from textileops.models.enums import JobStatus
from textileops.models.platform import Job
from textileops.services import clock

logger = get_logger(__name__)

JobHandler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]
_HANDLERS: dict[str, JobHandler] = {}


def handler(task: str) -> Callable[[JobHandler], JobHandler]:
    def decorate(func: JobHandler) -> JobHandler:
        _HANDLERS[task] = func
        return func

    return decorate


def registered_tasks() -> list[str]:
    return sorted(_HANDLERS)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def enqueue(
    session: Session,
    task: str,
    payload: dict[str, Any] | None = None,
    *,
    queue: str = "default",
    idempotency_key: str | None = None,
    run_after: dt.datetime | None = None,
    max_attempts: int | None = None,
) -> Job | None:
    """Enqueue a job. Returns ``None`` when the idempotency key already exists."""
    if task not in _HANDLERS:
        raise ValueError(f"No handler registered for task {task!r}.")
    if idempotency_key:
        existing = session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key)
        )
        # A job that died is not a job that ran. Blocking on it would mean one
        # exhausted investigation could never be attempted again.
        if existing is not None and existing.status != JobStatus.DEAD:
            return None
        if existing is not None:
            existing.idempotency_key = f"{idempotency_key}:dead:{existing.id}"
            session.flush()
    job = Job(
        queue=queue,
        task=task,
        payload=payload or {},
        status=JobStatus.QUEUED,
        run_after=run_after or clock.now(),
        max_attempts=max_attempts or settings.worker_max_attempts,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    if idempotency_key:
        # The check above is a read followed by a write, so two enqueuers can
        # both find nothing and both insert. Losing that race must not cost the
        # caller their transaction: this runs inside the ingestion handler, and
        # an IntegrityError here used to roll back a whole document extraction
        # and record the failure against the *document*, blaming a key
        # collision that had nothing to do with it.
        savepoint = session.begin_nested()
        try:
            session.flush()
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            return None
        return job
    session.flush()
    return job


#: A job still marked RUNNING after this long has lost its worker (a crash, a
#: reboot, an OOM kill). Without reclaiming it, it would sit RUNNING for ever:
#: never re-claimed, never retried, never surfaced.
STALE_LOCK = dt.timedelta(minutes=15)


def reclaim_abandoned(session: Session, *, queue: str = "default") -> int:
    """Return jobs whose worker died back to the queue."""
    cutoff = clock.now() - STALE_LOCK
    abandoned = session.scalars(
        select(Job).where(
            Job.queue == queue,
            Job.status == JobStatus.RUNNING,
            Job.locked_at.is_not(None),
            Job.locked_at < cutoff,
        )
    ).all()
    for job in abandoned:
        job.status = JobStatus.QUEUED if job.attempts < job.max_attempts else JobStatus.DEAD
        job.error = (
            f"Worker {job.locked_by} stopped responding; reclaimed after "
            f"{STALE_LOCK}."
        )
        job.locked_at = None
        job.locked_by = None
        logger.warning("job_reclaimed", task=job.task, job_id=str(job.id))
    session.flush()
    return len(abandoned)


def claim(session: Session, *, queue: str = "default", limit: int = 1) -> list[Job]:
    """Atomically claim runnable jobs. Concurrent workers never collide."""
    reclaim_abandoned(session, queue=queue)
    jobs = (
        session.execute(
            select(Job)
            .where(
                Job.queue == queue,
                Job.status == JobStatus.QUEUED,
                Job.run_after <= clock.now(),
            )
            .order_by(Job.run_after)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    identity = worker_identity()
    for job in jobs:
        job.status = JobStatus.RUNNING
        job.locked_at = clock.now()
        job.locked_by = identity
        job.started_at = job.started_at or clock.now()
        job.attempts += 1
    session.flush()
    return list(jobs)


@dataclass
class JobResult:
    job_id: uuid.UUID
    task: str
    status: JobStatus
    error: str | None = None


def run_job(session: Session, job: Job) -> JobResult:
    """Execute one claimed job, with retry/backoff on failure."""
    func = _HANDLERS.get(job.task)
    if func is None:
        job.status = JobStatus.DEAD
        job.error = f"No handler registered for {job.task!r}."
        job.finished_at = clock.now()
        return JobResult(job.id, job.task, job.status, job.error)

    # The handler runs inside a SAVEPOINT so that a failure discards only the
    # handler's own writes. Rolling back the whole transaction would also undo
    # the claim — losing the attempt count and retrying for ever.
    savepoint = session.begin_nested()
    try:
        result = func(session, job.payload or {})
        savepoint.commit()
        job.result = result if isinstance(result, dict) else {"ok": True}
        job.status = JobStatus.SUCCEEDED
        job.error = None
        job.finished_at = clock.now()
        logger.info("job_succeeded", task=job.task, job_id=str(job.id))
    except Exception as exc:
        savepoint.rollback()
        job.error = f"{type(exc).__name__}: {exc}"[:2000]
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.DEAD
            job.finished_at = clock.now()
            logger.error("job_dead", task=job.task, job_id=str(job.id), error=job.error)
        else:
            job.status = JobStatus.QUEUED
            # Exponential backoff: 2s, 4s, 8s, ...
            job.run_after = clock.now() + dt.timedelta(seconds=2**job.attempts)
            logger.warning(
                "job_retry",
                task=job.task,
                job_id=str(job.id),
                attempt=job.attempts,
                error=job.error,
            )
    session.flush()
    return JobResult(job.id, job.task, job.status, job.error)


def drain(session: Session, *, queue: str = "default", max_jobs: int = 100) -> list[JobResult]:
    """Run queued jobs until the queue is empty. Used by tests and the CLI."""
    results: list[JobResult] = []
    while len(results) < max_jobs:
        jobs = claim(session, queue=queue, limit=1)
        if not jobs:
            break
        result = run_job(session, jobs[0])
        session.commit()
        results.append(result)
    return results


def queue_depth(session: Session, *, queue: str = "default") -> dict[str, int]:
    depth: dict[str, int] = {}
    for status in JobStatus:
        count = session.scalar(
            select(Job.id).where(Job.queue == queue, Job.status == status).limit(1)
        )
        depth[status.value] = 0 if count is None else (
            session.query(Job).filter(Job.queue == queue, Job.status == status).count()
        )
    return depth


#: Statuses in which a sweep has not yet finished looking at the world. Only
#: these may absorb a further request for one.
PENDING_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


def enqueue_debounced(
    session: Session,
    task: str,
    payload: dict[str, Any] | None = None,
    *,
    queue: str = "default",
) -> Job | None:
    """Keep at most one *pending* whole-database sweep.

    A full exception recompute re-derives everything, so a second one queued
    behind the first would compute the same answer. It was enqueued once per
    ingested document and once per message with no key at all, which on a busy
    morning queues identical multi-minute sweeps faster than they drain.

    The earlier version of this keyed the job by a one-minute window, which
    was wrong in a way that mattered: ``enqueue`` treats *any* existing key as
    absorbing, SUCCEEDED included. So once that window's sweep had run, every
    further request inside the window was silently dropped — and since nothing
    schedules a sweep periodically, dropped meant lost, not delayed. A 40-day
    supplier delay could be applied to a purchase order and the high-severity
    exception it raises simply never appear.

    Collapsing onto a job that is still QUEUED or RUNNING is safe, because
    that job has not looked at the world yet and will see this change too. A
    job that has already finished has not, so it must not absorb anything.
    """
    pending = session.scalar(
        select(Job).where(
            Job.task == task,
            Job.queue == queue,
            Job.status.in_(PENDING_JOB_STATUSES),
        )
    )
    if pending is not None:
        return None
    # No idempotency key: what bounds this is the pending check above, and a
    # key would reintroduce exactly the "already succeeded, therefore skip"
    # behaviour this exists to avoid.
    return enqueue(session, task, payload, queue=queue)
