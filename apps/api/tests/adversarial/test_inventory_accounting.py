"""Inventory as double-entry accounting.

The governing identity, which must hold after every operation:

    physical stock (all lots, any status)
        == opening + receipts + production output
           − consumption − scrap − shipments ± adjustments

and, separately:

    on_hand − reserved == available          (never negative)
    supply available to a batch              (never less than real stock)

Each test below is an attempt to break one of those.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from tests.adversarial.conftest import (
    active_reservations,
    assert_ledger_consistent,
    physical_total,
)
from tests.conftest import (
    make_batch,
    make_purchase_order,
    make_sales_order,
    moment,
)
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    QCOutcome,
    SalesOrderStatus,
)
from textileops.models.inventory import InventoryLot
from textileops.services import (
    coverage,
    inventory,
    procurement,
    production,
    quality,
    shipments,
)

D = Decimal
ZERO = D("0")
KG = UnitOfMeasure.KG
M = UnitOfMeasure.METRE


def _yarn_lot(session, yarn, quantity="3000", code="LOT-Y"):
    return inventory.create_lot(
        session,
        lot_code=code,
        material_id=yarn.id,
        quantity=D(quantity),
        unit=KG,
        received_at=moment(-5),
    )


# --- The identity ------------------------------------------------------------


def test_issued_material_is_not_subtracted_twice(session, fabric, yarn):
    """A batch that has drawn its material must not also still reserve it.

    Issuing consumes stock. If the reservation survives, coverage subtracts the
    same kilograms a second time — and because the requirement is then
    satisfied, the batch drops out of the demand set, so the leftover
    reservation is treated as somebody else's claim. The mill sees zero
    available yarn while 1,436 kg sits on the floor.
    """
    _yarn_lot(session, yarn, "3000")
    batch = make_batch(session, fabric, quantity=D("5000"))
    required = batch.requirements[0].required_quantity
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)

    production.issue_materials(session, batch)
    session.flush()

    position = inventory.material_position(session, yarn.id)
    remaining = D("3000") - required

    assert position.on_hand == remaining
    assert position.available >= ZERO, "available stock can never be negative"
    assert position.supply_for_coverage == remaining, (
        "every kilogram physically on the floor must be drawable"
    )
    assert active_reservations(session, yarn.id, KG) == ZERO, (
        "issuing fulfils the reservation; it must not linger"
    )
    assert_ledger_consistent(session)


def test_partially_issued_material_keeps_only_the_unissued_reservation(
    session, fabric, yarn
):
    """Half-issued means half-reserved, not fully reserved and not unreserved."""
    _yarn_lot(session, yarn, "800")
    batch = make_batch(session, fabric, quantity=D("5000"))
    required = batch.requirements[0].required_quantity
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)

    result = production.issue_materials(session, batch)
    session.flush()

    issued = result.issued[yarn.code]
    assert issued == D("800.000")
    assert inventory.material_position(session, yarn.id).on_hand == ZERO
    assert active_reservations(session, yarn.id, KG) == required - issued, (
        "the unissued balance is still a real claim on future stock"
    )


def test_the_accounting_identity_holds_across_a_whole_order_lifecycle(
    session, customer, fabric, yarn, supplier
):
    """Order → PO → receipt → production → QC → shipment, checked at every step."""
    opening = D("5000")
    _yarn_lot(session, yarn, str(opening))
    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=30)
    line = order.lines[0]

    po = make_purchase_order(session, supplier, yarn, quantity=D("2000"), expected_in=2)
    procurement.receive(
        session, po.lines[0], accepted_quantity=D("2000"), received_at=moment(-1)
    )
    session.flush()
    assert physical_total(session, material_id=yarn.id, unit=KG) == opening + D("2000")

    batch = make_batch(session, fabric, order, quantity=D("1000"), start_in=-6, days=4)
    required = batch.requirements[0].required_quantity
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    production.record_output(session, batch, good_quantity=D("1000"))
    session.flush()

    inspection = quality.record_inspection(
        session,
        code="QC-LIFE",
        outcome=QCOutcome.PASS,
        inspected_quantity=D("1000"),
        accepted_quantity=D("1000"),
        unit=M,
        production_batch_id=batch.id,
    )
    quality.propagate(session, inspection)
    production.complete_batch(session, batch)
    session.flush()

    # Yarn: opening + receipt − consumption.
    assert physical_total(session, material_id=yarn.id, unit=KG) == (
        opening + D("2000") - required
    )
    # Fabric: all of the output, none shipped yet.
    assert physical_total(session, fabric_spec_id=fabric.id, unit=M) == D("1000.000")

    shipment = shipments.create_shipment(
        session,
        number="SHP-LIFE",
        customer_id=customer.id,
        lines=[(line.id, D("600"), M)],
    )
    shipments.dispatch(session, shipment, idempotency_key="life-1")
    session.flush()

    assert physical_total(session, fabric_spec_id=fabric.id, unit=M) == D("400.000")
    assert line.shipped_quantity == D("600.000")
    assert line.outstanding_quantity == D("400.000")
    assert active_reservations(session, yarn.id, KG) == ZERO
    assert_ledger_consistent(session)


def test_cancelled_orders_release_their_material(session, customer, fabric, yarn):
    """A cancelled order must stop holding stock and stop creating demand.

    Otherwise its yarn is locked away for ever and its phantom requirement
    invents shortages for the orders that are still real.
    """
    _yarn_lot(session, yarn, "3000")
    order = make_sales_order(session, customer, fabric, quantity=D("5000"), promised_in=30)
    make_batch(session, fabric, order, quantity=D("5000"), start_in=2)
    session.flush()

    order.status = SalesOrderStatus.CANCELLED
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    assert result.required == ZERO, "a cancelled order is not demand"
    position = inventory.material_position(session, yarn.id)
    assert position.available == D("3000.000"), "its stock is free again"


def test_delivered_orders_stop_creating_demand(session, customer, fabric, yarn):
    """Same trap, reached through the normal happy path rather than a cancel."""
    _yarn_lot(session, yarn, "3000")
    order = make_sales_order(session, customer, fabric, quantity=D("5000"), promised_in=30)
    make_batch(session, fabric, order, quantity=D("5000"), start_in=2)
    session.flush()

    order.status = SalesOrderStatus.DELIVERED
    session.flush()

    assert coverage.analyse_material(session, yarn.id).required == ZERO


# --- Double counting ---------------------------------------------------------


def test_two_batches_cannot_both_be_promised_the_same_kilogram(
    session, customer, fabric, yarn
):
    _yarn_lot(session, yarn, "2000")
    first = make_sales_order(session, customer, fabric, number="SO-1", promised_in=10)
    second = make_sales_order(session, customer, fabric, number="SO-2", promised_in=20)
    make_batch(session, fabric, first, quantity=D("5000"), start_in=2)
    make_batch(session, fabric, second, quantity=D("5000"), start_in=6)
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    covered = sum((a.covered_quantity for a in result.allocations), ZERO)
    assert covered <= D("2000.000"), "supply was allocated more than once"
    assert result.shortage == result.required - covered


def test_quarantined_output_cannot_satisfy_demand(session, customer, fabric, yarn):
    """Rejected cloth is still in the building but must never look sellable."""
    _yarn_lot(session, yarn, "3000")
    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=20)
    batch = make_batch(session, fabric, order, quantity=D("1000"), start_in=-6, days=4)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    production.record_output(session, batch, good_quantity=D("1000"))
    session.flush()

    # Output starts quarantined, before QC has released it.
    available, _ = inventory.fabric_available(session, fabric.id)
    assert available == ZERO
    assert physical_total(session, fabric_spec_id=fabric.id, unit=M) == D("1000.000")

    inspection = quality.record_inspection(
        session,
        code="QC-REJ",
        outcome=QCOutcome.REJECT,
        inspected_quantity=D("1000"),
        rejected_quantity=D("1000"),
        unit=M,
        production_batch_id=batch.id,
    )
    quality.propagate(session, inspection, schedule_replacement=False)
    session.flush()

    available, _ = inventory.fabric_available(session, fabric.id)
    assert available == ZERO
    assert physical_total(session, fabric_spec_id=fabric.id, unit=M) == ZERO
    assert_ledger_consistent(session)


def test_scrap_never_drives_a_lot_negative(session, fabric, yarn):
    """A rejection larger than the lot must not create negative stock."""
    _yarn_lot(session, yarn, "3000")
    batch = make_batch(session, fabric, quantity=D("500"), start_in=-6, days=4)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    production.record_output(session, batch, good_quantity=D("500"))
    session.flush()

    inspection = quality.record_inspection(
        session,
        code="QC-OVER",
        outcome=QCOutcome.REJECT,
        inspected_quantity=D("500"),
        rejected_quantity=D("500"),
        unit=M,
        production_batch_id=batch.id,
    )
    quality.propagate(session, inspection, schedule_replacement=False)
    session.flush()

    for lot in session.scalars(
        select(InventoryLot).where(InventoryLot.fabric_spec_id == fabric.id)
    ).all():
        assert lot.quantity_on_hand >= ZERO
    assert_ledger_consistent(session)


def test_issuing_never_drives_a_lot_negative(session, fabric, yarn):
    _yarn_lot(session, yarn, "100")
    batch = make_batch(session, fabric, quantity=D("5000"))
    production.schedule_batch(session, batch)
    production.start_batch(session, batch)
    production.issue_materials(session, batch)
    session.flush()

    for lot in session.scalars(
        select(InventoryLot).where(InventoryLot.material_id == yarn.id)
    ).all():
        assert lot.quantity_on_hand >= ZERO
    assert_ledger_consistent(session)
