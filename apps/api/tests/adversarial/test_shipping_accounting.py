"""Shipment accounting, attacked the way inventory was.

Shipping is where a quantity leaves the building and an invoice usually
follows. Over-shipping is therefore not a tidy-up problem: it is cloth given
away, and often billed for twice.

The invariant this file exists to defend:

    for every sales order line, shipped_quantity <= quantity

enforced server-side and in the database, not in a form.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.conftest import day, make_sales_order
from textileops.core.errors import ConflictError, ValidationError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import LotStatus, SalesOrderStatus
from textileops.models.inventory import InventoryMovement
from textileops.services import inventory, shipments

D = Decimal
ZERO = D("0.000")


@pytest.fixture
def order_with_stock(session, customer, fabric, yarn):
    """A 1,000 m order with 1,000 m of finished cloth ready to go."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("1000.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.AVAILABLE,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    session.flush()
    return order, order.lines[0]


def _ship(session, order_line, quantity, *, number=None):
    shipment = shipments.create_shipment(
        session,
        number=number or f"SHP-{uuid.uuid4().hex[:6].upper()}",
        customer_id=order_line.sales_order.customer_id,
        lines=[(order_line.id, D(quantity), order_line.unit)],
        expected_delivery_date=day(5),
    )
    session.flush()
    shipments.dispatch(session, shipment)
    session.flush()
    return shipment


# --- The invariant ------------------------------------------------------------


def test_exact_fulfilment_closes_the_line(session, order_with_stock):
    _order, line = order_with_stock
    _ship(session, line, "1000")
    assert line.shipped_quantity == D("1000.000")
    assert line.outstanding_quantity == ZERO


def test_two_partial_shipments_sum_to_the_order(session, order_with_stock):
    _order, line = order_with_stock
    _ship(session, line, "600")
    _ship(session, line, "400")
    assert line.shipped_quantity == D("1000.000")
    assert line.outstanding_quantity == ZERO


def test_a_third_shipment_beyond_the_order_is_refused(session, order_with_stock, fabric):
    """600 + 400 fulfils a 1,000 m order. Another 200 is cloth given away."""
    _order, line = order_with_stock
    # Plenty of finished stock, so nothing but the invariant can stop this.
    inventory.create_lot(
        session,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("5000.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.AVAILABLE,
    )
    session.flush()

    _ship(session, line, "600")
    _ship(session, line, "400")

    with pytest.raises((ConflictError, ValidationError)):
        _ship(session, line, "200")

    session.refresh(line)
    assert line.shipped_quantity == D("1000.000"), "the refused shipment changed nothing"


def test_a_single_shipment_larger_than_the_order_is_refused(
    session, order_with_stock, fabric
):
    _order, line = order_with_stock
    inventory.create_lot(
        session,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("5000.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.AVAILABLE,
    )
    session.flush()

    with pytest.raises((ConflictError, ValidationError)):
        _ship(session, line, "1500")

    session.refresh(line)
    assert line.shipped_quantity == ZERO


def test_over_shipping_is_refused_by_the_database_too(session, order_with_stock):
    """Belt and braces: the service can be bypassed, the constraint cannot."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    _order, line = order_with_stock
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "update sales_order_lines set shipped_quantity = quantity + 1 "
                    "where id = :id"
                ),
                {"id": line.id},
            )
            session.flush()
    finally:
        savepoint.rollback()


def test_a_shipment_in_another_unit_still_respects_the_order_quantity(
    session, customer, fabric, yarn
):
    """1,000 m ordered; 1,200 yards is more than 1,000 metres."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("5000.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.AVAILABLE,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    session.flush()
    line = order.lines[0]

    with pytest.raises((ConflictError, ValidationError)):
        shipment = shipments.create_shipment(
            session,
            number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            lines=[(line.id, D("1200"), UnitOfMeasure.YARD)],
        )
        session.flush()
        shipments.dispatch(session, shipment)
        session.flush()


# --- Degenerate quantities ----------------------------------------------------


def test_a_zero_quantity_shipment_line_is_refused(session, order_with_stock, customer):
    _order, line = order_with_stock
    with pytest.raises(ValidationError):
        shipments.create_shipment(
            session,
            number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            lines=[(line.id, ZERO, line.unit)],
        )


def test_a_negative_quantity_shipment_line_is_refused(session, order_with_stock, customer):
    _order, line = order_with_stock
    with pytest.raises(ValidationError):
        shipments.create_shipment(
            session,
            number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            lines=[(line.id, D("-100"), line.unit)],
        )


def test_a_shipment_in_an_incompatible_unit_is_refused_when_it_is_planned(
    session, order_with_stock, customer
):
    """Kilograms of a fabric sold by the metre is a mistake, not a conversion.

    Caught at planning rather than at the loading bay: discovering it at
    dispatch means the lorry is already there.
    """
    _order, line = order_with_stock
    with pytest.raises((ValidationError, ConflictError)):
        shipments.create_shipment(
            session,
            number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            lines=[(line.id, D("100"), UnitOfMeasure.KG)],
        )


# --- Order state --------------------------------------------------------------


def test_a_cancelled_order_cannot_be_shipped(session, order_with_stock, customer):
    order, line = order_with_stock
    order.status = SalesOrderStatus.CANCELLED
    session.flush()

    with pytest.raises((ConflictError, ValidationError)):
        _ship(session, line, "100")

    session.refresh(line)
    assert line.shipped_quantity == ZERO


def test_a_closed_order_cannot_be_shipped_again(session, order_with_stock):
    order, line = order_with_stock
    _ship(session, line, "1000")
    order.status = SalesOrderStatus.CLOSED
    session.flush()

    with pytest.raises((ConflictError, ValidationError)):
        _ship(session, line, "10")


# --- Replay and idempotency ---------------------------------------------------


def test_dispatching_the_same_shipment_twice_ships_once(session, order_with_stock):
    """Dispatch is the physical act; a retry must not repeat it."""
    order, line = order_with_stock
    shipment = shipments.create_shipment(
        session,
        number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
        customer_id=order.customer_id,
        lines=[(line.id, D("400"), line.unit)],
    )
    session.flush()

    shipments.dispatch(session, shipment, idempotency_key="dispatch-1")
    session.flush()
    shipments.dispatch(session, shipment, idempotency_key="dispatch-1")
    session.flush()

    assert line.shipped_quantity == D("400.000"), "the retry shipped the cloth twice"
    movements = session.scalar(
        select(func.count(InventoryMovement.id)).where(
            InventoryMovement.movement_type == "shipment"
        )
    )
    assert movements == 1


def test_quarantined_cloth_is_never_shipped(session, customer, fabric):
    """Failing QC must take stock out of reach of the loading bay."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-QC-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("1000.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.QUARANTINE,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    session.flush()
    line = order.lines[0]

    shipment = shipments.create_shipment(
        session,
        number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer.id,
        lines=[(line.id, D("1000"), line.unit)],
    )
    session.flush()
    shipments.dispatch(session, shipment)
    session.flush()

    assert line.shipped_quantity == ZERO, "quarantined cloth left the building"
    assert shipment.notes and "short" in shipment.notes.lower()


def test_the_credit_is_what_left_not_what_was_packed(session, customer, fabric):
    """Only 300 m exists against a 1,000 m plan."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("300.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.AVAILABLE,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    session.flush()
    line = order.lines[0]

    _ship(session, line, "1000")

    assert line.shipped_quantity == D("300.000"), (
        "the order was credited with cloth that was never loaded"
    )
    assert line.outstanding_quantity == D("700.000")


def test_shipping_across_two_order_lines_respects_each_line_separately(
    session, customer, fabric
):
    """One shipment, two lines: a surplus on one must not cover the other."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:6].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("5000.000"),
        fabric_spec_id=fabric.id,
        status=LotStatus.AVAILABLE,
    )
    order_a = make_sales_order(session, customer, fabric, quantity=D("500"))
    order_b = make_sales_order(session, customer, fabric, quantity=D("500"))
    session.flush()
    line_a, line_b = order_a.lines[0], order_b.lines[0]

    with pytest.raises((ConflictError, ValidationError)):
        shipments.create_shipment(
            session,
            number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            lines=[
                (line_a.id, D("500"), line_a.unit),
                (line_b.id, D("900"), line_b.unit),  # over its own line
            ],
        )

    session.refresh(line_a)
    session.refresh(line_b)
    assert line_a.shipped_quantity == ZERO
    assert line_b.shipped_quantity == ZERO
