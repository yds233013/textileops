"""Quality control and its downstream consequences.

A QC result is not a filing exercise: a rejected batch changes what stock is
usable, what production must be redone, and whether a customer order is still
achievable. This module makes that propagation explicit and deterministic.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.errors import ConflictError, ValidationError
from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.enums import (
    EntityType,
    LotStatus,
    MeasurementResult,
    MovementType,
    ProductionEventType,
    ProductionStatus,
    QCMeasurementKind,
    QCOutcome,
)
from textileops.models.inventory import InventoryLot
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection, QCMeasurement
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock, inventory, production
from textileops.services.audit import record_audit

ZERO = Decimal("0")

#: Outcomes that stop material being sold or shipped.
BLOCKING_OUTCOMES = (QCOutcome.REJECT, QCOutcome.REWORK)


@dataclass
class MeasurementInput:
    kind: QCMeasurementKind
    observed_value: Decimal | None = None
    observed_text: str | None = None
    target_value: Decimal | None = None
    tolerance_low: Decimal | None = None
    tolerance_high: Decimal | None = None
    unit_text: str | None = None
    label: str | None = None
    note: str | None = None

    def evaluate(self) -> MeasurementResult:
        """Numeric tolerance check. Judgement calls (shade) stay NOT_ASSESSED
        unless the inspector supplied a numeric result."""
        if self.observed_value is None:
            return MeasurementResult.NOT_ASSESSED
        low = self.tolerance_low
        high = self.tolerance_high
        if low is None and high is None:
            return MeasurementResult.NOT_ASSESSED
        if low is not None and self.observed_value < low:
            return MeasurementResult.OUT_OF_TOLERANCE
        if high is not None and self.observed_value > high:
            return MeasurementResult.OUT_OF_TOLERANCE
        return MeasurementResult.WITHIN_TOLERANCE


@dataclass
class QCPropagation:
    """What a QC result did to the rest of the business."""

    inspection_id: uuid.UUID
    lots_quarantined: list[str]
    lots_released: list[str]
    batch_status: str | None
    replacement_batch_code: str | None
    affected_sales_order_numbers: list[str]



#: How a QC verdict reads in a sentence.
_OUTCOME_WORD = {
    "pass": "passed",
    "reject": "rejected",
    "rework": "sent for rework",
    "conditional_pass": "conditional pass",
    "pending": "awaiting a verdict",
}

def record_inspection(
    session: Session,
    *,
    code: str,
    outcome: QCOutcome,
    inspected_quantity: Decimal,
    unit: UnitOfMeasure,
    accepted_quantity: Decimal | None = None,
    rejected_quantity: Decimal | None = None,
    production_batch_id: uuid.UUID | None = None,
    inventory_lot_id: uuid.UUID | None = None,
    measurements: list[MeasurementInput] | None = None,
    inspected_at: dt.datetime | None = None,
    inspector_user_id: uuid.UUID | None = None,
    notes: str | None = None,
    reinspection_of_id: uuid.UUID | None = None,
    source_document_id: uuid.UUID | None = None,
) -> QCInspection:
    if production_batch_id is None and inventory_lot_id is None:
        raise ValidationError("An inspection must target a production batch or an inventory lot.")

    inspected_quantity = quantize(inspected_quantity)
    if rejected_quantity is None and accepted_quantity is None:
        rejected = inspected_quantity if outcome in BLOCKING_OUTCOMES else ZERO
        accepted = ZERO if outcome in BLOCKING_OUTCOMES else inspected_quantity
    else:
        accepted = quantize(accepted_quantity or ZERO)
        rejected = quantize(rejected_quantity or ZERO)
    if accepted + rejected > inspected_quantity:
        raise ValidationError(
            "Accepted plus rejected quantity cannot exceed the inspected quantity."
        )

    # A batch has one current inspection. A second one is either an explicit
    # re-inspection — which says so — or a mistake, and the commonest mistake
    # is a double-submitted form.
    #
    # That is not a harmless duplicate. `_scrap_rejected` keys its idempotency
    # on the *inspection*, so a second inspection saying the same thing scraps
    # the same cloth again: two submissions of "1,000 inspected, 300 rejected"
    # destroy 600 m on the books for a 300 m rejection, and a SCRAP movement
    # has no correction path. It also raises a second replacement batch, which
    # takes its own material reservations for yarn nobody needs.
    if production_batch_id is not None and reinspection_of_id is None:
        existing = session.scalars(
            select(QCInspection).where(
                QCInspection.production_batch_id == production_batch_id
            )
        ).all()
        superseded = {
            i.reinspection_of_id for i in existing if i.reinspection_of_id is not None
        }
        current = [i for i in existing if i.id not in superseded]
        if current:
            raise ConflictError(
                f"Batch already has inspection {current[-1].code} recorded against "
                "it. If this is a fresh look after rework, record it as a "
                "re-inspection of that one; if it is a repeat of the same "
                "submission, it has already been saved.",
                details={
                    "existing_inspection": current[-1].code,
                    "existing_outcome": current[-1].outcome.value,
                },
            )

    inspection = QCInspection(
        code=code,
        production_batch_id=production_batch_id,
        inventory_lot_id=inventory_lot_id,
        inspected_at=inspected_at or clock.now(),
        outcome=outcome,
        inspected_quantity=inspected_quantity,
        accepted_quantity=accepted,
        rejected_quantity=rejected,
        unit=unit,
        inspector_user_id=inspector_user_id,
        reinspection_of_id=reinspection_of_id,
        source_document_id=source_document_id,
        notes=notes,
    )
    session.add(inspection)
    session.flush()

    for measurement in measurements or []:
        session.add(
            QCMeasurement(
                qc_inspection_id=inspection.id,
                kind=measurement.kind,
                label=measurement.label,
                observed_value=measurement.observed_value,
                observed_text=measurement.observed_text,
                target_value=measurement.target_value,
                tolerance_low=measurement.tolerance_low,
                tolerance_high=measurement.tolerance_high,
                unit_text=measurement.unit_text,
                result=measurement.evaluate(),
                note=measurement.note,
            )
        )

    record_audit(
        session,
        action="qc.recorded",
        entity_type=EntityType.QC_INSPECTION,
        entity_id=inspection.id,
        summary=(
            f"QC {code} on the {'batch' if production_batch_id else 'lot'}: "
            f"{_OUTCOME_WORD.get(outcome.value, outcome.value)}."
        ),
        actor_type="user" if inspector_user_id else "system",
        actor_user_id=inspector_user_id,
        after={"outcome": outcome.value, "accepted": accepted, "rejected": rejected},
    )
    session.flush()
    return inspection


def propagate(
    session: Session,
    inspection: QCInspection,
    *,
    schedule_replacement: bool = True,
    user_id: uuid.UUID | None = None,
) -> QCPropagation:
    """Apply the consequences of an inspection result.

    * Pass / conditional pass → release quarantined output to AVAILABLE.
    * Rework / reject → keep stock out of the available pool, mark the batch,
      and (optionally) schedule a replacement batch so the order's estimated
      completion moves honestly rather than silently slipping.
    """
    quarantined: list[str] = []
    released: list[str] = []
    cancelled_replacements: list[str] = []
    replacement_code: str | None = None
    batch: ProductionBatch | None = None
    if inspection.production_batch_id:
        batch = session.get(ProductionBatch, inspection.production_batch_id)

    lots = _target_lots(session, inspection)

    # The consequences follow the *quantities*, not the headline outcome.
    #
    # `record_inspection` stores an accepted and a rejected figure because a
    # real inspection is "of the 1,000 m, 700 is good and 300 is off-shade".
    # This used to branch on the outcome enum alone and ignore both:
    #
    #  * a conditional pass with 300 m rejected released all 1,000 m into the
    #    sellable pool, and dispatch would load the rejected cloth onto the
    #    lorry;
    #  * a reject with 700 m accepted quarantined the lot entire, so cloth QC
    #    had explicitly passed became invisible to allocation and to dispatch,
    #    the order was short with nothing planned to make up the difference,
    #    and only a manual re-inspection could recover it.
    #
    # Both are the same mistake read from opposite ends.
    if inspection.outcome in BLOCKING_OUTCOMES:
        for lot in lots:
            if lot.status in (LotStatus.AVAILABLE, LotStatus.QUARANTINE):
                lot.status = LotStatus.QUARANTINE
                quarantined.append(lot.lot_code)

    # Bad cloth leaves the building whatever the label says — except on
    # REWORK, where the cloth is expected to be recoverable and scrapping it
    # would destroy something the mill intends to put back through the dyehouse.
    if inspection.rejected_quantity > ZERO and inspection.outcome != QCOutcome.REWORK:
        # Once for the inspection, spread across its lots — not once per
        # lot, which would destroy the rejected quantity several times over.
        _scrap_rejected(session, lots, inspection)

    # Good cloth is released whatever the label says. After the scrap above,
    # what remains in these lots is what the inspector accepted, so releasing
    # the lot releases exactly that.
    if (
        inspection.outcome in (QCOutcome.PASS, QCOutcome.CONDITIONAL_PASS)
        or inspection.accepted_quantity > ZERO
    ) and inspection.outcome != QCOutcome.REWORK:
        for lot in lots:
            if lot.status == LotStatus.QUARANTINE and lot.quantity_on_hand > ZERO:
                lot.status = LotStatus.AVAILABLE
                released.append(lot.lot_code)
                if lot.lot_code in quarantined:
                    quarantined.remove(lot.lot_code)

    # A passing re-inspection ends the rework. Nothing made this transition
    # before, so a batch that failed, was reworked and then passed stayed in
    # REWORK for ever — an open status, so the order it belongs to went on
    # reporting itself as still being inspected while its QC verdict said
    # otherwise. REWORK -> COMPLETED was already legal; it was simply never
    # taken.
    if (
        batch is not None
        and inspection.reinspection_of_id is not None
        and inspection.outcome in (QCOutcome.PASS, QCOutcome.CONDITIONAL_PASS)
        and ProductionStatus.COMPLETED in production.TRANSITIONS.get(batch.status, set())
    ):
        batch.status = ProductionStatus.COMPLETED
        record_audit(
            session,
            action="production.qc_outcome_applied",
            entity_type=EntityType.PRODUCTION_BATCH,
            entity_id=batch.id,
            summary=(
                f"Batch {batch.code} passed re-inspection {inspection.code}; "
                "rework complete."
            ),
            actor_type="user" if user_id else "system",
            actor_user_id=user_id,
        )
        # The replacement the failure raised is no longer needed. Left
        # standing it would hold material reservations for cloth nobody is
        # going to make, which inflates every shortage and purchase
        # recommendation computed from them — and nothing else would ever
        # close it, because a batch cannot be cancelled from anywhere else.
        for replacement in session.scalars(
            select(ProductionBatch).where(
                ProductionBatch.rework_of_batch_id == batch.id,
                ProductionBatch.status.in_(production.OPEN_STATUSES),
            )
        ).all():
            replacement.status = ProductionStatus.CANCELLED
            freed = production.release_materials_if_terminal(session, replacement)
            cancelled_replacements.append(replacement.code)
            record_audit(
                session,
                action="production.replacement_cancelled",
                entity_type=EntityType.PRODUCTION_BATCH,
                entity_id=replacement.id,
                summary=(
                    f"Replacement batch {replacement.code} cancelled: "
                    f"{batch.code} passed re-inspection {inspection.code}. "
                    f"{freed} material reservation(s) released."
                ),
                actor_type="user" if user_id else "system",
                actor_user_id=user_id,
            )

    if inspection.outcome in BLOCKING_OUTCOMES and batch is not None:
        target = (
            ProductionStatus.REWORK
            if inspection.outcome == QCOutcome.REWORK
            else ProductionStatus.REJECTED
        )
        if target in production.TRANSITIONS.get(batch.status, set()):
            batch.status = target
            record_audit(
                session,
                action="production.qc_outcome_applied",
                entity_type=EntityType.PRODUCTION_BATCH,
                entity_id=batch.id,
                summary=(
                    f"Batch {batch.code} moved to {target.value} following QC "
                    f"{inspection.code}."
                ),
                actor_type="user" if user_id else "system",
                actor_user_id=user_id,
            )
        else:
            # The batch is in a state this outcome cannot act on (a reject
            # against a batch that never ran, say). Saying nothing would
            # leave its reservations locked for ever and report the old
            # status as though it were the result.
            production.add_event(
                session,
                batch,
                ProductionEventType.NOTE,
                note=(
                    f"QC {inspection.code} returned {inspection.outcome.value}, but "
                    f"batch {batch.code} is {batch.status.value} and cannot move to "
                    f"{target.value}. Needs an operator."
                ),
                user_id=user_id,
            )
        # A rejected batch will never consume the materials it reserved.
        production.release_materials_if_terminal(session, batch)
        production.add_event(
            session,
            batch,
            ProductionEventType.REJECTED
            if inspection.outcome == QCOutcome.REJECT
            else ProductionEventType.REWORK_STARTED,
            note=f"QC {inspection.code}: {inspection.outcome.value}.",
            user_id=user_id,
        )
        if schedule_replacement and inspection.rejected_quantity > ZERO:
            replacement = production.create_rework_batch(
                session,
                batch,
                quantity=convert(inspection.rejected_quantity, inspection.unit, batch.unit),
                code=_next_rework_code(session, batch.code),
                user_id=user_id,
            )
            replacement_code = replacement.code

    # A rejection moves the batch out of COMPLETED, which changes what the
    # order line has actually been given. Nothing recomputed it: the only
    # caller of `_propagate_produced_quantity` was `complete_batch`, so the
    # line went on claiming cloth that had since been scrapped, and only
    # self-corrected if some *other* batch on the line later completed.
    if batch is not None and batch.sales_order_line_id:
        production.propagate_produced_quantity(session, batch)

    affected = _affected_order_numbers(session, batch)
    session.flush()
    return QCPropagation(
        inspection_id=inspection.id,
        lots_quarantined=quarantined,
        lots_released=released,
        batch_status=batch.status.value if batch else None,
        replacement_batch_code=replacement_code,
        affected_sales_order_numbers=affected,
    )


def _target_lots(session: Session, inspection: QCInspection) -> list[InventoryLot]:
    if inspection.inventory_lot_id:
        lot = session.get(InventoryLot, inspection.inventory_lot_id)
        return [lot] if lot else []
    if inspection.production_batch_id:
        return list(
            session.scalars(
                select(InventoryLot)
                .where(
                    InventoryLot.production_batch_id == inspection.production_batch_id
                )
                # Ordered for the same reason dispatch orders its lots: each of
                # these becomes a locked row in `_scrap_rejected`. Without an
                # ORDER BY the scan order is not even stable between runs on
                # identical data, so QC and dispatch could take the same lot
                # locks in opposite orders and deadlock.
                .order_by(InventoryLot.received_at, InventoryLot.id)
            ).all()
        )
    return []


def _scrap_rejected(
    session: Session, lots: list[InventoryLot], inspection: QCInspection
) -> None:
    """Write the rejected quantity off across the inspected lots, exactly once.

    The rejected figure belongs to the *inspection*, not to each lot it
    touched: scrapping it once per lot would destroy 600 metres on the books
    for a 300-metre rejection. Accounting is done in the inspection's own unit
    and converted per lot, so a batch inspected in yards can be written off
    against lots held in metres.
    """
    remaining = quantize(inspection.rejected_quantity)
    for lot in lots:
        if remaining <= ZERO:
            break
        available = convert(lot.quantity_on_hand, lot.unit, inspection.unit)
        take = min(available, remaining)
        if take <= ZERO:
            continue
        inventory.post_movement(
            session,
            lot=lot,
            movement_type=MovementType.SCRAP,
            quantity=convert(take, inspection.unit, lot.unit),
            occurred_at=inspection.inspected_at,
            reference_type=EntityType.QC_INSPECTION,
            reference_id=inspection.id,
            idempotency_key=f"qc-scrap:{inspection.id}:{lot.id}",
            note=f"Scrapped following QC {inspection.code}.",
        )
        remaining = quantize(remaining - take)
        if lot.quantity_on_hand <= ZERO:
            lot.status = LotStatus.REJECTED


def _affected_order_numbers(session: Session, batch: ProductionBatch | None) -> list[str]:
    if batch is None or not batch.sales_order_line_id:
        return []
    row = session.execute(
        select(SalesOrder.number)
        .join(SalesOrderLine, SalesOrderLine.sales_order_id == SalesOrder.id)
        .where(SalesOrderLine.id == batch.sales_order_line_id)
    ).first()
    return [row[0]] if row else []


def _next_rework_code(session: Session, base_code: str) -> str:
    stem = base_code.split("-R")[0]
    existing = session.scalars(
        select(ProductionBatch.code).where(ProductionBatch.code.like(f"{stem}-R%"))
    ).all()
    return f"{stem}-R{len(existing) + 1}"


def tolerances_for_spec(spec) -> dict[QCMeasurementKind, tuple[Decimal, Decimal, Decimal]]:
    """The checks this mill performs on a fabric, and their limits.

    Returns ``kind -> (target, low, high)``. ±5% on GSM and ±2 cm on width are
    this business's conventions.

    These are *limits*, not results. A measurement with no observation is not a
    measurement — building inspection rows from these alone would record a
    check that never happened, and the database refuses it.
    """
    gsm = Decimal(str(spec.gsm))
    width = Decimal(str(spec.width_cm))
    return {
        QCMeasurementKind.GSM: (
            gsm,
            quantize(gsm * Decimal("0.95")),
            quantize(gsm * Decimal("1.05")),
        ),
        QCMeasurementKind.WIDTH_CM: (
            width,
            quantize(width - Decimal("2")),
            quantize(width + Decimal("2")),
        ),
    }


def measurements_for_spec(
    spec,
    *,
    observed_gsm: Decimal,
    observed_width_cm: Decimal,
) -> list[MeasurementInput]:
    """Build the standard fabric checks from what was actually observed."""
    tolerances = tolerances_for_spec(spec)
    gsm_target, gsm_low, gsm_high = tolerances[QCMeasurementKind.GSM]
    width_target, width_low, width_high = tolerances[QCMeasurementKind.WIDTH_CM]
    return [
        MeasurementInput(
            kind=QCMeasurementKind.GSM,
            observed_value=quantize(observed_gsm),
            target_value=gsm_target,
            tolerance_low=gsm_low,
            tolerance_high=gsm_high,
            unit_text="gsm",
        ),
        MeasurementInput(
            kind=QCMeasurementKind.WIDTH_CM,
            observed_value=quantize(observed_width_cm),
            target_value=width_target,
            tolerance_low=width_low,
            tolerance_high=width_high,
            unit_text="cm",
        ),
    ]
