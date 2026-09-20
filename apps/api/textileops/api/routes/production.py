"""Production batches and quality inspections."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from textileops.api.deps import ApproverUser, CurrentUser, DbSession
from textileops.core.errors import NotFoundError, ValidationError
from textileops.core.units import parse_unit
from textileops.models.enums import ProductionStatus, QCMeasurementKind, QCOutcome
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import production as production_service
from textileops.services import quality as quality_service
from textileops.services.quality import MeasurementInput

router = APIRouter(tags=["production"])


class RequirementOut(BaseModel):
    material_id: uuid.UUID
    material_code: str
    material_name: str
    required_quantity: Decimal
    issued_quantity: Decimal
    outstanding_quantity: Decimal
    unit: str
    required_by: dt.date


class BatchEventOut(BaseModel):
    id: uuid.UUID
    occurred_at: dt.datetime
    event_type: str
    quantity: Decimal | None
    unit: str | None
    note: str | None


class BatchOut(BaseModel):
    id: uuid.UUID
    code: str
    fabric_spec_id: uuid.UUID
    fabric_name: str
    stage: str
    status: str
    planned_quantity: Decimal
    output_quantity: Decimal
    wastage_quantity: Decimal
    rejected_quantity: Decimal
    unit: str
    planned_start: dt.date
    planned_completion: dt.date
    estimated_completion: dt.date | None
    actual_completion: dt.datetime | None
    delay_days: int
    yield_pct: Decimal | None
    priority: int
    blocked_reason: str | None
    sales_order_id: uuid.UUID | None
    sales_order_number: str | None
    customer_name: str | None


class BatchDetailOut(BatchOut):
    requirements: list[RequirementOut]
    events: list[BatchEventOut]
    material_ready_date: dt.date | None
    notes: str | None


def _batch_out(session: DbSession, batch: ProductionBatch) -> BatchOut:
    order_number = None
    customer_name = None
    order_id = None
    if batch.sales_order_line_id:
        row = session.execute(
            select(SalesOrder)
            .join(SalesOrderLine, SalesOrderLine.sales_order_id == SalesOrder.id)
            .where(SalesOrderLine.id == batch.sales_order_line_id)
        ).scalar_one_or_none()
        if row is not None:
            order_number, customer_name, order_id = row.number, row.customer.name, row.id
    delay = (
        (batch.estimated_completion - batch.planned_completion).days
        if batch.estimated_completion
        else 0
    )
    return BatchOut(
        id=batch.id,
        code=batch.code,
        fabric_spec_id=batch.fabric_spec_id,
        fabric_name=batch.fabric_spec.name,
        stage=batch.stage.value,
        status=batch.status.value,
        planned_quantity=batch.planned_quantity,
        output_quantity=batch.output_quantity,
        wastage_quantity=batch.wastage_quantity,
        rejected_quantity=batch.rejected_quantity,
        unit=batch.unit.value,
        planned_start=batch.planned_start,
        planned_completion=batch.planned_completion,
        estimated_completion=batch.estimated_completion,
        actual_completion=batch.actual_completion,
        delay_days=max(0, delay),
        yield_pct=batch.yield_pct,
        priority=batch.priority,
        blocked_reason=batch.blocked_reason,
        sales_order_id=order_id,
        sales_order_number=order_number,
        customer_name=customer_name,
    )


@router.get("/production/batches", response_model=list[BatchOut])
def list_batches(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    open_only: bool = True,
    limit: int = Query(200, ge=1, le=500),
) -> list[BatchOut]:
    stmt = select(ProductionBatch).order_by(ProductionBatch.planned_completion).limit(limit)
    if status:
        stmt = stmt.where(ProductionBatch.status == ProductionStatus(status))
    elif open_only:
        stmt = stmt.where(ProductionBatch.status.in_(production_service.OPEN_STATUSES))
    return [_batch_out(session, batch) for batch in session.scalars(stmt).all()]


@router.get("/production/batches/{batch_id}", response_model=BatchDetailOut)
def get_batch(batch_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> BatchDetailOut:
    batch = session.get(ProductionBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"Production batch {batch_id} not found.")
    return BatchDetailOut(
        **_batch_out(session, batch).model_dump(),
        notes=batch.notes,
        material_ready_date=production_service.material_ready_date(session, batch),
        requirements=[
            RequirementOut(
                material_id=requirement.material_id,
                material_code=requirement.material.code,
                material_name=requirement.material.name,
                required_quantity=requirement.required_quantity,
                issued_quantity=requirement.issued_quantity,
                outstanding_quantity=requirement.outstanding_quantity,
                unit=requirement.unit.value,
                required_by=requirement.required_by,
            )
            for requirement in batch.requirements
        ],
        events=[
            BatchEventOut(
                id=event.id,
                occurred_at=event.occurred_at,
                event_type=event.event_type.value,
                quantity=event.quantity,
                unit=event.unit.value if event.unit else None,
                note=event.note,
            )
            for event in sorted(batch.events, key=lambda e: e.occurred_at)
        ],
    )


class BatchActionRequest(BaseModel):
    action: str = Field(pattern="^(schedule|start|block|complete)$")
    reason: str | None = None


@router.post("/production/batches/{batch_id}/actions", response_model=BatchOut)
def batch_action(
    batch_id: uuid.UUID, payload: BatchActionRequest, session: DbSession, user: ApproverUser
) -> BatchOut:
    batch = session.get(ProductionBatch, batch_id)
    if batch is None:
        raise NotFoundError(f"Production batch {batch_id} not found.")
    if payload.action == "schedule":
        production_service.schedule_batch(session, batch, user_id=user.id)
    elif payload.action == "start":
        production_service.start_batch(session, batch, user_id=user.id)
    elif payload.action == "block":
        production_service.block_batch(
            session, batch, payload.reason or "Blocked by operator.", user_id=user.id
        )
    elif payload.action == "complete":
        production_service.complete_batch(session, batch, user_id=user.id)
    else:
        # Falling through to completion here would mean a typo or a stale
        # front-end could finish a batch, release its materials and credit the
        # customer order.
        raise ValidationError(f"Unknown batch action {payload.action!r}.")
    session.commit()
    return _batch_out(session, batch)


# --- Quality ------------------------------------------------------------------


class MeasurementOut(BaseModel):
    kind: str
    label: str | None
    observed_value: Decimal | None
    observed_text: str | None
    target_value: Decimal | None
    tolerance_low: Decimal | None
    tolerance_high: Decimal | None
    unit_text: str | None
    result: str


class InspectionOut(BaseModel):
    id: uuid.UUID
    code: str
    production_batch_id: uuid.UUID | None
    batch_code: str | None
    inventory_lot_id: uuid.UUID | None
    inspected_at: dt.datetime
    outcome: str
    inspected_quantity: Decimal
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    unit: str
    notes: str | None
    reinspection_of_id: uuid.UUID | None
    measurements: list[MeasurementOut]


def _inspection_out(session: DbSession, inspection: QCInspection) -> InspectionOut:
    batch = (
        session.get(ProductionBatch, inspection.production_batch_id)
        if inspection.production_batch_id
        else None
    )
    return InspectionOut(
        id=inspection.id,
        code=inspection.code,
        production_batch_id=inspection.production_batch_id,
        batch_code=batch.code if batch else None,
        inventory_lot_id=inspection.inventory_lot_id,
        inspected_at=inspection.inspected_at,
        outcome=inspection.outcome.value,
        inspected_quantity=inspection.inspected_quantity,
        accepted_quantity=inspection.accepted_quantity,
        rejected_quantity=inspection.rejected_quantity,
        unit=inspection.unit.value,
        notes=inspection.notes,
        reinspection_of_id=inspection.reinspection_of_id,
        measurements=[
            MeasurementOut(
                kind=m.kind.value,
                label=m.label,
                observed_value=m.observed_value,
                observed_text=m.observed_text,
                target_value=m.target_value,
                tolerance_low=m.tolerance_low,
                tolerance_high=m.tolerance_high,
                unit_text=m.unit_text,
                result=m.result.value,
            )
            for m in inspection.measurements
        ],
    )


@router.get("/quality/inspections", response_model=list[InspectionOut])
def list_inspections(
    session: DbSession,
    _user: CurrentUser,
    outcome: str | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[InspectionOut]:
    stmt = select(QCInspection).order_by(QCInspection.inspected_at.desc()).limit(limit)
    if outcome:
        stmt = stmt.where(QCInspection.outcome == QCOutcome(outcome))
    if batch_id:
        stmt = stmt.where(QCInspection.production_batch_id == batch_id)
    return [_inspection_out(session, i) for i in session.scalars(stmt).all()]


class MeasurementIn(BaseModel):
    kind: str
    observed_value: Decimal | None = None
    observed_text: str | None = None
    target_value: Decimal | None = None
    tolerance_low: Decimal | None = None
    tolerance_high: Decimal | None = None
    unit_text: str | None = None
    label: str | None = None
    note: str | None = None


class InspectionIn(BaseModel):
    production_batch_id: uuid.UUID | None = None
    inventory_lot_id: uuid.UUID | None = None
    outcome: str
    inspected_quantity: Decimal = Field(gt=0)
    accepted_quantity: Decimal | None = None
    rejected_quantity: Decimal | None = None
    unit: str
    notes: str | None = None
    reinspection_of_id: uuid.UUID | None = None
    measurements: list[MeasurementIn] = Field(default_factory=list)
    schedule_replacement: bool = True


class InspectionResultOut(BaseModel):
    inspection: InspectionOut
    lots_quarantined: list[str]
    lots_released: list[str]
    replacement_batch_code: str | None
    affected_sales_orders: list[str]


@router.post("/quality/inspections", response_model=InspectionResultOut)
def create_inspection(
    payload: InspectionIn, session: DbSession, user: ApproverUser
) -> InspectionResultOut:
    code = f"QC-{uuid.uuid4().hex[:8].upper()}"
    inspection = quality_service.record_inspection(
        session,
        code=code,
        outcome=QCOutcome(payload.outcome),
        inspected_quantity=payload.inspected_quantity,
        accepted_quantity=payload.accepted_quantity,
        rejected_quantity=payload.rejected_quantity,
        unit=parse_unit(payload.unit),
        production_batch_id=payload.production_batch_id,
        inventory_lot_id=payload.inventory_lot_id,
        reinspection_of_id=payload.reinspection_of_id,
        inspector_user_id=user.id,
        notes=payload.notes,
        measurements=[
            MeasurementInput(
                kind=QCMeasurementKind(m.kind),
                observed_value=m.observed_value,
                observed_text=m.observed_text,
                target_value=m.target_value,
                tolerance_low=m.tolerance_low,
                tolerance_high=m.tolerance_high,
                unit_text=m.unit_text,
                label=m.label,
                note=m.note,
            )
            for m in payload.measurements
        ],
    )
    propagation = quality_service.propagate(
        session,
        inspection,
        schedule_replacement=payload.schedule_replacement,
        user_id=user.id,
    )
    session.commit()
    return InspectionResultOut(
        inspection=_inspection_out(session, inspection),
        lots_quarantined=propagation.lots_quarantined,
        lots_released=propagation.lots_released,
        replacement_batch_code=propagation.replacement_batch_code,
        affected_sales_orders=propagation.affected_sales_order_numbers,
    )
