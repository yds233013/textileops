"""QC and its downstream consequences."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from tests.conftest import make_batch, make_sales_order, moment
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    MeasurementResult,
    ProductionStatus,
    QCMeasurementKind,
    QCOutcome,
)
from textileops.models.inventory import InventoryLot
from textileops.services import inventory, orders, production, quality
from textileops.services.quality import MeasurementInput

D = Decimal
ZERO = D("0")


def _produced_batch(session, fabric, yarn, order=None, quantity=D("5000")):
    inventory.create_lot(
        session,
        lot_code="LOT-YARN",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-3),
    )
    batch = make_batch(session, fabric, order, quantity=quantity, start_in=-6, days=5)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    production.record_output(session, batch, good_quantity=quantity)
    session.flush()
    return batch


def test_a_pass_releases_quarantined_output_to_available(session, fabric, yarn):
    batch = _produced_batch(session, fabric, yarn)
    inspection = quality.record_inspection(
        session,
        code="QC-1",
        outcome=QCOutcome.PASS,
        inspected_quantity=D("5000"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
    )
    result = quality.propagate(session, inspection)
    session.flush()
    assert result.lots_released
    lot = batch.fabric_spec  # sanity: spec exists
    assert lot is not None
    available, _ = inventory.fabric_available(session, batch.fabric_spec_id)
    assert available == D("5000.000")


def test_a_shade_rejection_quarantines_stock_and_schedules_a_replacement(
    session, fabric, yarn, customer
):
    """Scenario B, end to end: reject → quarantine → replacement → order risk."""
    order = make_sales_order(session, customer, fabric, quantity=D("5000"), promised_in=6)
    batch = _produced_batch(session, fabric, yarn, order)

    inspection = quality.record_inspection(
        session,
        code="QC-2",
        outcome=QCOutcome.REJECT,
        inspected_quantity=D("5000"),
        accepted_quantity=D("2000"),
        rejected_quantity=D("3000"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
        notes="Off-shade against the approved swatch.",
        measurements=[
            MeasurementInput(
                kind=QCMeasurementKind.SHADE,
                observed_text="Off-shade, greyer than the swatch",
                unit_text="visual",
            )
        ],
    )
    propagation = quality.propagate(session, inspection)
    session.flush()

    assert inspection.failed
    assert propagation.replacement_batch_code is not None
    assert propagation.lots_quarantined
    assert batch.status in (ProductionStatus.REJECTED, ProductionStatus.REWORK)
    # The rejected metres are scrapped out of stock, not quietly left sellable.
    available, _ = inventory.fabric_available(session, fabric.id)
    assert available == D("0.000")

    assessment = orders.assess_order(session, order)
    assert assessment.qc_status == "rejected"


def test_numeric_measurements_are_judged_against_tolerance(session, fabric, yarn):
    batch = _produced_batch(session, fabric, yarn)
    inspection = quality.record_inspection(
        session,
        code="QC-3",
        outcome=QCOutcome.CONDITIONAL_PASS,
        inspected_quantity=D("5000"),
        accepted_quantity=D("5000"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
        measurements=[
            MeasurementInput(
                kind=QCMeasurementKind.GSM,
                observed_value=D("172"),
                target_value=D("180"),
                tolerance_low=D("171"),
                tolerance_high=D("189"),
                unit_text="gsm",
            ),
            MeasurementInput(
                kind=QCMeasurementKind.WIDTH_CM,
                observed_value=D("160"),
                target_value=D("165"),
                tolerance_low=D("163"),
                tolerance_high=D("167"),
                unit_text="cm",
            ),
        ],
    )
    session.flush()
    results = {m.kind: m.result for m in inspection.measurements}
    assert results[QCMeasurementKind.GSM] == MeasurementResult.WITHIN_TOLERANCE
    assert results[QCMeasurementKind.WIDTH_CM] == MeasurementResult.OUT_OF_TOLERANCE


def test_a_judgement_measurement_without_tolerance_is_not_assessed(session, fabric, yarn):
    """Shade is judged by eye; the system must not pretend it measured it."""
    batch = _produced_batch(session, fabric, yarn)
    inspection = quality.record_inspection(
        session,
        code="QC-4",
        outcome=QCOutcome.PASS,
        inspected_quantity=D("100"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
        measurements=[
            MeasurementInput(
                kind=QCMeasurementKind.SHADE, observed_text="Matches swatch", unit_text="visual"
            )
        ],
    )
    session.flush()
    assert inspection.measurements[0].result == MeasurementResult.NOT_ASSESSED


def test_tolerances_come_from_the_fabric_spec(fabric):
    tolerances = quality.tolerances_for_spec(fabric)
    target, low, high = tolerances[QCMeasurementKind.GSM]
    assert (target, low, high) == (D("180"), D("171.000"), D("189.000"))


def test_a_measurement_needs_an_observation_not_just_a_tolerance(
    session, fabric, yarn
):
    """Tolerances describe what to check; they are not results.

    Building inspection rows from limits alone produced an inspection that
    claimed to have measured something it never did — the database refuses it,
    and so should the code that constructs them.
    """
    batch = _produced_batch(session, fabric, yarn, quantity=D("100"))
    measurements = quality.measurements_for_spec(
        fabric, observed_gsm=D("178"), observed_width_cm=D("165")
    )
    assert all(m.observed_value is not None for m in measurements)

    inspection = quality.record_inspection(
        session,
        code="QC-OBS",
        outcome=QCOutcome.PASS,
        inspected_quantity=D("100"),
        accepted_quantity=D("100"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
        measurements=measurements,
    )
    session.flush()
    results = {m.kind: m.result for m in inspection.measurements}
    assert results[QCMeasurementKind.GSM] == MeasurementResult.WITHIN_TOLERANCE


def test_a_rejected_batch_gives_its_materials_back(session, fabric, yarn, customer):
    """A dead batch must not hold stock hostage: leaving its reservations in
    place makes every later coverage figure wrong by that amount."""
    from textileops.services import coverage
    from textileops.services import inventory as inventory_service

    order = make_sales_order(session, customer, fabric, quantity=D("1000"), promised_in=20)
    batch = _produced_batch(session, fabric, yarn, order, quantity=D("1000"))
    session.flush()

    reserved_before = inventory_service.material_position(session, yarn.id).reserved
    assert reserved_before > ZERO

    inspection = quality.record_inspection(
        session,
        code="QC-REL",
        outcome=QCOutcome.REJECT,
        inspected_quantity=D("1000"),
        rejected_quantity=D("1000"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
    )
    quality.propagate(session, inspection, schedule_replacement=False)
    session.flush()

    position = inventory_service.material_position(session, yarn.id)
    assert position.reserved == D("0.000")
    # And the coverage supply pool is a real, non-negative quantity again.
    result = coverage.analyse_material(session, yarn.id)
    assert result.available >= D("0")


def test_a_rejection_is_scrapped_once_not_once_per_lot(session, fabric, yarn):
    """The rejected quantity belongs to the inspection, not to each lot.

    Scrapping it per lot destroyed 600 m on the books for a 300 m rejection.
    """
    inventory.create_lot(
        session,
        lot_code="LOT-YARN",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-3),
    )
    batch = make_batch(session, fabric, quantity=D("1000"), start_in=-6, days=4)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    # Two output lots of 500 m each.
    production.record_output(session, batch, good_quantity=D("500"), lot_code="LOT-A")
    production.record_output(session, batch, good_quantity=D("500"), lot_code="LOT-B")
    session.flush()

    inspection = quality.record_inspection(
        session,
        code="QC-SPLIT",
        outcome=QCOutcome.REJECT,
        inspected_quantity=D("1000"),
        accepted_quantity=D("700"),
        rejected_quantity=D("300"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
    )
    quality.propagate(session, inspection, schedule_replacement=False)
    session.flush()

    lots = session.scalars(
        select(InventoryLot).where(InventoryLot.production_batch_id == batch.id)
    ).all()
    total = sum(lot.quantity_on_hand for lot in lots)
    # 1,000 produced − 300 rejected = 700 left, not 400.
    assert total == D("700.000")
    assert inventory.ledger_discrepancies(session) == []


def test_a_qc_outcome_a_batch_cannot_act_on_is_recorded(session, fabric, yarn):
    """A reject against a batch that never ran must not pass silently."""
    inventory.create_lot(
        session,
        lot_code="LOT-YARN",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-3),
    )
    batch = make_batch(session, fabric, quantity=D("1000"))
    session.flush()
    assert batch.status == ProductionStatus.PLANNED

    inspection = quality.record_inspection(
        session,
        code="QC-ODD",
        outcome=QCOutcome.REJECT,
        inspected_quantity=D("100"),
        rejected_quantity=D("100"),
        unit=UnitOfMeasure.METRE,
        production_batch_id=batch.id,
    )
    quality.propagate(session, inspection, schedule_replacement=False)
    session.flush()

    notes = " ".join(event.note or "" for event in batch.events)
    assert "cannot move" in notes
    assert "Needs an operator" in notes


def test_completing_a_batch_twice_does_not_double_the_produced_quantity(
    session, customer, fabric, yarn
):
    """complete → QC rework → complete again is a legal path."""
    inventory.create_lot(
        session,
        lot_code="LOT-YARN",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-3),
    )
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    batch = make_batch(session, fabric, order, quantity=D("1000"), start_in=-6, days=4)
    production.schedule_batch(session, batch)
    production.start_batch(session, batch, at=moment(-6))
    production.record_output(session, batch, good_quantity=D("1000"))
    production.complete_batch(session, batch)
    session.flush()
    assert order.lines[0].produced_quantity == D("1000.000")

    batch.status = ProductionStatus.REWORK
    session.flush()
    production.complete_batch(session, batch)
    session.flush()
    assert order.lines[0].produced_quantity == D("1000.000")
