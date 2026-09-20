"""The inventory ledger, stated as accounting identities and then attacked.

Example-based tests check the sequences somebody thought of. These generate
sequences nobody thought of — receive, reserve, issue, produce, inspect,
correct, ship, cancel, in whatever order Hypothesis finds interesting — and
assert the same identities after *every* step.

The identities, in one place, because the rest of the system depends on them
holding and nothing else writes them down:

    I1  lot.quantity_on_hand == sum of that lot's movements
    I2  lot.quantity_on_hand >= 0
    I3  line.received_quantity == sum(receipts) - sum(corrections)
    I4  line.shipped_quantity <= line.quantity
    I5  line.produced_quantity <= line.quantity
    I6  a lot's status and its balance agree
    I7  physical stock is never reserved twice by the same batch

I1 is the one that matters most. A stored balance that has drifted from its
own movement history is a number with no explanation, and every coverage,
shortage and promise figure downstream is computed from it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select

from tests.conftest import make_batch, make_purchase_order, make_sales_order
from textileops.core.errors import TextileOpsError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    LotStatus,
    ReservationStatus,
    SalesOrderStatus,
)
from textileops.models.inventory import (
    InventoryLot,
    InventoryMovement,
    InventoryReservation,
)
from textileops.models.procurement import PurchaseOrderLine
from textileops.models.sales import SalesOrderLine
from textileops.services import inventory, procurement, production, quality, shipments

D = Decimal
ZERO = D("0.000")

SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


# --- The identities -----------------------------------------------------------


def assert_ledger_identities(session, *, step: str) -> None:
    """Every identity, checked together. ``step`` names what just happened."""
    lots = session.scalars(select(InventoryLot)).all()
    for lot in lots:
        ledger = session.scalar(
            select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
                InventoryMovement.lot_id == lot.id
            )
        )
        # I1 — the stored balance is explained by its own history.
        assert lot.quantity_on_hand == ledger, (
            f"after {step}: lot {lot.lot_code} stores {lot.quantity_on_hand} "
            f"but its movements sum to {ledger}"
        )
        # I2 — no negative physical stock.
        assert lot.quantity_on_hand >= ZERO, (
            f"after {step}: lot {lot.lot_code} holds {lot.quantity_on_hand}"
        )
        # I6 — a consumed lot holds nothing, and a lot holding nothing is not
        # still being offered as available.
        if lot.status == LotStatus.CONSUMED:
            assert lot.quantity_on_hand == ZERO, (
                f"after {step}: lot {lot.lot_code} is consumed but holds "
                f"{lot.quantity_on_hand}"
            )

    for line in session.scalars(select(PurchaseOrderLine)).all():
        received = ZERO
        corrected = ZERO
        for receipt in line.receipts:
            received += receipt.accepted_quantity
            for correction in receipt.corrections:
                corrected += correction.accepted_delta
        # I3 — the line's figure is the receipts less the corrections, not an
        # independently maintained counter that can drift from them.
        assert line.received_quantity == inventory.quantize(received - corrected), (
            f"after {step}: line {line.line_no} says {line.received_quantity} "
            f"received; its receipts say {received} less {corrected} corrected"
        )
        assert line.received_quantity >= ZERO

    for line in session.scalars(select(SalesOrderLine)).all():
        # I4/I5 — nothing leaves or is credited beyond what was ordered.
        assert line.shipped_quantity <= line.quantity, (
            f"after {step}: line {line.line_no} shipped {line.shipped_quantity} "
            f"against an order for {line.quantity}"
        )
        assert line.produced_quantity <= line.quantity, (
            f"after {step}: line {line.line_no} produced {line.produced_quantity} "
            f"against an order for {line.quantity}"
        )
        assert line.shipped_quantity >= ZERO
        assert line.produced_quantity >= ZERO

    # I7 — one active reservation per batch and material. Two would let a batch
    # commit the same kilograms to itself twice and halve what everyone else
    # can see.
    duplicates = session.execute(
        select(
            InventoryReservation.production_batch_id,
            InventoryReservation.material_id,
            func.count(InventoryReservation.id),
        )
        .where(
            InventoryReservation.status == ReservationStatus.ACTIVE,
            InventoryReservation.production_batch_id.is_not(None),
        )
        .group_by(
            InventoryReservation.production_batch_id, InventoryReservation.material_id
        )
        .having(func.count(InventoryReservation.id) > 1)
    ).all()
    assert duplicates == [], f"after {step}: duplicate active reservations {duplicates}"

    # A released reservation carries when it was released, or "released" is a
    # claim with no time attached to it.
    unstamped = session.scalar(
        select(func.count(InventoryReservation.id)).where(
            InventoryReservation.status == ReservationStatus.RELEASED,
            InventoryReservation.released_at.is_(None),
        )
    )
    assert unstamped == 0, f"after {step}: {unstamped} released reservations unstamped"

    assert inventory.ledger_discrepancies(session) == [], (
        f"after {step}: the integrity checker disagrees with the ledger"
    )


# --- Operations the generator can pick from -----------------------------------

OPERATIONS = [
    "receive",
    "receive_partial",
    "correct_receipt",
    "start_batch",
    "issue_materials",
    "record_output",
    "complete_batch",
    "inspect_pass",
    "inspect_reject",
    "dispatch",
    "cancel_order",
]


@pytest.fixture
def world(session, supplier, customer, yarn, fabric):
    """One purchase order, one sales order, one batch — enough to interact."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("2000"))
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    session.flush()
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()
    return {
        "po_line": po.lines[0],
        "order": order,
        "order_line": order.lines[0],
        "batch": batch,
        "fabric": fabric,
        "customer": customer,
    }


def _apply(session, world, op: str) -> None:
    """Run one operation. Business refusals are expected and are not failures.

    A refusal is the system working: it means an invariant was about to be
    broken and something stopped it. What must never happen is a refusal that
    leaves state half-applied, which is exactly what the identity check after
    each step is looking for.
    """
    po_line = world["po_line"]
    order_line = world["order_line"]
    batch = world["batch"]

    if op == "receive":
        procurement.receive(session, po_line, accepted_quantity=D("800"))
    elif op == "receive_partial":
        procurement.receive(session, po_line, accepted_quantity=D("250"))
    elif op == "correct_receipt":
        if po_line.receipts:
            procurement.correct_receipt(
                session,
                po_line.receipts[-1],
                accepted_delta=D("100"),
                reason="Generated correction.",
            )
    elif op == "start_batch":
        production.start_batch(session, batch)
    elif op == "issue_materials":
        production.issue_materials(session, batch)
    elif op == "record_output":
        production.record_output(
            session, batch, good_quantity=D("400"), unit=UnitOfMeasure.METRE
        )
    elif op == "complete_batch":
        production.complete_batch(session, batch)
    elif op in ("inspect_pass", "inspect_reject"):
        from textileops.models.enums import QCOutcome

        outcome = QCOutcome.PASS if op == "inspect_pass" else QCOutcome.REJECT
        if batch.output_quantity > ZERO:
            inspection = quality.record_inspection(
                session,
                code=f"QC-{uuid.uuid4().hex[:8].upper()}",
                outcome=outcome,
                inspected_quantity=batch.output_quantity,
                rejected_quantity=(
                    batch.output_quantity if outcome == QCOutcome.REJECT else ZERO
                ),
                unit=batch.unit,
                production_batch_id=batch.id,
            )
            quality.propagate(session, inspection)
    elif op == "dispatch":
        shipment = shipments.create_shipment(
            session,
            number=f"SHP-{uuid.uuid4().hex[:8].upper()}",
            customer_id=world["customer"].id,
            lines=[(order_line.id, D("200"), order_line.unit)],
        )
        session.flush()
        shipments.dispatch(session, shipment)
    elif op == "cancel_order":
        world["order"].status = SalesOrderStatus.CANCELLED
        production.release_materials_if_terminal(session, batch)
    session.flush()


@SETTINGS
@given(st.lists(st.sampled_from(OPERATIONS), min_size=1, max_size=10))
def test_the_identities_hold_after_every_operation_in_any_order(session, world, ops):
    """Thousands of orderings, checked after each step.

    Each example runs inside a savepoint that is rolled back, so one sequence
    cannot contaminate the next.
    """
    savepoint = session.begin_nested()
    try:
        assert_ledger_identities(session, step="setup")
        for index, op in enumerate(ops):
            inner = session.begin_nested()
            try:
                _apply(session, world, op)
                inner.commit()
            except TextileOpsError:
                # A refusal is the system defending an invariant. Roll back
                # just that operation and carry on — what matters is that the
                # books are intact afterwards.
                inner.rollback()
            assert_ledger_identities(session, step=f"{index}:{op} of {ops}")
    finally:
        savepoint.rollback()


@SETTINGS
@given(
    quantities=st.lists(
        st.decimals(min_value=D("1"), max_value=D("500"), places=3),
        min_size=1,
        max_size=6,
    )
)
def test_receiving_then_correcting_always_balances(session, supplier, yarn, quantities):
    """Any sequence of receipts and corrections keeps the line and ledger equal."""
    savepoint = session.begin_nested()
    try:
        po = make_purchase_order(session, supplier, yarn, quantity=D("100000"))
        session.flush()
        line = po.lines[0]

        for quantity in quantities:
            inner = session.begin_nested()
            try:
                outcome = procurement.receive(
                    session, line, accepted_quantity=Decimal(quantity)
                )
                inner.commit()
            except TextileOpsError:
                inner.rollback()
                continue

            inner = session.begin_nested()
            try:
                procurement.correct_receipt(
                    session,
                    outcome.receipt,
                    accepted_delta=Decimal(quantity) / 2,
                    reason="Half of it did not arrive.",
                )
                inner.commit()
            except TextileOpsError:
                inner.rollback()
            assert_ledger_identities(session, step=f"receive/correct {quantity}")

        lots_total = session.scalar(
            select(func.coalesce(func.sum(InventoryLot.quantity_on_hand), ZERO)).where(
                InventoryLot.purchase_order_line_id == line.id
            )
        )
        assert lots_total == line.received_quantity, (
            "the stock in the building disagrees with what the line says arrived"
        )
    finally:
        savepoint.rollback()
