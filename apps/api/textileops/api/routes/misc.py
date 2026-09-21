"""Shipments, search, audit, metrics and the demo simulation."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from textileops.api.deps import ApproverUser, CurrentUser, DbSession
from textileops.core.errors import NotFoundError
from textileops.models.enums import ShipmentStatus
from textileops.models.logistics import Shipment
from textileops.models.org import User
from textileops.models.platform import AuditEvent
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock
from textileops.services import metrics as metrics_service
from textileops.services import search as search_service
from textileops.services import shipments as shipment_service
from textileops.services import simulation as simulation_service

router = APIRouter(tags=["operations"])


# --- Shipments ----------------------------------------------------------------


class ShipmentLineOut(BaseModel):
    id: uuid.UUID
    sales_order_line_id: uuid.UUID
    sales_order_number: str | None
    quantity: Decimal
    unit: str


class ShipmentOut(BaseModel):
    id: uuid.UUID
    number: str
    customer_id: uuid.UUID
    customer_name: str
    status: str
    carrier: str | None
    tracking_reference: str | None
    dispatch_date: dt.date | None
    expected_delivery_date: dt.date | None
    actual_delivery_date: dt.date | None
    days_late: int
    #: True when the arrival itself was late, as opposed to still missing.
    delivered_late: bool
    lines: list[ShipmentLineOut]
    notes: str | None


def _shipment_out(session: DbSession, shipment: Shipment) -> ShipmentOut:
    today = clock.today()
    days_late = 0
    if shipment.expected_delivery_date:
        # Measured against the arrival if there is one, and against today if
        # there is not. This used to require `actual_delivery_date is None`,
        # so the only shipments that could ever be marked late were ones that
        # had not arrived: a delivery twelve days past its expected date read
        # as 0 — identical, on screen, to one that arrived on time.
        reference = shipment.actual_delivery_date or today
        if reference > shipment.expected_delivery_date:
            days_late = (reference - shipment.expected_delivery_date).days
    numbers: dict[uuid.UUID, str] = {}
    if shipment.lines:
        rows = session.execute(
            select(SalesOrderLine.id, SalesOrder.number)
            .join(SalesOrder, SalesOrderLine.sales_order_id == SalesOrder.id)
            .where(
                SalesOrderLine.id.in_([line.sales_order_line_id for line in shipment.lines])
            )
        ).all()
        numbers = dict(rows)  # type: ignore[arg-type]
    return ShipmentOut(
        id=shipment.id,
        number=shipment.number,
        customer_id=shipment.customer_id,
        customer_name=shipment.customer.name,
        status=shipment.status.value,
        carrier=shipment.carrier,
        tracking_reference=shipment.tracking_reference,
        dispatch_date=shipment.dispatch_date,
        expected_delivery_date=shipment.expected_delivery_date,
        actual_delivery_date=shipment.actual_delivery_date,
        days_late=days_late,
        delivered_late=bool(
            shipment.actual_delivery_date is not None and days_late > 0
        ),
        notes=shipment.notes,
        lines=[
            ShipmentLineOut(
                id=line.id,
                sales_order_line_id=line.sales_order_line_id,
                sales_order_number=numbers.get(line.sales_order_line_id),
                quantity=line.quantity,
                unit=line.unit.value,
            )
            for line in shipment.lines
        ],
    )


@router.get("/shipments", response_model=list[ShipmentOut])
def list_shipments(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[ShipmentOut]:
    stmt = select(Shipment).order_by(Shipment.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Shipment.status == ShipmentStatus(status))
    if customer_id:
        stmt = stmt.where(Shipment.customer_id == customer_id)
    return [_shipment_out(session, shipment) for shipment in session.scalars(stmt).all()]


@router.get("/shipments/{shipment_id}", response_model=ShipmentOut)
def get_shipment(
    shipment_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> ShipmentOut:
    shipment = session.get(Shipment, shipment_id)
    if shipment is None:
        raise NotFoundError(f"Shipment {shipment_id} not found.")
    return _shipment_out(session, shipment)


class DispatchRequest(BaseModel):
    dispatch_date: dt.date | None = None
    tracking_reference: str | None = None


@router.post("/shipments/{shipment_id}/dispatch", response_model=ShipmentOut)
def dispatch_shipment(
    shipment_id: uuid.UUID,
    payload: DispatchRequest,
    session: DbSession,
    user: ApproverUser,
) -> ShipmentOut:
    shipment = session.get(Shipment, shipment_id)
    if shipment is None:
        raise NotFoundError(f"Shipment {shipment_id} not found.")
    shipment_service.dispatch(
        session,
        shipment,
        dispatch_date=payload.dispatch_date,
        tracking_reference=payload.tracking_reference,
        user_id=user.id,
        idempotency_key=f"dispatch:{shipment.id}",
    )
    session.commit()
    return _shipment_out(session, shipment)


class DeliveredRequest(BaseModel):
    delivered_on: dt.date | None = None


@router.post("/shipments/{shipment_id}/delivered", response_model=ShipmentOut)
def mark_delivered(
    shipment_id: uuid.UUID,
    payload: DeliveredRequest,
    session: DbSession,
    user: ApproverUser,
) -> ShipmentOut:
    shipment = session.get(Shipment, shipment_id)
    if shipment is None:
        raise NotFoundError(f"Shipment {shipment_id} not found.")
    shipment_service.mark_delivered(
        session, shipment, delivered_on=payload.delivered_on, user_id=user.id
    )
    session.commit()
    return _shipment_out(session, shipment)


# --- Search -------------------------------------------------------------------


class SearchHitOut(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    label: str
    sublabel: str
    href: str
    score: float


@router.get("/search", response_model=list[SearchHitOut])
def search(
    q: str, session: DbSession, _user: CurrentUser, limit: int = Query(20, ge=1, le=50)
) -> list[SearchHitOut]:
    return [
        SearchHitOut(**hit.to_dict()) for hit in search_service.search(session, q, limit=limit)
    ]


# --- Audit --------------------------------------------------------------------


class AuditEventOut(BaseModel):
    id: uuid.UUID
    occurred_at: dt.datetime
    actor_type: str
    actor_user_id: uuid.UUID | None
    actor_label: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    summary: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    exception_id: uuid.UUID | None
    action_proposal_id: uuid.UUID | None
    #: The person's name, when a person did it. Looked up rather than stored,
    #: so the record keeps pointing at the account, not at a copy of a name.
    actor_name: str | None = None


@router.get("/audit", response_model=list[AuditEventOut])
def audit_log(
    session: DbSession,
    _user: CurrentUser,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    actor_type: str | None = None,
    exception_id: uuid.UUID | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit)
    if exception_id:
        # Everything done about one exception: detection, investigation,
        # proposals, approvals and executions all carry its id.
        stmt = stmt.where(AuditEvent.exception_id == exception_id)
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditEvent.action.ilike(f"%{action}%"))
    if actor_type:
        stmt = stmt.where(AuditEvent.actor_type == actor_type)
    events = list(session.scalars(stmt).all())
    user_ids = {event.actor_user_id for event in events if event.actor_user_id}
    names: dict[uuid.UUID, str] = {}
    if user_ids:
        for user_id, full_name in session.execute(
            select(User.id, User.full_name).where(User.id.in_(user_ids))
        ).all():
            names[user_id] = full_name
    return [
        AuditEventOut(
            id=event.id,
            occurred_at=event.occurred_at,
            actor_type=event.actor_type,
            actor_user_id=event.actor_user_id,
            actor_label=event.actor_label,
            action=event.action,
            entity_type=event.entity_type.value,
            entity_id=event.entity_id,
            summary=event.summary,
            before=event.before,
            after=event.after,
            exception_id=event.exception_id,
            action_proposal_id=event.action_proposal_id,
            actor_name=names.get(event.actor_user_id) if event.actor_user_id else None,
        )
        for event in events
    ]


# --- Metrics ------------------------------------------------------------------


@router.get("/metrics/product")
def product_metrics(
    session: DbSession, _user: CurrentUser, window_days: int = Query(30, ge=1, le=365)
) -> dict[str, Any]:
    snapshot = metrics_service.snapshot(session, window_days=window_days)
    return {
        **snapshot.to_dict(),
        "exception_breakdown": metrics_service.exception_breakdown(session),
    }


# --- Simulation ---------------------------------------------------------------


class SimulationRequest(BaseModel):
    event: str
    purchase_order_id: uuid.UUID | None = None
    purchase_order_line_id: uuid.UUID | None = None
    production_batch_id: uuid.UUID | None = None
    shipment_id: uuid.UUID | None = None
    delay_days: int | None = Field(default=None, ge=1, le=90)
    quantity: Decimal | None = None
    partial: bool = False
    kind: str = "shade"


class SimulationResponse(BaseModel):
    event: str
    summary: str
    details: dict[str, Any]
    engine: dict[str, int]


@router.get("/simulation/events")
def simulation_events(_user: CurrentUser) -> dict[str, Any]:
    from textileops.core.config import settings

    return {
        "enabled": settings.simulation_allowed,
        "events": [
            {
                "key": "supplier_delay",
                "label": "Supplier reports a delay",
                "description": (
                    "Creates a real inbound message and runs it through the full ingestion "
                    "pipeline, revising the purchase order ETA with provenance."
                ),
            },
            {
                "key": "inventory_receipt",
                "label": "Goods received",
                "description": "Posts a receipt against an open PO line, in full or short.",
            },
            {
                "key": "qc_rejection",
                "label": "QC rejection",
                "description": (
                    "Fails a batch on shade or GSM, quarantines the stock and schedules "
                    "a replacement batch."
                ),
            },
            {
                "key": "production_completion",
                "label": "Production completed",
                "description": "Runs a batch to completion with wastage, QC pass and release.",
            },
            {
                "key": "shipment_dispatch",
                "label": "Shipment dispatched",
                "description": "Dispatches a planned shipment and draws down finished stock.",
            },
        ],
    }


@router.post("/simulation/run", response_model=SimulationResponse)
def run_simulation(
    payload: SimulationRequest, session: DbSession, _user: ApproverUser
) -> SimulationResponse:
    kwargs: dict[str, Any] = {}
    if payload.event == "supplier_delay":
        kwargs = {
            "purchase_order_id": payload.purchase_order_id,
            "delay_days": payload.delay_days,
        }
    elif payload.event == "inventory_receipt":
        kwargs = {
            "purchase_order_line_id": payload.purchase_order_line_id,
            "quantity": payload.quantity,
            "partial": payload.partial,
        }
    elif payload.event == "qc_rejection":
        kwargs = {"production_batch_id": payload.production_batch_id, "kind": payload.kind}
    elif payload.event == "production_completion":
        kwargs = {"production_batch_id": payload.production_batch_id}
    elif payload.event == "shipment_dispatch":
        kwargs = {"shipment_id": payload.shipment_id}

    result = simulation_service.run(session, payload.event, **kwargs)
    session.commit()
    return SimulationResponse(**result.to_dict())
