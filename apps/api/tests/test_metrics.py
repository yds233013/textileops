"""Product instrumentation — and what it refuses to claim."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import make_purchase_order
from textileops.models.enums import ExceptionStatus
from textileops.models.exceptions import OperationalException
from textileops.services import clock, exception_engine, metrics

D = Decimal


def test_snapshot_counts_real_events(session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=-6)
    session.flush()
    exception_engine.run(session)
    session.flush()

    snapshot = metrics.snapshot(session)
    assert snapshot.counters["exceptions_detected"] >= 1
    assert snapshot.counters["open_exceptions"] >= 1


def test_snapshot_never_claims_hours_saved(session):
    snapshot = metrics.snapshot(session)
    payload = snapshot.to_dict()
    text = str(payload).lower()
    assert "hours_saved" not in text
    assert "hours saved" in payload["caveat"].lower()  # it says so explicitly
    assert "measured baseline" in payload["caveat"]


def test_durations_report_no_value_rather_than_a_fake_one(session):
    durations = {d.label: d for d in metrics.workflow_durations(session)}
    stat = durations["Detected → resolved by a person"]
    assert stat.count == 0
    assert stat.median_value is None
    assert "No completed occurrences yet" in (stat.note or "")


def test_resolution_time_is_measured_from_first_detection(session, supplier, yarn, user):
    """From *first* detection, not from the most recent re-detection.

    The test used to detect the condition once, so `first_detected_at` and
    `detected_at` were the same moment and the distinction it is named for was
    untestable: swapping one for the other in metrics.py left it green. It
    also asserted only a count and nothing about the measured duration.
    """
    import datetime as dt

    from sqlalchemy import select

    first_seen = clock.now() - dt.timedelta(days=3)
    with clock.frozen(first_seen):
        make_purchase_order(session, supplier, yarn, expected_in=-6)
        session.flush()
        exception_engine.run(session)
        session.flush()

    exception = session.scalar(select(OperationalException))
    assert exception is not None
    original_first_seen = exception.first_detected_at

    # Seen again two days later, and by then the order is later still, so the
    # detection changes. `detected_at` moves forward; the duration must still
    # be measured from the first sighting.
    with clock.frozen(first_seen + dt.timedelta(days=2)):
        exception_engine.run(session)
        session.flush()
    session.refresh(exception)
    assert exception.first_detected_at == original_first_seen
    assert exception.detected_at > exception.first_detected_at, (
        "precondition: the condition was re-detected later"
    )

    metrics.mark_exception_viewed(session, exception)
    exception.status = ExceptionStatus.RESOLVED
    exception.resolved_at = first_seen + dt.timedelta(days=3)
    exception.resolved_by_user_id = user.id
    session.flush()

    durations = {d.label: d for d in metrics.workflow_durations(session)}
    measured = durations["Detected → resolved by a person"]
    assert measured.count == 1
    # Three days from first sighting, not one from the re-detection.
    assert measured.median_value == pytest.approx(3 * 24 * 60, rel=0.01), (
        f"measured {measured.median_value} minutes; resolution time is being "
        "taken from the latest detection rather than the first"
    )


def test_ai_summary_shows_how_much_was_stubbed(session, supplier, yarn):
    from textileops.ai.provider import get_provider
    from textileops.ai.schemas import SupplierMessageExtraction
    from textileops.ai.telemetry import record_call

    result = get_provider().structured(
        workflow="extract_supplier_message",
        system="s",
        user_content="PO-1 delayed two days",
        schema=SupplierMessageExtraction,
    )
    record_call(session, workflow="extract_supplier_message", result=result)
    session.flush()

    summary = metrics.ai_summary(session)
    assert summary["calls"] == 1
    assert summary["stubbed_share_pct"] == 100
