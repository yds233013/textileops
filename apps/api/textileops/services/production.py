"""Production batches: planning, material requirements and schedule estimation.

The estimation model is intentionally simple and fully deterministic, because
an estimate an operator cannot reproduce by hand is an estimate they will not
trust:

    duration      = planned_completion − planned_start   (calendar days)
    start         = actual start, else the later of planned start / today,
                    never earlier than the date the materials are on site
    estimate      = start + duration

That last clause is where procurement reality enters production planning: if
the yarn lands on the 14th, a batch that needs it cannot start on the 10th.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.errors import IllegalStateTransition, NotFoundError, ValidationError
from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.catalog import FabricSpec
from textileops.models.enums import (
    EntityType,
    LotStatus,
    MovementType,
    ProductionEventType,
    ProductionStage,
    ProductionStatus,
)
from textileops.models.inventory import InventoryLot
from textileops.models.production import (
    ProductionBatch,
    ProductionEvent,
    ProductionMaterialRequirement,
)
from textileops.models.sales import SalesOrderLine
from textileops.services import clock, inventory
from textileops.services.audit import record_audit

ZERO = Decimal("0")

OPEN_STATUSES = (
    ProductionStatus.PLANNED,
    ProductionStatus.SCHEDULED,
    ProductionStatus.IN_PROGRESS,
    ProductionStatus.BLOCKED,
    ProductionStatus.REWORK,
)

#: Allowed status transitions. Enforced here, not scattered through routes.
TRANSITIONS: dict[ProductionStatus, set[ProductionStatus]] = {
    ProductionStatus.PLANNED: {
        ProductionStatus.SCHEDULED,
        ProductionStatus.IN_PROGRESS,
        ProductionStatus.BLOCKED,
        ProductionStatus.CANCELLED,
    },
    ProductionStatus.SCHEDULED: {
        ProductionStatus.IN_PROGRESS,
        ProductionStatus.BLOCKED,
        ProductionStatus.CANCELLED,
        ProductionStatus.PLANNED,
    },
    ProductionStatus.IN_PROGRESS: {
        ProductionStatus.COMPLETED,
        ProductionStatus.BLOCKED,
        ProductionStatus.REJECTED,
        ProductionStatus.REWORK,
        ProductionStatus.CANCELLED,
    },
    ProductionStatus.BLOCKED: {
        ProductionStatus.IN_PROGRESS,
        ProductionStatus.SCHEDULED,
        ProductionStatus.PLANNED,
        ProductionStatus.CANCELLED,
    },
    ProductionStatus.REWORK: {
        ProductionStatus.IN_PROGRESS,
        ProductionStatus.COMPLETED,
        ProductionStatus.REJECTED,
        ProductionStatus.CANCELLED,
    },
    ProductionStatus.COMPLETED: {ProductionStatus.REWORK},
    ProductionStatus.REJECTED: {ProductionStatus.REWORK},
    ProductionStatus.CANCELLED: set(),
}


#: Statuses after which a batch will never consume its materials.
TERMINAL_STATUSES = (
    ProductionStatus.COMPLETED,
    ProductionStatus.REJECTED,
    ProductionStatus.CANCELLED,
)


def _transition(batch: ProductionBatch, to: ProductionStatus) -> None:
    if to == batch.status:
        return
    if to not in TRANSITIONS.get(batch.status, set()):
        raise IllegalStateTransition(
            f"Batch {batch.code} cannot move from {batch.status.value} to {to.value}.",
            details={"from": batch.status.value, "to": to.value},
        )
    batch.status = to


def release_materials_if_terminal(session: Session, batch: ProductionBatch) -> int:
    """Give a finished, rejected or cancelled batch's materials back.

    A dead batch that keeps its reservations locks stock away for ever: the
    material is neither consumed nor available, and every coverage calculation
    that follows is wrong by that amount.
    """
    if batch.status not in TERMINAL_STATUSES:
        return 0
    return inventory.release_reservations(session, production_batch_id=batch.id)


def add_event(
    session: Session,
    batch: ProductionBatch,
    event_type: ProductionEventType,
    *,
    note: str | None = None,
    quantity: Decimal | None = None,
    unit: UnitOfMeasure | None = None,
    occurred_at: dt.datetime | None = None,
    user_id: uuid.UUID | None = None,
    payload: dict[str, object] | None = None,
) -> ProductionEvent:
    event = ProductionEvent(
        production_batch_id=batch.id,
        event_type=event_type,
        occurred_at=occurred_at or clock.now(),
        note=note,
        quantity=quantity,
        unit=unit,
        created_by_user_id=user_id,
        payload=payload,
    )
    session.add(event)
    return event


def create_batch(
    session: Session,
    *,
    code: str,
    fabric_spec_id: uuid.UUID,
    planned_quantity: Decimal,
    planned_start: dt.date,
    planned_completion: dt.date,
    stage: ProductionStage,
    sales_order_line_id: uuid.UUID | None = None,
    unit: UnitOfMeasure | None = None,
    priority: int = 5,
    reserve_materials: bool = True,
    **kwargs: object,
) -> ProductionBatch:
    """Create a batch and explode the fabric spec's bill of materials."""
    spec = session.get(FabricSpec, fabric_spec_id)
    if spec is None:
        raise NotFoundError(f"Fabric spec {fabric_spec_id} not found.")
    if planned_completion < planned_start:
        raise ValidationError("Planned completion cannot precede planned start.")

    batch = ProductionBatch(
        code=code,
        fabric_spec_id=fabric_spec_id,
        sales_order_line_id=sales_order_line_id,
        stage=stage,
        status=ProductionStatus.PLANNED,
        planned_quantity=quantize(planned_quantity),
        unit=unit or spec.sale_unit,
        planned_start=planned_start,
        planned_completion=planned_completion,
        priority=priority,
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(batch)
    session.flush()

    explode_requirements(session, batch, reserve=reserve_materials)
    # Compute the estimate from real material coverage rather than assuming the
    # plan is achievable; a batch is never born optimistic.
    recompute_estimated_completion(session, batch)
    add_event(session, batch, ProductionEventType.CREATED, note=f"Batch {code} planned.")
    return batch


def explode_requirements(
    session: Session, batch: ProductionBatch, *, reserve: bool = True
) -> list[ProductionMaterialRequirement]:
    """Turn the fabric BOM into concrete material requirements for this batch.

    ``required = quantity_per_unit × batch_quantity ÷ (1 − wastage_pct)``
    — wastage inflates what must be *bought*, it does not reduce what is needed.
    """
    spec = batch.fabric_spec
    requirements: list[ProductionMaterialRequirement] = []
    # Materials must be on site before the batch starts, not when it ends.
    required_by = batch.planned_start

    for component in spec.components:
        batch_qty_in_spec_unit = convert(batch.planned_quantity, batch.unit, spec.sale_unit)
        gross = component.quantity_per_unit * batch_qty_in_spec_unit
        if component.wastage_pct > 0:
            gross = gross / (Decimal("1") - component.wastage_pct)
        requirement = ProductionMaterialRequirement(
            production_batch_id=batch.id,
            material_id=component.material_id,
            required_quantity=quantize(gross),
            unit=component.unit,
            required_by=required_by,
        )
        session.add(requirement)
        requirements.append(requirement)
        if reserve:
            inventory.reserve(
                session,
                quantity=requirement.required_quantity,
                unit=requirement.unit,
                material_id=component.material_id,
                production_batch_id=batch.id,
                required_by=required_by,
                note=f"Requirement for batch {batch.code}",
            )
    session.flush()
    return requirements


def material_ready_date(session: Session, batch: ProductionBatch) -> dt.date | None:
    """Earliest date every material for this batch is physically on site.

    ``None`` means at least one material is not covered at all within the
    planning horizon — the batch cannot be scheduled truthfully.
    """
    from textileops.services.coverage import analyse_material

    if not batch.requirements:
        return clock.today()

    latest = clock.today()
    for requirement in batch.requirements:
        if requirement.outstanding_quantity <= ZERO:
            continue
        coverage = analyse_material(session, requirement.material_id)
        allocation = next(
            (
                a
                for a in coverage.allocations
                if a.requirement.production_batch_id == batch.id
            ),
            None,
        )
        if allocation is None:
            continue
        if allocation.is_short:
            return None
        if allocation.covered_by_date and allocation.covered_by_date > latest:
            latest = allocation.covered_by_date
    return latest


def recompute_estimated_completion(
    session: Session, batch: ProductionBatch, *, consider_materials: bool = True
) -> dt.date | None:
    """Deterministic schedule estimate. See the module docstring for the model."""
    if batch.status in (ProductionStatus.COMPLETED, ProductionStatus.CANCELLED):
        if batch.actual_completion:
            batch.estimated_completion = batch.actual_completion.date()
        return batch.estimated_completion

    today = clock.today()
    duration = max(0, (batch.planned_completion - batch.planned_start).days)

    if batch.actual_start:
        start = batch.actual_start.date()
    else:
        start = max(batch.planned_start, today)

    if consider_materials and batch.status != ProductionStatus.IN_PROGRESS:
        ready = material_ready_date(session, batch)
        if ready is None:
            # Materials are not covered: no honest completion date exists.
            batch.estimated_completion = None
            return None
        start = max(start, ready)

    if batch.status == ProductionStatus.BLOCKED:
        start = max(start, today)

    batch.estimated_completion = start + dt.timedelta(days=duration)
    return batch.estimated_completion


def schedule_batch(session: Session, batch: ProductionBatch, *, user_id=None) -> ProductionBatch:
    _transition(batch, ProductionStatus.SCHEDULED)
    recompute_estimated_completion(session, batch)
    add_event(session, batch, ProductionEventType.SCHEDULED, user_id=user_id)
    return batch


def start_batch(
    session: Session,
    batch: ProductionBatch,
    *,
    at: dt.datetime | None = None,
    user_id: uuid.UUID | None = None,
) -> ProductionBatch:
    _transition(batch, ProductionStatus.IN_PROGRESS)
    batch.actual_start = at or clock.now()
    batch.blocked_reason = None
    recompute_estimated_completion(session, batch)
    add_event(session, batch, ProductionEventType.STARTED, occurred_at=batch.actual_start,
              user_id=user_id)
    record_audit(
        session,
        action="production.started",
        entity_type=EntityType.PRODUCTION_BATCH,
        entity_id=batch.id,
        summary=f"Batch {batch.code} started.",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
    )
    return batch


def block_batch(
    session: Session, batch: ProductionBatch, reason: str, *, user_id: uuid.UUID | None = None
) -> ProductionBatch:
    if not reason:
        raise ValidationError("A blocked batch must record why it is blocked.")
    _transition(batch, ProductionStatus.BLOCKED)
    batch.blocked_reason = reason
    recompute_estimated_completion(session, batch)
    add_event(session, batch, ProductionEventType.BLOCKED, note=reason, user_id=user_id)
    record_audit(
        session,
        action="production.blocked",
        entity_type=EntityType.PRODUCTION_BATCH,
        entity_id=batch.id,
        summary=f"Batch {batch.code} blocked: {reason}",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
    )
    return batch


def record_output(
    session: Session,
    batch: ProductionBatch,
    *,
    good_quantity: Decimal,
    wastage_quantity: Decimal = ZERO,
    rejected_quantity: Decimal = ZERO,
    unit: UnitOfMeasure | None = None,
    lot_code: str | None = None,
    at: dt.datetime | None = None,
    user_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> InventoryLot | None:
    """Record batch output, creating a finished-goods lot for the good quantity."""
    unit = unit or batch.unit
    good = convert(Decimal(str(good_quantity)), unit, batch.unit)
    waste = convert(Decimal(str(wastage_quantity)), unit, batch.unit)
    rejected = convert(Decimal(str(rejected_quantity)), unit, batch.unit)
    if good < ZERO or waste < ZERO or rejected < ZERO:
        raise ValidationError("Output quantities cannot be negative.")

    occurred = at or clock.now()
    batch.output_quantity = quantize(batch.output_quantity + good)
    batch.wastage_quantity = quantize(batch.wastage_quantity + waste)
    batch.rejected_quantity = quantize(batch.rejected_quantity + rejected)

    lot: InventoryLot | None = None
    if good > ZERO:
        lot = inventory.create_lot(
            session,
            lot_code=lot_code or f"{batch.code}-OUT",
            fabric_spec_id=batch.fabric_spec_id,
            quantity=good,
            unit=batch.unit,
            received_at=occurred,
            status=LotStatus.QUARANTINE,  # released to AVAILABLE by QC
            production_batch_id=batch.id,
            notes=f"Output of batch {batch.code}",
            movement_type=MovementType.PRODUCTION_OUTPUT,
            reference_type=EntityType.PRODUCTION_BATCH,
            reference_id=batch.id,
            idempotency_key=idempotency_key,
            movement_note=f"Good output from batch {batch.code}.",
        )

    add_event(
        session,
        batch,
        ProductionEventType.OUTPUT_RECORDED,
        quantity=good,
        unit=batch.unit,
        occurred_at=occurred,
        user_id=user_id,
        note=f"Good {good} {batch.unit.value}, wastage {waste}, rejected {rejected}.",
    )
    record_audit(
        session,
        action="production.output_recorded",
        entity_type=EntityType.PRODUCTION_BATCH,
        entity_id=batch.id,
        summary=f"Batch {batch.code} produced {good} {batch.unit.value}.",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
        after={"good": good, "wastage": waste, "rejected": rejected},
    )
    return lot


@dataclass
class MaterialIssue:
    """What a batch actually drew from stock, and what it could not find."""

    issued: dict[str, Decimal]
    shortfalls: dict[str, Decimal]


def issue_materials(
    session: Session, batch: ProductionBatch, *, at: dt.datetime | None = None
) -> MaterialIssue:
    """Consume the batch's outstanding material requirements from stock.

    Reserving material is a promise; issuing it is the physical act. Without
    this, stock would only ever go up: every completed batch would give its
    reservation back and the yarn it actually burned would still appear on the
    shelf, so the next coverage run would schedule work against material that
    no longer exists.

    Issues oldest lot first. Where stock is short, it issues what exists and
    reports the shortfall rather than inventing a negative balance.
    """
    occurred = at or clock.now()
    issued: dict[str, Decimal] = {}
    shortfalls: dict[str, Decimal] = {}

    for requirement in batch.requirements:
        outstanding = requirement.outstanding_quantity
        if outstanding <= ZERO:
            continue
        material = requirement.material
        remaining = convert(outstanding, requirement.unit, material.base_unit)
        drawn = ZERO

        lots = session.scalars(
            select(InventoryLot)
            .where(
                InventoryLot.material_id == requirement.material_id,
                InventoryLot.status == LotStatus.AVAILABLE,
                InventoryLot.quantity_on_hand > 0,
            )
            .order_by(InventoryLot.received_at)
        ).all()

        for lot in lots:
            if remaining <= ZERO:
                break
            take = min(convert(lot.quantity_on_hand, lot.unit, material.base_unit), remaining)
            if take <= ZERO:
                continue
            inventory.post_movement(
                session,
                lot=lot,
                movement_type=MovementType.ISSUE,
                quantity=convert(take, material.base_unit, lot.unit),
                occurred_at=occurred,
                reference_type=EntityType.PRODUCTION_BATCH,
                reference_id=batch.id,
                idempotency_key=f"batch-issue:{batch.id}:{requirement.id}:{lot.id}",
                note=f"Issued to batch {batch.code}.",
            )
            drawn = quantize(drawn + take)
            remaining = quantize(remaining - take)

        if drawn > ZERO:
            requirement.issued_quantity = quantize(
                requirement.issued_quantity
                + convert(drawn, material.base_unit, requirement.unit)
            )
            # The promise has been kept: draw the reservation down by what was
            # actually taken. Leaving it standing would deduct the same
            # kilograms twice — once as stock that left, once as stock still
            # claimed — and tell the floor it has nothing when it has plenty.
            inventory.consume_reservations(
                session,
                production_batch_id=batch.id,
                material_id=requirement.material_id,
                quantity=drawn,
                unit=material.base_unit,
            )
            issued[material.code] = drawn
        if remaining > ZERO:
            shortfalls[material.code] = remaining

    session.flush()
    return MaterialIssue(issued=issued, shortfalls=shortfalls)


def complete_batch(
    session: Session,
    batch: ProductionBatch,
    *,
    at: dt.datetime | None = None,
    user_id: uuid.UUID | None = None,
) -> ProductionBatch:
    completed_at = at or clock.now()
    # Consume before releasing: what the batch burned must leave the shelf.
    consumption = issue_materials(session, batch, at=completed_at)
    _transition(batch, ProductionStatus.COMPLETED)
    batch.actual_completion = completed_at
    batch.estimated_completion = batch.actual_completion.date()
    inventory.release_reservations(session, production_batch_id=batch.id)
    _propagate_produced_quantity(session, batch)

    if consumption.issued:
        add_event(
            session,
            batch,
            ProductionEventType.NOTE,
            occurred_at=completed_at,
            note="Materials issued: "
            + ", ".join(f"{code} {qty}" for code, qty in consumption.issued.items()),
            user_id=user_id,
        )
    if consumption.shortfalls:
        # The goods were physically made, so completion is not blocked — but a
        # batch that consumed material we cannot account for is a real problem.
        add_event(
            session,
            batch,
            ProductionEventType.NOTE,
            occurred_at=completed_at,
            note="Could not issue from stock: "
            + ", ".join(f"{code} {qty}" for code, qty in consumption.shortfalls.items())
            + ". Physical stock and records disagree; reconcile this lot.",
            user_id=user_id,
        )
    add_event(session, batch, ProductionEventType.COMPLETED, occurred_at=batch.actual_completion,
              user_id=user_id)
    record_audit(
        session,
        action="production.completed",
        entity_type=EntityType.PRODUCTION_BATCH,
        entity_id=batch.id,
        summary=f"Batch {batch.code} completed with {batch.output_quantity} {batch.unit.value}.",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
    )
    return batch


def _propagate_produced_quantity(session: Session, batch: ProductionBatch) -> None:
    """Recompute the line's produced quantity from its batches.

    Derived rather than accumulated: a batch can legitimately be completed more
    than once (complete → rework after a QC failure → complete again), and
    adding its cumulative output each time would double-count it.
    """
    if not batch.sales_order_line_id:
        return
    line = session.get(SalesOrderLine, batch.sales_order_line_id)
    if line is None:
        return
    completed = session.scalars(
        select(ProductionBatch).where(
            ProductionBatch.sales_order_line_id == line.id,
            ProductionBatch.status == ProductionStatus.COMPLETED,
        )
    ).all()
    seen = {other.id for other in completed}
    total = sum(
        (convert(other.output_quantity, other.unit, line.unit) for other in completed),
        ZERO,
    )
    # This batch is mid-transition and may not be in the query result yet.
    if batch.status == ProductionStatus.COMPLETED and batch.id not in seen:
        total += convert(batch.output_quantity, batch.unit, line.unit)
    line.produced_quantity = quantize(total)


def create_rework_batch(
    session: Session,
    original: ProductionBatch,
    *,
    quantity: Decimal,
    code: str,
    days: int | None = None,
    user_id: uuid.UUID | None = None,
) -> ProductionBatch:
    """Schedule replacement production after a QC rejection."""
    duration = days if days is not None else max(
        1, (original.planned_completion - original.planned_start).days
    )
    start = clock.today()
    batch = create_batch(
        session,
        code=code,
        fabric_spec_id=original.fabric_spec_id,
        planned_quantity=quantity,
        planned_start=start,
        planned_completion=start + dt.timedelta(days=duration),
        stage=original.stage,
        sales_order_line_id=original.sales_order_line_id,
        unit=original.unit,
        priority=max(1, original.priority - 1),
        rework_of_batch_id=original.id,
        notes=f"Replacement for {original.code}.",
    )
    add_event(
        session,
        batch,
        ProductionEventType.REWORK_STARTED,
        note=f"Replacement batch for {original.code}.",
        user_id=user_id,
    )
    record_audit(
        session,
        action="production.rework_scheduled",
        entity_type=EntityType.PRODUCTION_BATCH,
        entity_id=batch.id,
        summary=f"Replacement batch {batch.code} scheduled for {original.code}.",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
    )
    return batch


def open_batches(session: Session) -> list[ProductionBatch]:
    return list(
        session.scalars(
            select(ProductionBatch)
            .where(ProductionBatch.status.in_(OPEN_STATUSES))
            .order_by(ProductionBatch.planned_completion)
        ).all()
    )


def refresh_all_estimates(session: Session) -> int:
    """Recompute every open batch's estimate. Idempotent; safe to run often."""
    count = 0
    for batch in open_batches(session):
        before = batch.estimated_completion
        after = recompute_estimated_completion(session, batch)
        if before != after:
            count += 1
    return count


@dataclass
class BatchDelay:
    batch: ProductionBatch
    delay_days: int
    reason: str


def delayed_batches(session: Session) -> list[BatchDelay]:
    """Batches whose honest estimate is later than what was planned."""
    out: list[BatchDelay] = []
    for batch in open_batches(session):
        estimate = batch.estimated_completion
        if estimate is None:
            out.append(
                BatchDelay(
                    batch=batch,
                    delay_days=0,
                    reason=(
                        "Materials for this batch are not covered, so no completion date "
                        "can be given."
                    ),
                )
            )
            continue
        delay = (estimate - batch.planned_completion).days
        if delay > 0:
            reason = (
                batch.blocked_reason
                if batch.status == ProductionStatus.BLOCKED and batch.blocked_reason
                else "Schedule has slipped against the plan."
            )
            out.append(BatchDelay(batch=batch, delay_days=delay, reason=reason))
    return out
