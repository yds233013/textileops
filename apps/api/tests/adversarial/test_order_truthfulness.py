"""Statuses and metrics must not claim more than the data supports.

An operations screen is read at a glance. A green word that is wrong is worse
than no word, because it stops the reader looking further.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from tests.conftest import (
    day,
    make_batch,
    make_purchase_order,
    make_sales_order,
    moment,
)
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    ProductionStatus,
    QCOutcome,
    RiskLevel,
    SalesOrderStatus,
    ShipmentStatus,
)
from textileops.services import (
    coverage,
    inventory,
    orders,
    procurement,
    production,
    quality,
    shipments,
)

D = Decimal
ZERO = D("0")
M = UnitOfMeasure.METRE
KG = UnitOfMeasure.KG


def _yarn(session, yarn, quantity="3000"):
    return inventory.create_lot(
        session,
        lot_code=f"LOT-{quantity}",
        material_id=yarn.id,
        quantity=D(quantity),
        unit=KG,
        received_at=moment(-5),
    )


# --- "Completed" ------------------------------------------------------------


def test_an_order_whose_batches_were_all_cancelled_is_not_completed(
    session, customer, fabric, yarn
):
    """Nothing was made. Reporting green "Completed" is the worst kind of wrong."""
    _yarn(session, yarn)
    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=20)
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    batch.status = ProductionStatus.CANCELLED
    session.flush()

    assessment = orders.assess_order(session, order)
    assert assessment.production_status != "completed"
    assert assessment.production_status == "cancelled"


def test_a_mix_of_completed_and_cancelled_is_not_reported_as_completed(
    session, customer, fabric, yarn
):
    _yarn(session, yarn)
    order = make_sales_order(session, customer, fabric, quantity=D("2000"), promised_in=20)
    done = make_batch(session, fabric, order, code="B-DONE", quantity=D("1000"),
                      start_in=-6, days=3)
    production.schedule_batch(session, done)
    production.start_batch(session, done, at=moment(-6))
    production.record_output(session, done, good_quantity=D("1000"))
    production.complete_batch(session, done)
    abandoned = make_batch(session, fabric, order, code="B-GONE", quantity=D("1000"))
    abandoned.status = ProductionStatus.CANCELLED
    session.flush()

    assert orders.assess_order(session, order).production_status != "completed"


# --- "Passed" ---------------------------------------------------------------


def test_qc_passed_requires_every_batch_to_have_been_inspected(
    session, customer, fabric, yarn
):
    """One batch inspected and two never looked at is not "Passed"."""
    _yarn(session, yarn, "6000")
    order = make_sales_order(session, customer, fabric, quantity=D("3000"), promised_in=25)

    inspected = make_batch(session, fabric, order, code="B-1", quantity=D("1000"),
                           start_in=-6, days=3)
    production.schedule_batch(session, inspected)
    production.start_batch(session, inspected, at=moment(-6))
    production.record_output(session, inspected, good_quantity=D("1000"))
    session.flush()
    passed = quality.record_inspection(
        session,
        code="QC-OK",
        outcome=QCOutcome.PASS,
        inspected_quantity=D("1000"),
        accepted_quantity=D("1000"),
        unit=M,
        production_batch_id=inspected.id,
    )
    quality.propagate(session, passed)

    make_batch(session, fabric, order, code="B-2", quantity=D("1000"), start_in=1)
    make_batch(session, fabric, order, code="B-3", quantity=D("1000"), start_in=3)
    session.flush()

    assessment = orders.assess_order(session, order)
    assert assessment.qc_status != "passed", (
        "two of three batches were never inspected"
    )
    assert assessment.qc_status == "partially_inspected"


# --- "No achievable date" ---------------------------------------------------


def test_a_finished_order_is_not_reported_as_unschedulable(
    session, customer, fabric, yarn
):
    """Nothing outstanding means done, not "no achievable date"."""
    _yarn(session, yarn)
    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=-5)
    order.lines[0].shipped_quantity = D("1000")
    order.status = SalesOrderStatus.DELIVERED
    session.flush()

    assessment = orders.assess_order(session, order)
    assert assessment.estimated_completion is None
    assert assessment.completion_unknown_reason is None, (
        "a completed order has no missing date to explain"
    )
    assert assessment.risk == RiskLevel.ON_TRACK


def test_an_order_with_no_plan_says_why_it_has_no_date(session, customer, fabric):
    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=30)
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.estimated_completion is None
    assert assessment.completion_unknown_reason == "nothing_planned"


def test_an_order_blocked_on_materials_says_so_rather_than_nothing_planned(
    session, customer, fabric, yarn
):
    """Three different conditions produced one message. They are not the same."""
    order = make_sales_order(session, customer, fabric, quantity=D("5000"), promised_in=30)
    make_batch(session, fabric, order, quantity=D("5000"), start_in=2)
    session.flush()

    assessment = orders.assess_order(session, order)
    assert assessment.estimated_completion is None
    assert assessment.completion_unknown_reason == "materials_not_covered"


# --- On-time delivery -------------------------------------------------------


def test_on_time_delivery_is_measured_from_actual_deliveries(
    session, customer, fabric, yarn
):
    """Not from an internal bookkeeping timestamp.

    An order can be stamped closed before its goods arrive — or never stamped
    at all — and counting that as on time makes the owner's headline
    reliability number a fiction.
    """
    from textileops.services import metrics

    _yarn(session, yarn, "6000")

    # Delivered, genuinely on time.
    good = make_sales_order(session, customer, fabric, number="SO-GOOD",
                            quantity=D("100"), promised_in=-10)
    # Planned first, then credited — the order real events happen in. Setting
    # shipped_quantity before the shipment exists writes a state the
    # application cannot produce, and the over-shipping guard now says so.
    good_shipment = shipments.create_shipment(
        session, number="SHP-GOOD", customer_id=customer.id,
        lines=[(good.lines[0].id, D("100"), M)],
    )
    good.lines[0].shipped_quantity = D("100")
    good.status = SalesOrderStatus.DELIVERED
    good_shipment.status = ShipmentStatus.DELIVERED
    good_shipment.dispatch_date = day(-15)
    good_shipment.actual_delivery_date = day(-12)

    # Marked delivered, but the goods are still on a lorry and already late.
    bad = make_sales_order(session, customer, fabric, number="SO-BAD",
                           quantity=D("100"), promised_in=-8)
    bad_shipment = shipments.create_shipment(
        session, number="SHP-BAD", customer_id=customer.id,
        lines=[(bad.lines[0].id, D("100"), M)],
    )
    bad.lines[0].shipped_quantity = D("100")
    bad.status = SalesOrderStatus.DELIVERED
    bad.closed_at = moment(-9)          # closed *before* the goods went out
    bad_shipment.status = ShipmentStatus.IN_TRANSIT
    bad_shipment.dispatch_date = day(-5)
    bad_shipment.expected_delivery_date = day(-2)
    session.flush()

    result = metrics.on_time_delivery(session)
    assert result.measured == 1, "only one order has a confirmed delivery date"
    assert result.on_time == 1
    assert result.percentage == 100
    assert result.unmeasured == 1, "the undelivered one must be disclosed, not counted"


def test_an_order_closed_with_no_delivery_evidence_is_never_counted_on_time(
    session, customer, fabric
):
    from textileops.services import metrics

    order = make_sales_order(session, customer, fabric, quantity=D("100"), promised_in=-10)
    order.lines[0].shipped_quantity = D("100")
    order.status = SalesOrderStatus.CLOSED
    order.closed_at = None
    session.flush()

    result = metrics.on_time_delivery(session)
    assert result.measured == 0
    assert result.percentage is None, "no evidence means no percentage, not 100%"
    assert result.unmeasured == 1


# --- Coverage source ----------------------------------------------------------


def test_an_uncovered_requirement_does_not_claim_to_come_from_stock(
    session, fabric, yarn
):
    """A null arrival date meant two opposite things.

    Supply already in the building has no arrival date, and neither does supply
    that does not exist. The coverage screen read the null and printed "from
    stock" — the most reassuring of the two readings — against material nobody
    had.
    """
    batch = make_batch(session, fabric, quantity=D("5000"))
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    allocation = next(
        a for a in result.allocations if a.requirement.production_batch_id == batch.id
    )

    assert allocation.covered_quantity == ZERO, "there is no yarn at all"
    assert allocation.covered_by_date is None
    assert allocation.coverage_source == "uncovered", (
        "a requirement nothing can satisfy was reported as covered from stock"
    )


def test_a_requirement_met_from_stock_says_so(session, fabric, yarn):
    """The other side of the same null: real stock must still read as stock."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-{uuid.uuid4().hex[:8].upper()}",
        unit=UnitOfMeasure.KG,
        quantity=D("5000.000"),
        material_id=yarn.id,
    )
    batch = make_batch(session, fabric, quantity=D("1000"))
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    allocation = next(
        a for a in result.allocations if a.requirement.production_batch_id == batch.id
    )

    assert allocation.shortfall_quantity == ZERO
    assert allocation.covered_by_date is None
    assert allocation.coverage_source == "stock"


# --- Supplier scoring ---------------------------------------------------------


def test_a_supplier_who_sends_nothing_loses_their_rating_without_delivering(
    session, supplier, yarn
):
    """The score could only move when a supplier *delivered*.

    So the commonest kind of lateness — sending nothing at all — never moved
    it. A supplier whose promised date quietly passed kept the rating their
    last delivery earned, and the procurement screen kept recommending them.
    """
    delivered_on_time = make_purchase_order(
        session, supplier, yarn, quantity=D("500"), expected_in=-5
    )
    procurement.receive(
        session,
        delivered_on_time.lines[0],
        accepted_quantity=D("500"),
        received_at=moment(-6),
    )
    session.flush()
    assert supplier.on_time_rate == D("1.0000"), "one line, delivered early"

    # A second order is promised and the date passes in silence. Nothing is
    # received, so nothing in the receipt path runs.
    make_purchase_order(session, supplier, yarn, quantity=D("500"), expected_in=-2)
    session.flush()
    assert supplier.on_time_rate == D("1.0000"), (
        "precondition: the stale score is still showing"
    )

    changed = procurement.recompute_all_supplier_rates(session)

    assert changed >= 1
    assert supplier.on_time_rate == D("0.5000"), (
        "the overdue line with nothing received was never counted against them"
    )
