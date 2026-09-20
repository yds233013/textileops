"""Product instrumentation — and what it refuses to claim."""

from __future__ import annotations

from decimal import Decimal

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
    make_purchase_order(session, supplier, yarn, expected_in=-6)
    session.flush()
    exception_engine.run(session)
    session.flush()

    from sqlalchemy import select

    exception = session.scalar(select(OperationalException))
    metrics.mark_exception_viewed(session, exception)
    exception.status = ExceptionStatus.RESOLVED
    exception.resolved_at = clock.now()
    session.flush()

    durations = {d.label: d for d in metrics.workflow_durations(session)}
    assert durations["Detected → resolved by a person"].count == 1


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
