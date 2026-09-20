"""What the database looks like after something fails half way through.

A process is killed, a connection drops, a worker is redeployed mid-job. The
question is never whether that happens but what is left behind when it does:
a half-applied receipt is worse than no receipt, because nothing downstream
can tell the difference between it and a real one.

Each test here forces a failure at a specific point and then asserts the
surviving state is one a person could act on — either the whole change or
none of it, never half.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.conftest import make_batch, make_purchase_order, make_sales_order
from textileops.core.errors import ConflictError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import MovementType, PurchaseOrderStatus
from textileops.models.inventory import InventoryLot, InventoryMovement
from textileops.models.procurement import PurchaseOrderReceipt
from textileops.services import inventory, procurement, production

D = Decimal
ZERO = D("0.000")


class InjectedFailure(RuntimeError):
    """Stands in for the process dying at an inconvenient moment."""


def _ledger_total(session, lot_id) -> Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
            InventoryMovement.lot_id == lot_id
        )
    )


def test_a_receipt_that_fails_before_commit_leaves_no_trace_of_itself(
    session, supplier, yarn
):
    """Half a receipt is indistinguishable from a whole one to everything
    downstream, so it must not survive."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"))
    session.flush()
    line = po.lines[0]

    lots_before = session.scalar(select(func.count(InventoryLot.id)))
    receipts_before = session.scalar(select(func.count(PurchaseOrderReceipt.id)))

    savepoint = session.begin_nested()
    try:
        procurement.receive(session, line, accepted_quantity=D("400"))
        session.flush()
        raise InjectedFailure("the worker died after writing, before committing")
    except InjectedFailure:
        savepoint.rollback()

    session.expire_all()
    assert session.scalar(select(func.count(InventoryLot.id))) == lots_before
    assert session.scalar(select(func.count(PurchaseOrderReceipt.id))) == receipts_before
    assert line.received_quantity == ZERO, "the line kept a receipt that never happened"
    assert po.status != PurchaseOrderStatus.PARTIALLY_RECEIVED


def test_a_receipt_retried_after_a_failure_lands_exactly_once(session, supplier, yarn):
    """The realistic sequence: it failed, the worker retried, it succeeded."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"))
    session.flush()
    line = po.lines[0]
    key = "delivery-note-8841"

    savepoint = session.begin_nested()
    try:
        procurement.receive(
            session, line, accepted_quantity=D("400"), idempotency_key=key
        )
        session.flush()
        raise InjectedFailure("died before commit")
    except InjectedFailure:
        savepoint.rollback()

    session.expire_all()
    outcome = procurement.receive(
        session, line, accepted_quantity=D("400"), idempotency_key=key
    )
    session.flush()

    assert not outcome.was_replay, "the rolled-back attempt was treated as already done"
    assert line.received_quantity == D("400.000")
    receipts = session.scalar(
        select(func.count(PurchaseOrderReceipt.id)).where(
            PurchaseOrderReceipt.purchase_order_line_id == line.id
        )
    )
    assert receipts == 1, "the retry produced a second receipt for one delivery"


def test_a_failed_issue_does_not_leave_stock_drawn_down(session, fabric, yarn, customer):
    """The movement and the balance must move together or not at all."""
    lot = inventory.create_lot(
        session,
        lot_code="LOT-FAIL-1",
        unit=UnitOfMeasure.KG,
        quantity=D("1000.000"),
        material_id=yarn.id,
    )
    session.flush()
    lot_id = lot.id

    savepoint = session.begin_nested()
    try:
        inventory.post_movement(
            session,
            lot=lot,
            movement_type=MovementType.ISSUE,
            quantity=D("250.000"),
        )
        session.flush()
        raise InjectedFailure("died between the movement and the commit")
    except InjectedFailure:
        savepoint.rollback()

    session.expire_all()
    restored = session.get(InventoryLot, lot_id)
    assert restored is not None
    assert restored.quantity_on_hand == D("1000.000")
    assert _ledger_total(session, lot_id) == restored.quantity_on_hand, (
        "the ledger and the balance parted company across a rollback"
    )


def test_a_batch_whose_completion_fails_does_not_keep_the_output(
    session, fabric, yarn, customer
):
    """Output stock without a completed batch is cloth from nowhere."""
    inventory.create_lot(
        session,
        lot_code="LOT-FAIL-2",
        unit=UnitOfMeasure.KG,
        quantity=D("5000.000"),
        material_id=yarn.id,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()

    production.start_batch(session, batch)
    production.issue_materials(session, batch)
    session.flush()

    lots_before = session.scalar(select(func.count(InventoryLot.id)))
    produced_before = order.lines[0].produced_quantity

    savepoint = session.begin_nested()
    try:
        production.record_output(
            session, batch, good_quantity=D("1000"), unit=UnitOfMeasure.METRE
        )
        session.flush()
        raise InjectedFailure("died after recording output")
    except InjectedFailure:
        savepoint.rollback()

    session.expire_all()
    assert session.scalar(select(func.count(InventoryLot.id))) == lots_before
    assert order.lines[0].produced_quantity == produced_before, (
        "the order was credited with production that was rolled back"
    )


def test_the_accounting_identity_survives_a_failure_at_every_step(
    session, fabric, yarn, customer
):
    """Run the lifecycle, failing at each stage, and check the books each time.

    The invariant is the one a stock ledger lives or dies by: every lot's
    stored balance equals the sum of its own movements. It has to hold after a
    failure just as it does after a success.
    """
    inventory.create_lot(
        session,
        lot_code="LOT-FAIL-3",
        unit=UnitOfMeasure.KG,
        quantity=D("5000.000"),
        material_id=yarn.id,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()

    steps = [
        lambda: production.start_batch(session, batch),
        lambda: production.issue_materials(session, batch),
        lambda: production.record_output(
            session, batch, good_quantity=D("1000"), unit=UnitOfMeasure.METRE
        ),
    ]

    for step in steps:
        savepoint = session.begin_nested()
        try:
            step()
            session.flush()
            raise InjectedFailure("died mid-step")
        except InjectedFailure:
            savepoint.rollback()
        session.expire_all()

        for lot in session.scalars(select(InventoryLot)).all():
            assert lot.quantity_on_hand == _ledger_total(session, lot.id), (
                f"{lot.lot_code} disagrees with its ledger after a rolled-back step"
            )
            assert lot.quantity_on_hand >= ZERO

        # Having rolled the step back, apply it for real and check again.
        step()
        session.flush()
        for lot in session.scalars(select(InventoryLot)).all():
            assert lot.quantity_on_hand == _ledger_total(session, lot.id), (
                f"{lot.lot_code} disagrees with its ledger after a completed step"
            )


def test_a_movement_is_never_written_without_its_balance_moving(session, yarn):
    """The two writes are one fact; there is no legitimate state between them."""
    lot = inventory.create_lot(
        session,
        lot_code="LOT-FAIL-4",
        unit=UnitOfMeasure.KG,
        quantity=D("100.000"),
        material_id=yarn.id,
    )
    session.flush()

    with pytest.raises(ConflictError):
        inventory.post_movement(
            session,
            lot=lot,
            movement_type=MovementType.ISSUE,
            quantity=D("500.000"),  # more than exists
        )
    session.flush()

    assert lot.quantity_on_hand == D("100.000")
    assert _ledger_total(session, lot.id) == D("100.000"), (
        "a refused issue still wrote a movement"
    )
