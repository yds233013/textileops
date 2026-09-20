"""Development-only operational event simulation.

This exists so the product can be seen *working* rather than described: fire a
realistic event, watch the exception engine re-derive risk, and see the
attention queue change.

It is deliberately not a shortcut around the real code paths. A simulated
supplier delay is a real inbound message that goes through the real ingestion
pipeline: extraction, validation, entity resolution, then the deterministic ETA
revision. What you see in the demo is the mechanism you get in production.

Refuses to run when ``ENVIRONMENT=production`` or ``ENABLE_SIMULATION=false``.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.errors import ConflictError, NotFoundError, ValidationError
from textileops.core.units import quantize
from textileops.ingestion import pipeline
from textileops.models.enums import (
    OPEN_PO_STATUSES,
    BusinessEventType,
    ProductionStatus,
    QCMeasurementKind,
    QCOutcome,
    ShipmentStatus,
    SourceChannel,
)
from textileops.models.logistics import Shipment
from textileops.models.procurement import PurchaseOrder, PurchaseOrderLine
from textileops.models.production import ProductionBatch
from textileops.services import (
    clock,
    exception_engine,
    procurement,
    production,
    quality,
    shipments,
)
from textileops.services.audit import record_metric
from textileops.services.quality import MeasurementInput

ZERO = Decimal("0")


@dataclass
class SimulationResult:
    event: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    engine: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "summary": self.summary,
            "details": self.details,
            "engine": self.engine,
        }


def _guard() -> None:
    if settings.is_production or not settings.enable_simulation:
        raise ConflictError(
            "Simulation is disabled. It is a development feature and never runs in "
            "production."
        )


def _finish(result: SimulationResult, session: Session) -> SimulationResult:
    production.refresh_all_estimates(session)
    engine_result = exception_engine.run(session)
    result.engine = engine_result.summary()
    record_metric(
        session,
        event_type=BusinessEventType.SIMULATION_EVENT,
        payload={"event": result.event, **result.engine},
    )
    session.flush()
    return result


AVAILABLE_EVENTS = (
    "supplier_delay",
    "inventory_receipt",
    "qc_rejection",
    "production_completion",
    "shipment_dispatch",
)

_DELAY_REASONS = (
    "Truck breakdown near Salem; the vehicle is being replaced.",
    "Dyeing unit power cut for two shifts.",
    "Yarn lot failed our own incoming check, re-spinning the balance.",
    "Transporter strike on the Tirupur route.",
    "Labour shortage after the festival week.",
)


def simulate_supplier_delay(
    session: Session,
    *,
    purchase_order_id: uuid.UUID | None = None,
    delay_days: int | None = None,
    reason: str | None = None,
) -> SimulationResult:
    """A supplier writes in to say they will be late.

    Runs through the genuine ingestion path, so the ETA change carries real
    provenance back to the message.
    """
    _guard()
    po = _pick_purchase_order(session, purchase_order_id)
    days = delay_days or random.randint(2, 9)
    why = reason or random.choice(_DELAY_REASONS)
    material = po.lines[0].material.name if po.lines else "the material"

    body = (
        f"Dear Sir,\n\n"
        f"Regarding {po.number}, dispatch of {material} will be delayed by {days} days. "
        f"{why}\n\n"
        f"We regret the inconvenience and will confirm the vehicle details once loaded.\n\n"
        f"Regards,\n{po.supplier.contact_name or 'Dispatch desk'}\n{po.supplier.name}"
    )
    message = pipeline.receive_message(
        session,
        body=body,
        sender=po.supplier.contact_email or f"{po.supplier.code.lower()}@example.com",
        subject=f"Delay in dispatch — {po.number}",
        channel=SourceChannel.SIMULATION,
        supplier_id=po.supplier_id,
    )
    outcome = pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    result = SimulationResult(
        event="supplier_delay",
        summary=(
            f"{po.supplier.name} reported a {days}-day delay on {po.number}. "
            + (
                f"Expected date moved to {po.current_expected_date.isoformat()}."
                if outcome.facts_applied
                else "The claim needs human reconciliation before it is applied."
            )
        ),
        details={
            "purchase_order": po.number,
            "message_id": str(message.id),
            "delay_days": days,
            "applied": bool(outcome.facts_applied),
            "new_expected_date": po.current_expected_date.isoformat(),
            "reconciliation_items": outcome.reconciliation_items,
            "notes": outcome.notes,
        },
    )
    return _finish(result, session)


def simulate_inventory_receipt(
    session: Session,
    *,
    purchase_order_line_id: uuid.UUID | None = None,
    quantity: Decimal | None = None,
    partial: bool = False,
) -> SimulationResult:
    """Goods arrive — in full, or short."""
    _guard()
    line = _pick_po_line(session, purchase_order_line_id)
    outstanding = line.outstanding_quantity
    if outstanding <= ZERO:
        raise ConflictError(f"Line {line.line_no} of {line.purchase_order.number} is complete.")
    received = quantity or (
        quantize(outstanding * Decimal("0.6")) if partial else outstanding
    )
    received = min(quantize(Decimal(str(received))), outstanding)

    outcome = procurement.receive(
        session,
        line,
        accepted_quantity=received,
        received_at=clock.now(),
        supplier_document_ref=f"SIM-{uuid.uuid4().hex[:8].upper()}",
        note="Simulated goods receipt.",
    )
    result = SimulationResult(
        event="inventory_receipt",
        summary=(
            f"Received {received} {line.unit.value} of {line.material.name} against "
            f"{line.purchase_order.number}"
            + (
                f"; {line.outstanding_quantity} {line.unit.value} still outstanding."
                if line.outstanding_quantity > ZERO
                else " — line complete."
            )
        ),
        details={
            "purchase_order": line.purchase_order.number,
            "material": line.material.name,
            "received": str(received),
            "outstanding": str(line.outstanding_quantity),
            "unit": line.unit.value,
            "lot_code": outcome.lot_code,
            "purchase_order_status": outcome.purchase_order_status.value,
        },
    )
    return _finish(result, session)


def simulate_qc_rejection(
    session: Session,
    *,
    production_batch_id: uuid.UUID | None = None,
    kind: str = "shade",
) -> SimulationResult:
    """A batch fails inspection, and the consequences propagate."""
    _guard()
    batch = _pick_batch(session, production_batch_id, require_output=True)
    spec = batch.fabric_spec
    inspected = batch.output_quantity or batch.planned_quantity
    rejected = quantize(inspected * Decimal("0.5"))

    if kind == "gsm":
        measurements = [
            MeasurementInput(
                kind=QCMeasurementKind.GSM,
                observed_value=quantize(Decimal(str(spec.gsm)) * Decimal("0.88")),
                target_value=Decimal(str(spec.gsm)),
                tolerance_low=quantize(Decimal(str(spec.gsm)) * Decimal("0.95")),
                tolerance_high=quantize(Decimal(str(spec.gsm)) * Decimal("1.05")),
                unit_text="gsm",
                note="Weight below the agreed tolerance.",
            )
        ]
        notes = "GSM measured below tolerance across three rolls."
    else:
        measurements = [
            MeasurementInput(
                kind=QCMeasurementKind.SHADE,
                observed_text="Off-shade vs approved swatch (greyer, ~1.5 DE)",
                unit_text="visual",
                note="Rejected against the customer's approved shade band.",
            )
        ]
        notes = "Shade does not match the approved swatch."

    inspection = quality.record_inspection(
        session,
        code=f"QC-SIM-{uuid.uuid4().hex[:6].upper()}",
        outcome=QCOutcome.REJECT,
        inspected_quantity=inspected,
        accepted_quantity=quantize(inspected - rejected),
        rejected_quantity=rejected,
        unit=batch.unit,
        production_batch_id=batch.id,
        measurements=measurements,
        notes=notes,
    )
    propagation = quality.propagate(session, inspection)

    result = SimulationResult(
        event="qc_rejection",
        summary=(
            f"{batch.code} failed {kind} inspection: {rejected} {batch.unit.value} rejected."
            + (
                f" Replacement batch {propagation.replacement_batch_code} scheduled."
                if propagation.replacement_batch_code
                else ""
            )
        ),
        details={
            "batch": batch.code,
            "inspection": inspection.code,
            "rejected": str(rejected),
            "unit": batch.unit.value,
            "replacement_batch": propagation.replacement_batch_code,
            "lots_quarantined": propagation.lots_quarantined,
            "orders_affected": propagation.affected_sales_order_numbers,
        },
    )
    return _finish(result, session)


def simulate_production_completion(
    session: Session, *, production_batch_id: uuid.UUID | None = None
) -> SimulationResult:
    """A batch finishes, with realistic wastage."""
    _guard()
    batch = _pick_batch(session, production_batch_id)
    if batch.status in (ProductionStatus.COMPLETED, ProductionStatus.CANCELLED):
        raise ConflictError(f"Batch {batch.code} is already {batch.status.value}.")

    if batch.status in (ProductionStatus.PLANNED, ProductionStatus.SCHEDULED):
        if batch.status == ProductionStatus.PLANNED:
            production.schedule_batch(session, batch)
        production.start_batch(session, batch)

    wastage = quantize(batch.planned_quantity * Decimal("0.03"))
    good = quantize(batch.planned_quantity - wastage)
    lot = production.record_output(
        session,
        batch,
        good_quantity=good,
        wastage_quantity=wastage,
        idempotency_key=f"sim-output:{uuid.uuid4().hex}",
    )
    inspection = quality.record_inspection(
        session,
        code=f"QC-SIM-{uuid.uuid4().hex[:6].upper()}",
        outcome=QCOutcome.PASS,
        inspected_quantity=good,
        accepted_quantity=good,
        rejected_quantity=ZERO,
        unit=batch.unit,
        production_batch_id=batch.id,
        measurements=quality.measurements_for_spec(
            batch.fabric_spec,
            # A good run: on target, with the small variation any real roll has.
            observed_gsm=quantize(Decimal(str(batch.fabric_spec.gsm)) * Decimal("0.99")),
            observed_width_cm=Decimal(str(batch.fabric_spec.width_cm)),
        ),
        notes="Simulated in-line inspection passed.",
    )
    quality.propagate(session, inspection)
    production.complete_batch(session, batch)

    result = SimulationResult(
        event="production_completion",
        summary=(
            f"{batch.code} completed: {good} {batch.unit.value} good, {wastage} wastage, "
            f"QC passed and stock released."
        ),
        details={
            "batch": batch.code,
            "good_quantity": str(good),
            "wastage": str(wastage),
            "unit": batch.unit.value,
            "lot_code": lot.lot_code if lot else None,
            "yield_pct": str(batch.yield_pct) if batch.yield_pct else None,
        },
    )
    return _finish(result, session)


def simulate_shipment_dispatch(
    session: Session, *, shipment_id: uuid.UUID | None = None
) -> SimulationResult:
    """A planned shipment leaves the building."""
    _guard()
    shipment = _pick_shipment(session, shipment_id)
    shipments.dispatch(
        session,
        shipment,
        dispatch_date=clock.today(),
        tracking_reference=f"LR-{uuid.uuid4().hex[:8].upper()}",
        idempotency_key=f"sim-dispatch:{shipment.id}",
    )
    result = SimulationResult(
        event="shipment_dispatch",
        summary=(
            f"Shipment {shipment.number} to {shipment.customer.name} dispatched with "
            f"reference {shipment.tracking_reference}."
        ),
        details={
            "shipment": shipment.number,
            "customer": shipment.customer.name,
            "tracking_reference": shipment.tracking_reference,
            "expected_delivery": (
                shipment.expected_delivery_date.isoformat()
                if shipment.expected_delivery_date
                else None
            ),
        },
    )
    return _finish(result, session)


# --- pickers ------------------------------------------------------------------


def _pick_purchase_order(session: Session, po_id: uuid.UUID | None) -> PurchaseOrder:
    if po_id:
        po = session.get(PurchaseOrder, po_id)
        if po is None:
            raise NotFoundError(f"Purchase order {po_id} not found.")
        return po
    candidates = [
        po
        for po in session.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
            .order_by(PurchaseOrder.expected_date)
        ).all()
        if any(line.outstanding_quantity > ZERO for line in po.lines)
    ]
    if not candidates:
        raise ConflictError("There is no open purchase order to delay.")
    return candidates[0]


def _pick_po_line(session: Session, line_id: uuid.UUID | None) -> PurchaseOrderLine:
    if line_id:
        line = session.get(PurchaseOrderLine, line_id)
        if line is None:
            raise NotFoundError(f"Purchase order line {line_id} not found.")
        return line
    po = _pick_purchase_order(session, None)
    for line in po.lines:
        if line.outstanding_quantity > ZERO:
            return line
    raise ConflictError("No purchase order line has an outstanding quantity.")


def _pick_batch(
    session: Session, batch_id: uuid.UUID | None, *, require_output: bool = False
) -> ProductionBatch:
    if batch_id:
        batch = session.get(ProductionBatch, batch_id)
        if batch is None:
            raise NotFoundError(f"Production batch {batch_id} not found.")
        return batch
    statuses = (
        (ProductionStatus.IN_PROGRESS, ProductionStatus.COMPLETED)
        if require_output
        else production.OPEN_STATUSES
    )
    batches = session.scalars(
        select(ProductionBatch)
        .where(ProductionBatch.status.in_(statuses))
        .order_by(ProductionBatch.planned_completion)
    ).all()
    if require_output:
        batches = [b for b in batches if b.output_quantity > ZERO] or list(batches)
    if not batches:
        raise ConflictError("There is no suitable production batch for this event.")
    return batches[0]


def _pick_shipment(session: Session, shipment_id: uuid.UUID | None) -> Shipment:
    if shipment_id:
        shipment = session.get(Shipment, shipment_id)
        if shipment is None:
            raise NotFoundError(f"Shipment {shipment_id} not found.")
        return shipment
    shipment = session.scalars(
        select(Shipment)
        .where(Shipment.status.in_([ShipmentStatus.PLANNED, ShipmentStatus.PACKED]))
        .order_by(Shipment.created_at)
    ).first()
    if shipment is None:
        raise ConflictError("There is no planned shipment to dispatch.")
    return shipment


DISPATCH: dict[str, Callable[..., SimulationResult]] = {
    "supplier_delay": simulate_supplier_delay,
    "inventory_receipt": simulate_inventory_receipt,
    "qc_rejection": simulate_qc_rejection,
    "production_completion": simulate_production_completion,
    "shipment_dispatch": simulate_shipment_dispatch,
}


def run(session: Session, event: str, **kwargs: Any) -> SimulationResult:
    if event not in DISPATCH:
        raise ValidationError(
            f"Unknown simulation event {event!r}. Available: {', '.join(AVAILABLE_EVENTS)}."
        )
    return DISPATCH[event](session, **kwargs)
