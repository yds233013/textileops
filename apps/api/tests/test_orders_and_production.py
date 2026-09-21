"""Order risk, and the production schedule model that drives it."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import (
    day,
    make_batch,
    make_purchase_order,
    make_sales_order,
    moment,
)
from textileops.core.errors import IllegalStateTransition, ValidationError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    LotStatus,
    ProductionStatus,
    RiskLevel,
    SalesOrderStatus,
)
from textileops.services import inventory, orders, production

D = Decimal


def _stock(session, yarn, quantity="3000"):
    return inventory.create_lot(
        session,
        lot_code=f"LOT-{quantity}",
        material_id=yarn.id,
        quantity=D(quantity),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )


# --- Risk ladder --------------------------------------------------------------


def test_order_covered_by_finished_stock_is_on_track(session, customer, fabric):
    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=20)
    inventory.create_lot(
        session,
        lot_code="LOT-FG",
        fabric_spec_id=fabric.id,
        quantity=D("1200"),
        unit=UnitOfMeasure.METRE,
        received_at=moment(-1),
    )
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.risk == RiskLevel.ON_TRACK
    assert assessment.lines[0].to_produce == D("0.000")


def test_order_is_late_once_the_promised_date_has_passed(session, customer, fabric, yarn):
    _stock(session, yarn)
    order = make_sales_order(session, customer, fabric, promised_in=-2)
    make_batch(session, fabric, order, start_in=-5)
    session.flush()
    assert orders.assess_order(session, order).risk == RiskLevel.LATE


def test_order_is_at_risk_when_the_batch_finishes_after_the_promise(
    session, customer, fabric, yarn
):
    _stock(session, yarn)
    order = make_sales_order(session, customer, fabric, promised_in=6)
    make_batch(session, fabric, order, start_in=1, days=10)
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.risk == RiskLevel.AT_RISK
    assert assessment.days_ahead is not None and assessment.days_ahead < 0


def test_order_is_watched_when_the_buffer_is_thin(session, customer, fabric, yarn):
    """Completion lands inside the configured buffer: not at risk, but not comfortable."""
    _stock(session, yarn)
    order = make_sales_order(session, customer, fabric, promised_in=10)
    make_batch(session, fabric, order, start_in=1, days=8)  # ready day 9, promised day 10
    session.flush()
    assert orders.assess_order(session, order).risk == RiskLevel.WATCH


def test_a_late_batch_with_a_long_buffer_leaves_the_order_on_track(
    session, customer, fabric, yarn
):
    """Scenario F: production slips, the customer is still safe."""
    _stock(session, yarn)
    order = make_sales_order(session, customer, fabric, promised_in=40)
    batch = make_batch(session, fabric, order, start_in=-4, days=10)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(0))  # started four days late
    production.recompute_estimated_completion(session, batch)
    session.flush()

    assert batch.estimated_completion > batch.planned_completion
    delays = {d.batch.code: d for d in production.delayed_batches(session)}
    assert batch.code in delays
    assert orders.assess_order(session, order).risk == RiskLevel.ON_TRACK


def test_an_order_with_no_stock_and_no_plan_cannot_be_called_on_track(
    session, customer, fabric
):
    order = make_sales_order(session, customer, fabric, promised_in=30)
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.estimated_completion is None
    assert assessment.risk == RiskLevel.AT_RISK


def test_uncoverable_materials_make_the_order_at_risk(
    session, customer, fabric, yarn
):
    """No yarn, no purchase order: the batch has no honest completion date."""
    order = make_sales_order(session, customer, fabric, promised_in=40)
    make_batch(session, fabric, order, start_in=2, days=5)
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.material_readiness == "short"
    assert assessment.estimated_completion is None
    assert assessment.risk == RiskLevel.AT_RISK


def test_outstanding_value_is_unavailable_when_prices_are_missing(
    session, customer, fabric, yarn
):
    _stock(session, yarn)
    order = make_sales_order(session, customer, fabric, unit_price=None)
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.outstanding_value is None
    assert assessment.value_basis == "unavailable"


def test_outstanding_value_uses_the_unshipped_quantity(session, customer, fabric, yarn):
    _stock(session, yarn)
    order = make_sales_order(
        session, customer, fabric, quantity=D("1000"), unit_price=D("2.00")
    )
    order.lines[0].shipped_quantity = D("400")
    session.flush()
    assessment = orders.assess_order(session, order)
    assert assessment.outstanding_value == D("1200.00")


# --- Production schedule ------------------------------------------------------


def test_estimate_is_start_plus_planned_duration(session, fabric, yarn):
    _stock(session, yarn)
    batch = make_batch(session, fabric, start_in=2, days=8)
    production.recompute_estimated_completion(session, batch)
    assert batch.estimated_completion == day(10)


def test_a_batch_cannot_start_before_its_materials_are_on_site(
    session, fabric, yarn, supplier
):
    """This is where procurement reality enters the production plan."""
    batch = make_batch(session, fabric, quantity=D("5000"), start_in=1, days=6)
    make_purchase_order(session, supplier, yarn, quantity=D("3000"), expected_in=9)
    session.flush()

    assert production.material_ready_date(session, batch) == day(9)
    production.recompute_estimated_completion(session, batch)
    assert batch.estimated_completion == day(15)


def test_no_completion_date_is_offered_when_materials_are_not_covered(
    session, fabric, yarn
):
    batch = make_batch(session, fabric, quantity=D("5000"))
    session.flush()
    assert production.material_ready_date(session, batch) is None
    assert production.recompute_estimated_completion(session, batch) is None


def test_a_started_batch_keeps_its_actual_start(session, fabric, yarn):
    _stock(session, yarn)
    batch = make_batch(session, fabric, start_in=-3, days=6)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-1))
    assert batch.estimated_completion == day(5)


def test_illegal_status_transitions_are_refused(session, fabric, yarn):
    _stock(session, yarn)
    batch = make_batch(session, fabric)
    with pytest.raises(IllegalStateTransition):
        production.complete_batch(session, batch)  # planned → completed


def test_blocking_a_batch_requires_a_reason(session, fabric, yarn):
    _stock(session, yarn)
    batch = make_batch(session, fabric)
    with pytest.raises(ValidationError):
        production.block_batch(session, batch, "")


def test_output_creates_quarantined_stock_and_advances_the_order_line(
    session, customer, fabric, yarn
):
    _stock(session, yarn)
    order = make_sales_order(session, customer, fabric, quantity=D("5000"))
    batch = make_batch(session, fabric, order, quantity=D("5000"))
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)
    lot = production.record_output(
        session, batch, good_quantity=D("4850"), wastage_quantity=D("150")
    )
    session.flush()

    assert lot is not None
    # Output is quarantined until QC releases it: it is not sellable yet.
    assert lot.status == LotStatus.QUARANTINE
    assert batch.output_quantity == D("4850.000")
    assert batch.wastage_quantity == D("150.000")
    assert batch.yield_pct == D("0.9700")

    production.complete_batch(session, batch)
    session.flush()
    assert order.lines[0].produced_quantity == D("4850.000")
    assert batch.status == ProductionStatus.COMPLETED


# --- Material consumption -----------------------------------------------------


def test_completing_a_batch_consumes_its_materials(session, customer, fabric, yarn):
    """Stock must go down when production burns it.

    Without this, every completed batch gives its reservation back while the
    yarn it actually used still appears on the shelf, and the next coverage run
    schedules work against material that no longer exists.
    """
    lot = _stock(session, yarn, "3000")
    order = make_sales_order(session, customer, fabric, quantity=D("5000"))
    batch = make_batch(session, fabric, order, quantity=D("5000"))
    required = batch.requirements[0].required_quantity
    assert required == D("1563.158")

    production.schedule_batch(session, batch)
    production.start_batch(session, batch)
    production.record_output(session, batch, good_quantity=D("5000"))
    production.complete_batch(session, batch)
    session.flush()

    # The yarn left the shelf, and the ledger says so.
    assert lot.quantity_on_hand == D("1436.842")
    assert inventory.recompute_lot_on_hand(session, lot) == lot.quantity_on_hand
    assert batch.requirements[0].issued_quantity == required
    assert batch.requirements[0].outstanding_quantity == D("0.000")

    position = inventory.material_position(session, yarn.id)
    assert position.on_hand == D("1436.842")
    assert position.reserved == D("0.000")  # the reservation was consumed, not just released


def test_issuing_material_is_idempotent(session, fabric, yarn):
    lot = _stock(session, yarn, "3000")
    batch = make_batch(session, fabric, quantity=D("5000"))
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)
    session.flush()

    first = production.issue_materials(session, batch)
    after_first = lot.quantity_on_hand
    second = production.issue_materials(session, batch)
    session.flush()

    assert first.issued
    assert not second.issued  # nothing outstanding the second time
    assert lot.quantity_on_hand == after_first


def test_a_shortfall_at_issue_is_reported_not_invented(session, fabric, yarn):
    """Issuing more than exists must not create a negative balance."""
    _stock(session, yarn, "500")
    batch = make_batch(session, fabric, quantity=D("5000"))
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)
    session.flush()

    result = production.issue_materials(session, batch)
    session.flush()

    assert result.issued[yarn.code] == D("500.000")
    assert result.shortfalls[yarn.code] == D("1063.158")
    assert inventory.material_position(session, yarn.id).on_hand == D("0.000")
    assert inventory.ledger_discrepancies(session) == []


def test_a_shortfall_is_recorded_on_the_batch_rather_than_hidden(
    session, fabric, yarn
):
    _stock(session, yarn, "500")
    batch = make_batch(session, fabric, quantity=D("5000"))
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)
    production.record_output(session, batch, good_quantity=D("5000"))
    production.complete_batch(session, batch)
    session.flush()

    notes = " ".join(event.note or "" for event in batch.events)
    assert "Could not issue from stock" in notes
    assert "reconcile" in notes


# --- Finished goods are a single pool ----------------------------------------


def test_one_roll_of_stock_cannot_be_promised_to_two_customers(
    session, customer, fabric
):
    """The regression test for the worst kind of silent failure.

    1,000 m in stock and two orders for 1,000 m each. Comparing each order
    against the whole pool independently makes both look comfortable, and the
    shortfall surfaces on the second customer's promised date.
    """
    inventory.create_lot(
        session,
        lot_code="LOT-FG",
        fabric_spec_id=fabric.id,
        quantity=D("1000"),
        unit=UnitOfMeasure.METRE,
        received_at=moment(-1),
    )
    make_sales_order(
        session, customer, fabric, number="SO-EARLY", quantity=D("1000"), promised_in=10
    )
    make_sales_order(
        session, customer, fabric, number="SO-LATE", quantity=D("1000"), promised_in=25
    )
    session.flush()

    assessments = {a.number: a for a in orders.assess_open_orders(session)}

    # The earlier promise gets the stock.
    assert assessments["SO-EARLY"].lines[0].stock_available == D("1000.000")
    assert assessments["SO-EARLY"].lines[0].to_produce == D("0.000")
    assert assessments["SO-EARLY"].risk == RiskLevel.ON_TRACK

    # The later one is told the truth: it has to be made, and nothing is planned.
    assert assessments["SO-LATE"].lines[0].stock_available == D("0.000")
    assert assessments["SO-LATE"].lines[0].to_produce == D("1000.000")
    assert assessments["SO-LATE"].risk == RiskLevel.AT_RISK


def test_partial_stock_is_shared_in_promise_order(session, customer, fabric):
    inventory.create_lot(
        session,
        lot_code="LOT-FG",
        fabric_spec_id=fabric.id,
        quantity=D("1200"),
        unit=UnitOfMeasure.METRE,
        received_at=moment(-1),
    )
    make_sales_order(
        session, customer, fabric, number="SO-A", quantity=D("1000"), promised_in=5
    )
    make_sales_order(
        session, customer, fabric, number="SO-B", quantity=D("1000"), promised_in=15
    )
    session.flush()

    assessments = {a.number: a for a in orders.assess_open_orders(session)}
    assert assessments["SO-A"].lines[0].stock_available == D("1000.000")
    assert assessments["SO-B"].lines[0].stock_available == D("200.000")
    assert assessments["SO-B"].lines[0].to_produce == D("800.000")


def test_assessing_one_order_still_respects_other_orders_claims(
    session, customer, fabric
):
    """A single-order view must not quietly ignore everyone else's claims."""
    inventory.create_lot(
        session,
        lot_code="LOT-FG",
        fabric_spec_id=fabric.id,
        quantity=D("1000"),
        unit=UnitOfMeasure.METRE,
        received_at=moment(-1),
    )
    make_sales_order(
        session, customer, fabric, number="SO-FIRST", quantity=D("1000"), promised_in=5
    )
    later = make_sales_order(
        session, customer, fabric, number="SO-SECOND", quantity=D("1000"), promised_in=20
    )
    session.flush()

    assessment = orders.assess_order(session, later)
    assert assessment.lines[0].stock_available == D("0.000")


def test_dispatch_credits_only_what_actually_left(session, customer, fabric):
    """Crediting the packed quantity would close the line and hide the gap."""
    from textileops.core.units import UnitOfMeasure as U
    from textileops.services import shipments

    inventory.create_lot(
        session,
        lot_code="LOT-FG",
        fabric_spec_id=fabric.id,
        quantity=D("300"),
        unit=U.METRE,
        received_at=moment(-1),
    )
    order = make_sales_order(session, customer, fabric, quantity=D("500"))
    line = order.lines[0]
    shipment = shipments.create_shipment(
        session,
        number="SHP-SHORT",
        customer_id=customer.id,
        lines=[(line.id, D("500"), U.METRE)],
    )
    session.flush()

    shipments.dispatch(session, shipment, idempotency_key="dispatch-1")
    session.flush()

    # Only 300 m existed, so only 300 m is credited.
    assert line.shipped_quantity == D("300.000")
    assert line.outstanding_quantity == D("200.000")
    assert order.status != SalesOrderStatus.SHIPPED
    assert "short" in (shipment.notes or "")


def test_the_next_blocker_is_named_only_from_facts_on_the_assessment():
    """An order list shows one line of "what is in the way". It must never
    invent a cause, and must say nothing — not something reassuring — when
    nothing is in the way."""
    import datetime as dt
    import uuid

    from textileops.models.enums import RiskLevel, SalesOrderStatus
    from textileops.services.orders import MaterialReadiness, OrderAssessment, next_blocker

    def order(**overrides):
        base = {
            "order_id": uuid.uuid4(),
            "number": "SO-1",
            "customer_id": uuid.uuid4(),
            "customer_name": "C",
            "status": SalesOrderStatus.IN_PRODUCTION,
            "order_date": dt.date(2026, 9, 1),
            "promised_date": dt.date(2026, 10, 1),
            "currency": "INR",
            "risk": RiskLevel.ON_TRACK,
            "estimated_completion": dt.date(2026, 9, 20),
            "completion_unknown_reason": None,
            "days_ahead": 11,
            "material_readiness": MaterialReadiness.READY,
            "production_status": "in_progress",
            "qc_status": "not_inspected",
            "shipment_status": "not_shipped",
        }
        base.update(overrides)
        return OrderAssessment(**base)

    assert next_blocker(order()) is None
    assert next_blocker(order(status=SalesOrderStatus.DELIVERED, risk=RiskLevel.LATE)) is None
    assert "blocked" in next_blocker(order(blocked_reasons=["B-1: loom down"])).lower()
    assert "QC" in next_blocker(order(qc_status="rejected"))
    assert "short" in next_blocker(order(material_readiness=MaterialReadiness.SHORT)).lower()
    assert "passed" in next_blocker(order(risk=RiskLevel.LATE))
    assert "3 days after" in next_blocker(order(days_ahead=-3, risk=RiskLevel.AT_RISK))
    # A stopped batch outranks a late material: it is the thing to fix first.
    assert "blocked" in next_blocker(
        order(blocked_reasons=["B-1: loom down"], material_readiness=MaterialReadiness.PARTIAL)
    ).lower()
