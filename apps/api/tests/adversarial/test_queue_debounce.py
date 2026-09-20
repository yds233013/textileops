"""A whole-database sweep must not be queued once per inbound message.

`recompute_exceptions` re-derives everything, so two runs back to back give
the same answer twice. It was enqueued on every processed document and every
processed message with no idempotency key — which on a busy morning is a queue
of identical multi-minute sweeps that drains slower than the mail arrives.
"""

from __future__ import annotations

from sqlalchemy import func, select

from textileops.models.enums import JobStatus
from textileops.models.platform import Job

# Importing the handlers registers them; enqueue refuses an unknown task.
from textileops.workers import tasks as _tasks  # noqa: F401
from textileops.workers.queue import enqueue_debounced


def _pending(session) -> int:
    return session.scalar(
        select(func.count(Job.id)).where(
            Job.task == "recompute_exceptions",
            Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
    )


def test_a_burst_of_requests_produces_one_sweep(session):
    for index in range(25):
        enqueue_debounced(session, "recompute_exceptions", {"reason": f"msg-{index}"})
    session.flush()

    assert _pending(session) == 1, (
        "twenty-five inbound messages queued twenty-five full recomputes"
    )


def test_the_request_is_delayed_not_dropped(session):
    """Collapsing onto a pending job is only safe if that job still runs."""
    first = enqueue_debounced(session, "recompute_exceptions", {"reason": "first"})
    session.flush()
    assert first is not None

    second = enqueue_debounced(session, "recompute_exceptions", {"reason": "second"})
    session.flush()
    assert second is None, "the second request collapsed onto the pending one"

    still_there = session.get(Job, first.id)
    assert still_there is not None
    assert still_there.status == JobStatus.QUEUED, (
        "the sweep that absorbed the others must still be waiting to run"
    )


def test_a_change_after_the_sweep_has_run_gets_its_own_sweep(session):
    """The defect an earlier version of this had, and it was severe.

    Debouncing by a time window meant the key for that window persisted after
    the sweep SUCCEEDED — and ``enqueue`` treats any existing key as
    absorbing. So a change arriving later in the same window was not delayed,
    it was **dropped**: nothing schedules a sweep periodically, so it would
    never be looked at until some unrelated ingestion happened to queue one.
    A supplier delay could be applied to a purchase order and the
    high-severity exception it raises never appear at all.
    """
    first = enqueue_debounced(session, "recompute_exceptions", {"reason": "early"})
    session.flush()
    assert first is not None

    # The sweep runs and finishes. It has now seen the world as it was.
    first.status = JobStatus.SUCCEEDED
    session.flush()
    assert _pending(session) == 0

    second = enqueue_debounced(session, "recompute_exceptions", {"reason": "later"})
    session.flush()
    assert second is not None, (
        "a change arriving after the sweep finished was dropped, not delayed"
    )
    assert _pending(session) == 1


def test_a_running_sweep_still_absorbs_requests(session):
    """A sweep that has not finished will see this change too."""
    first = enqueue_debounced(session, "recompute_exceptions", {"reason": "first"})
    session.flush()
    first.status = JobStatus.RUNNING
    session.flush()

    assert enqueue_debounced(session, "recompute_exceptions", {"reason": "during"}) is None
    session.flush()
    assert _pending(session) == 1


def test_debouncing_does_not_affect_targeted_jobs(session, supplier, yarn):
    """Only whole-database sweeps are safe to collapse.

    A job about one specific thing is not interchangeable with another, so
    nothing here should have taught the queue to drop those.
    """
    from textileops.workers.queue import enqueue

    first = enqueue(session, "recompute_exceptions", {"reason": "explicit"})
    second = enqueue(session, "recompute_exceptions", {"reason": "also explicit"})
    session.flush()
    assert first is not None and second is not None
    assert first.id != second.id
