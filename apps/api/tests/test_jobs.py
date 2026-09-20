"""The background queue: idempotency, retries, and crash safety."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from textileops.models.enums import JobStatus
from textileops.models.platform import Job
from textileops.services import clock
from textileops.workers import tasks
from textileops.workers.queue import (
    claim,
    enqueue,
    handler,
    registered_tasks,
    run_job,
)

_runs: list[str] = []


@handler("test_ok")
def _ok(session, payload):
    _runs.append(payload.get("tag", "ok"))
    return {"tag": payload.get("tag")}


@handler("test_boom")
def _boom(session, payload):
    raise RuntimeError("deliberate failure")


def test_every_registered_task_is_addressable():
    assert "recompute_exceptions" in registered_tasks()
    assert "process_message" in registered_tasks()


def test_an_unknown_task_cannot_be_enqueued(session):
    with pytest.raises(ValueError):
        enqueue(session, "task_that_does_not_exist", {})


def test_enqueueing_the_same_idempotency_key_twice_is_a_no_op(session):
    first = enqueue(session, "test_ok", {"tag": "a"}, idempotency_key="key-1")
    second = enqueue(session, "test_ok", {"tag": "a"}, idempotency_key="key-1")
    session.flush()
    assert first is not None
    assert second is None
    assert session.scalar(select(func.count(Job.id))) == 1


def test_claiming_marks_the_job_running_and_counts_the_attempt(session):
    enqueue(session, "test_ok", {"tag": "b"})
    session.flush()
    claimed = claim(session, limit=5)
    assert len(claimed) == 1
    assert claimed[0].status == JobStatus.RUNNING
    assert claimed[0].attempts == 1
    assert claimed[0].locked_by


def test_a_future_job_is_not_claimed_yet(session):
    import datetime as dt

    enqueue(
        session,
        "test_ok",
        {"tag": "later"},
        run_after=clock.now() + dt.timedelta(hours=1),
    )
    session.flush()
    assert claim(session, limit=5) == []


def test_a_failing_job_is_retried_with_backoff_then_declared_dead(session):
    job = enqueue(session, "test_boom", {}, max_attempts=2)
    session.flush()

    claim(session, limit=1)
    result = run_job(session, session.get(Job, job.id))
    session.flush()
    retried = session.get(Job, job.id)
    assert result.status == JobStatus.QUEUED
    assert retried.error and "deliberate failure" in retried.error
    assert retried.run_after > clock.now()

    retried.run_after = clock.now()
    session.flush()
    claim(session, limit=1)
    run_job(session, session.get(Job, job.id))
    session.flush()
    assert session.get(Job, job.id).status == JobStatus.DEAD


def test_recompute_is_safe_to_run_repeatedly(session, supplier, yarn):
    """The recompute task must be idempotent: it is queued on every event."""
    from tests.conftest import make_purchase_order

    make_purchase_order(session, supplier, yarn, expected_in=-5)
    session.flush()

    first = tasks.recompute_exceptions(session, {})
    session.flush()
    second = tasks.recompute_exceptions(session, {})
    session.flush()

    assert first["created"] >= 1
    assert second["created"] == 0
    assert second["auto_resolved"] == 0


def test_a_job_whose_worker_died_is_reclaimed(session):
    """A RUNNING job with a stale lock would otherwise sit there for ever."""
    import datetime as dt

    from textileops.workers.queue import reclaim_abandoned

    job = enqueue(session, "test_ok", {"tag": "orphan"})
    session.flush()
    claim(session, limit=1)
    session.flush()
    assert session.get(Job, job.id).status == JobStatus.RUNNING

    # Pretend the worker died a long time ago.
    session.get(Job, job.id).locked_at = clock.now() - dt.timedelta(hours=2)
    session.flush()

    assert reclaim_abandoned(session) == 1
    reclaimed = session.get(Job, job.id)
    assert reclaimed.status == JobStatus.QUEUED
    assert "stopped responding" in reclaimed.error


def test_a_dead_job_does_not_block_the_task_for_ever(session):
    """An exhausted job must not permanently claim its idempotency key."""
    job = enqueue(session, "test_boom", {}, idempotency_key="investigate:x", max_attempts=1)
    session.flush()
    claim(session, limit=1)
    run_job(session, session.get(Job, job.id))
    session.flush()
    assert session.get(Job, job.id).status == JobStatus.DEAD

    again = enqueue(session, "test_ok", {}, idempotency_key="investigate:x")
    session.flush()
    assert again is not None
