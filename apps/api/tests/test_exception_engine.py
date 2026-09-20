"""The exception engine: detection, deduplication, lifecycle, auto-resolution."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from tests.conftest import (
    day,
    make_batch,
    make_purchase_order,
    make_sales_order,
    moment,
)
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    ExceptionStatus,
    ExceptionType,
    QCOutcome,
    Severity,
)
from textileops.models.exceptions import OperationalException
from textileops.services import clock, exception_engine, inventory, procurement, production, quality

D = Decimal


def _codes(session, exception_type: ExceptionType) -> list[str]:
    return list(
        session.scalars(
            select(OperationalException.code).where(
                OperationalException.exception_type == exception_type
            )
        ).all()
    )


def test_a_late_purchase_order_is_detected(session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=-4)
    session.flush()
    exception_engine.run(session)
    assert _codes(session, ExceptionType.PO_LATE)


def test_an_on_time_purchase_order_raises_nothing(session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=6)
    session.flush()
    exception_engine.run(session)
    assert not _codes(session, ExceptionType.PO_LATE)


def test_running_the_engine_twice_does_not_duplicate_exceptions(session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=-4)
    session.flush()

    first = exception_engine.run(session)
    total_after_first = session.scalar(select(func.count(OperationalException.id)))
    second = exception_engine.run(session)
    total_after_second = session.scalar(select(func.count(OperationalException.id)))

    assert first.created
    assert not second.created
    assert total_after_first == total_after_second


def test_the_dedupe_key_identifies_the_issue_not_the_occurrence(session, supplier, yarn):
    po = make_purchase_order(session, supplier, yarn, expected_in=-4)
    session.flush()
    exception_engine.run(session)
    exception = session.scalar(
        select(OperationalException).where(
            OperationalException.exception_type == ExceptionType.PO_LATE
        )
    )
    assert exception.dedupe_key == f"PO_LATE:{po.id}"


def test_a_condition_that_clears_auto_resolves_its_exception(session, supplier, yarn):
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=-4)
    session.flush()
    exception_engine.run(session)
    exception = session.scalar(
        select(OperationalException).where(
            OperationalException.exception_type == ExceptionType.PO_LATE
        )
    )
    assert exception.status == ExceptionStatus.OPEN

    procurement.receive(session, po.lines[0], accepted_quantity=D("1000"))
    session.flush()
    result = exception_engine.run(session)

    session.refresh(exception)
    assert exception.code in result.auto_resolved
    assert exception.status == ExceptionStatus.RESOLVED
    assert exception.auto_resolved is True
    assert exception.resolved_at is not None


def test_a_recurring_condition_reopens_the_same_record(session, supplier, yarn):
    """History stays in one place instead of spawning a second exception."""
    make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=-4)
    session.flush()
    exception_engine.run(session)
    exception = session.scalar(
        select(OperationalException).where(
            OperationalException.exception_type == ExceptionType.PO_LATE
        )
    )
    original_id = exception.id

    # Resolve it by hand, then let the condition persist.
    exception.status = ExceptionStatus.RESOLVED
    exception.resolved_at = clock.now()
    session.flush()

    exception_engine.run(session)
    session.refresh(exception)
    assert exception.id == original_id
    assert exception.status == ExceptionStatus.OPEN
    assert exception.occurrence_count == 2
    assert session.scalar(
        select(func.count(OperationalException.id)).where(
            OperationalException.exception_type == ExceptionType.PO_LATE
        )
    ) == 1


def test_human_resolution_survives_a_recompute_when_the_condition_is_gone(
    session, supplier, yarn
):
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=-4)
    session.flush()
    exception_engine.run(session)
    exception = session.scalar(select(OperationalException))
    exception.status = ExceptionStatus.DISMISSED
    exception.dismissed_at = clock.now()
    session.flush()

    procurement.receive(session, po.lines[0], accepted_quantity=D("1000"))
    session.flush()
    exception_engine.run(session)
    session.refresh(exception)
    assert exception.status == ExceptionStatus.DISMISSED


def test_a_material_shortage_names_every_affected_order(session, customer, fabric, yarn):
    inventory.create_lot(
        session,
        lot_code="LOT-SMALL",
        material_id=yarn.id,
        quantity=D("500"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    first = make_sales_order(session, customer, fabric, number="SO-X", promised_in=15)
    second = make_sales_order(session, customer, fabric, number="SO-Y", promised_in=25)
    make_batch(session, fabric, first, start_in=2)
    make_batch(session, fabric, second, start_in=5)
    session.flush()
    exception_engine.run(session)

    shortage = session.scalar(
        select(OperationalException).where(
            OperationalException.exception_type == ExceptionType.MATERIAL_SHORTAGE
        )
    )
    assert shortage is not None
    numbers = {o["number"] for o in shortage.impact["affected_orders"]}
    assert numbers == {"SO-X", "SO-Y"}
    assert shortage.evidence  # the calculation is shown, not just asserted


def test_severity_rises_with_customer_importance(session, customer, fabric, yarn):
    customer.priority_tier = 1
    inventory.create_lot(
        session,
        lot_code="LOT-1",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    order = make_sales_order(session, customer, fabric, promised_in=-3)
    make_batch(session, fabric, order, start_in=-6)
    session.flush()
    exception_engine.run(session)
    late = session.scalar(
        select(OperationalException).where(
            OperationalException.exception_type == ExceptionType.ORDER_LATE
        )
    )
    assert late.severity == Severity.CRITICAL
    assert late.priority_score > 3000


def test_an_over_receipt_beyond_tolerance_is_a_quantity_mismatch(session, supplier, yarn):
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=3)
    procurement.receive(session, po.lines[0], accepted_quantity=D("1100"))
    session.flush()
    exception_engine.run(session)
    assert _codes(session, ExceptionType.QUANTITY_MISMATCH)


def test_a_small_over_receipt_inside_trade_tolerance_is_not_an_exception(
    session, supplier, yarn
):
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=3)
    procurement.receive(session, po.lines[0], accepted_quantity=D("1015"))
    session.flush()
    exception_engine.run(session)
    assert not _codes(session, ExceptionType.QUANTITY_MISMATCH)


def test_a_stock_ledger_mismatch_is_an_inventory_anomaly(session, yarn):
    lot = inventory.create_lot(
        session,
        lot_code="LOT-BAD",
        material_id=yarn.id,
        quantity=D("100"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-1),
    )
    lot.quantity_on_hand = D("150.000")
    session.flush()
    exception_engine.run(session)
    assert _codes(session, ExceptionType.INVENTORY_ANOMALY)


def test_a_qc_rejection_raises_an_exception_that_clears_on_reinspection(
    session, fabric, yarn
):
    inventory.create_lot(
        session,
        lot_code="LOT-Y",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-3),
    )
    batch = make_batch(session, fabric, quantity=D("1000"), start_in=-6, days=4)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    production.record_output(session, batch, good_quantity=D("1000"))
    failed = quality.record_inspection(
        session,
        code="QC-F",
        outcome=QCOutcome.REWORK,
        inspected_quantity=D("1000"),
        rejected_quantity=D("1000"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
    )
    quality.propagate(session, failed, schedule_replacement=False)
    session.flush()
    exception_engine.run(session)
    assert _codes(session, ExceptionType.QC_FAILURE)

    passed = quality.record_inspection(
        session,
        code="QC-F-RE1",
        outcome=QCOutcome.PASS,
        inspected_quantity=D("1000"),
        accepted_quantity=D("1000"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
        reinspection_of_id=failed.id,
    )
    quality.propagate(session, passed)
    session.flush()
    result = exception_engine.run(session)

    qc_exception = session.scalar(
        select(OperationalException).where(
            OperationalException.exception_type == ExceptionType.QC_FAILURE
        )
    )
    assert qc_exception.code in result.auto_resolved
    assert qc_exception.status == ExceptionStatus.RESOLVED


def test_a_dismissed_exception_stays_dismissed(session, supplier, yarn):
    """Re-raising something a person has judged not worth acting on would
    teach them to ignore the queue."""
    make_purchase_order(session, supplier, yarn, expected_in=-4)
    session.flush()
    exception_engine.run(session)
    exception = session.scalar(select(OperationalException))
    exception.status = ExceptionStatus.DISMISSED
    exception.dismissed_at = clock.now()
    session.flush()

    exception_engine.run(session)
    session.refresh(exception)
    assert exception.status == ExceptionStatus.DISMISSED


def test_a_dismissed_exception_reopens_only_if_it_gets_worse(session, supplier, yarn):
    po = make_purchase_order(session, supplier, yarn, expected_in=-4)
    session.flush()
    exception_engine.run(session)
    exception = session.scalar(select(OperationalException))
    exception.status = ExceptionStatus.DISMISSED
    exception.dismissed_at = clock.now()
    session.flush()

    # The same condition, materially worse: it has slipped further.
    po.order_date = day(-40)
    po.expected_date = day(-20)
    session.flush()
    exception_engine.run(session)
    session.refresh(exception)
    assert exception.status == ExceptionStatus.OPEN
    assert "got worse" in (exception.resolution_note or "")
