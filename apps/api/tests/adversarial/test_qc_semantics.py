"""What a QC verdict actually does to the cloth.

An inspection records two numbers — how much was accepted and how much was
rejected — because that is what an inspection is: "of the 1,000 metres, 700
are good and 300 are off-shade". The consequences have to follow those
numbers. They used to follow the outcome *label* instead, and the two
directions of that mistake are the first two tests here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.conftest import make_batch, make_sales_order
from textileops.core.errors import ConflictError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import LotStatus, MovementType, QCOutcome
from textileops.models.inventory import InventoryLot, InventoryMovement
from textileops.services import inventory, orders, production, quality

D = Decimal
ZERO = D("0.000")


@pytest.fixture
def produced(session, fabric, yarn, customer):
    """A batch that has made 1,000 m, sitting in quarantine awaiting QC."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-{uuid.uuid4().hex[:8].upper()}",
        unit=UnitOfMeasure.KG,
        quantity=D("5000.000"),
        material_id=yarn.id,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()
    production.start_batch(session, batch)
    production.issue_materials(session, batch)
    production.record_output(
        session, batch, good_quantity=D("1000"), unit=UnitOfMeasure.METRE
    )
    session.flush()
    return order, batch


def _inspect(session, batch, outcome, accepted, rejected, **kwargs):
    inspection = quality.record_inspection(
        session,
        code=f"QC-{uuid.uuid4().hex[:8].upper()}",
        outcome=outcome,
        inspected_quantity=D("1000"),
        accepted_quantity=D(accepted),
        rejected_quantity=D(rejected),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
        **kwargs,
    )
    quality.propagate(session, inspection)
    session.flush()
    return inspection


def test_a_pass_with_a_partial_rejection_does_not_release_the_rejected_cloth(
    session, produced, fabric
):
    """"Accept with a deduction, 300 m set aside" is ordinary mill practice.

    The pass branch flipped *every* lot of the batch to AVAILABLE and the
    scrap was gated on the outcome being REJECT, so the rejected metres went
    straight into the sellable pool and dispatch would load them.
    """
    _order, batch = produced
    _inspect(session, batch, QCOutcome.CONDITIONAL_PASS, "700", "300")

    available, unit = inventory.fabric_available(session, fabric.id)
    assert available == D("700.000"), (
        f"rejected cloth is sellable: {available} {unit.value} available"
    )
    scrapped = session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
            InventoryMovement.movement_type == MovementType.SCRAP
        )
    )
    assert scrapped == D("-300.000")


def test_a_rejection_with_a_partial_acceptance_does_not_strand_the_good_cloth(
    session, produced, fabric
):
    """The same mistake read from the other end.

    Every lot was quarantined on REJECT regardless of what the inspector
    accepted, so 700 m QC had explicitly passed became invisible to
    allocation and to dispatch — the order short, nothing planned to make up
    the difference, and only a manual re-inspection able to recover it.
    """
    _order, batch = produced
    _inspect(session, batch, QCOutcome.REJECT, "700", "300")

    available, _ = inventory.fabric_available(session, fabric.id)
    assert available == D("700.000"), (
        "cloth the inspector accepted is stranded in quarantine"
    )


def test_rework_keeps_the_cloth_and_scraps_nothing(session, produced, fabric):
    """Rework means recoverable. Scrapping it destroys what the mill intends
    to put back through the dyehouse."""
    _order, batch = produced
    _inspect(session, batch, QCOutcome.REWORK, "0", "1000")

    available, _ = inventory.fabric_available(session, fabric.id)
    assert available == ZERO, "cloth awaiting rework is not sellable"
    lots = session.scalars(
        select(InventoryLot).where(InventoryLot.production_batch_id == batch.id)
    ).all()
    assert sum((lot.quantity_on_hand for lot in lots), ZERO) == D("1000.000"), (
        "rework scrapped cloth that was meant to be re-dyed"
    )
    assert all(lot.status == LotStatus.QUARANTINE for lot in lots)


def test_a_full_pass_releases_everything(session, produced, fabric):
    """The ordinary case must still work."""
    _order, batch = produced
    _inspect(session, batch, QCOutcome.PASS, "1000", "0")
    available, _ = inventory.fabric_available(session, fabric.id)
    assert available == D("1000.000")


# --- Duplicate submissions ----------------------------------------------------


def test_a_second_inspection_of_one_batch_is_refused(session, produced):
    """A double-submitted form destroyed cloth twice.

    `_scrap_rejected` keys its idempotency on the *inspection*, so a second
    inspection saying the same thing scraps the same metres again: two
    submissions of "1,000 inspected, 300 rejected" take 600 m off the books
    for a 300 m rejection. A SCRAP movement has no correction path.
    """
    _order, batch = produced
    _inspect(session, batch, QCOutcome.REJECT, "700", "300")

    with pytest.raises(ConflictError) as exc:
        _inspect(session, batch, QCOutcome.REJECT, "700", "300")
    assert "already has inspection" in str(exc.value)

    lots = session.scalars(
        select(InventoryLot).where(InventoryLot.production_batch_id == batch.id)
    ).all()
    assert sum((lot.quantity_on_hand for lot in lots), ZERO) == D("700.000"), (
        "the duplicate submission scrapped the rejected quantity twice"
    )


def test_a_genuine_reinspection_is_allowed(session, produced):
    """The guard must not block the legitimate second look."""
    _order, batch = produced
    first = _inspect(session, batch, QCOutcome.REWORK, "0", "1000")

    second = _inspect(
        session, batch, QCOutcome.PASS, "1000", "0", reinspection_of_id=first.id
    )
    assert second.reinspection_of_id == first.id


def test_only_one_replacement_batch_is_raised_for_one_rejection(session, produced):
    """A second inspection also raised a second replacement batch, which took
    its own material reservations for yarn nobody needed."""
    from textileops.models.production import ProductionBatch

    _order, batch = produced
    _inspect(session, batch, QCOutcome.REJECT, "0", "1000")

    replacements = session.scalars(
        select(ProductionBatch).where(ProductionBatch.rework_of_batch_id == batch.id)
    ).all()
    assert len(replacements) == 1


# --- The badge ----------------------------------------------------------------


def test_a_passing_reinspection_clears_the_failure(session, produced):
    """The order screen and the exception list used to contradict each other.

    `_qc_status` reduced over every inspection ever attached to the batch, and
    REJECT wins any such reduction — so a batch that failed, was reworked and
    then passed carried its failure for the rest of its life, while the
    exception engine, which does follow the re-inspection chain, had already
    closed the exception.
    """
    order, batch = produced
    first = _inspect(session, batch, QCOutcome.REWORK, "0", "1000")
    assert orders.assess_order(session, order).qc_status == "rework"

    _inspect(session, batch, QCOutcome.PASS, "1000", "0", reinspection_of_id=first.id)

    assert orders.assess_order(session, order).qc_status == "passed", (
        "a batch that passed on re-inspection still carries its old failure"
    )


def test_uninspected_batches_outrank_a_conditional_pass(session, fabric, yarn, customer):
    """One batch passed with a note and two never looked at is not
    "conditionally passed" — the looking is not finished."""
    inventory.create_lot(
        session,
        lot_code=f"LOT-{uuid.uuid4().hex[:8].upper()}",
        unit=UnitOfMeasure.KG,
        quantity=D("9000.000"),
        material_id=yarn.id,
    )
    order = make_sales_order(session, customer, fabric, quantity=D("3000"))
    session.flush()
    first = make_batch(session, fabric, order, quantity=D("1000"))
    make_batch(session, fabric, order, quantity=D("1000"))
    make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()
    production.start_batch(session, first)
    production.issue_materials(session, first)
    production.record_output(
        session, first, good_quantity=D("1000"), unit=UnitOfMeasure.METRE
    )
    session.flush()
    _inspect(session, first, QCOutcome.CONDITIONAL_PASS, "1000", "0")

    assert orders.assess_order(session, order).qc_status == "partially_inspected"


def test_a_passing_reinspection_cancels_the_replacement_it_no_longer_needs(
    session, produced, yarn
):
    """Otherwise the mill keeps yarn reserved for cloth nobody will make.

    The failure raises a replacement batch. When the rework then passes, that
    replacement is redundant — but nothing closed it, so it went on holding
    material reservations, and every shortage and purchase recommendation
    computed from them was inflated by cloth that was never going to be made.
    """
    from textileops.models.enums import ProductionStatus, ReservationStatus
    from textileops.models.inventory import InventoryReservation
    from textileops.models.production import ProductionBatch

    _order, batch = produced
    first = _inspect(session, batch, QCOutcome.REWORK, "0", "1000")
    session.flush()

    replacement = session.scalars(
        select(ProductionBatch).where(ProductionBatch.rework_of_batch_id == batch.id)
    ).first()
    assert replacement is not None, "precondition: a replacement was raised"
    held_before = session.scalar(
        select(func.count(InventoryReservation.id)).where(
            InventoryReservation.production_batch_id == replacement.id,
            InventoryReservation.status == ReservationStatus.ACTIVE,
        )
    )

    _inspect(session, batch, QCOutcome.PASS, "1000", "0", reinspection_of_id=first.id)
    session.refresh(replacement)

    assert replacement.status == ProductionStatus.CANCELLED
    held_after = session.scalar(
        select(func.count(InventoryReservation.id)).where(
            InventoryReservation.production_batch_id == replacement.id,
            InventoryReservation.status == ReservationStatus.ACTIVE,
        )
    )
    assert held_after == 0, (
        f"the cancelled replacement still holds {held_after} reservation(s) "
        f"(was {held_before})"
    )
