"""Customer orders."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from textileops.api.deps import CurrentUser, DbSession
from textileops.core.errors import NotFoundError
from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    OPEN_SALES_ORDER_STATUSES,
    RiskLevel,
    SalesOrderStatus,
)
from textileops.models.exceptions import OperationalException
from textileops.models.sales import SalesOrder
from textileops.schemas.common import TimelineEntry
from textileops.services import orders as order_service

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    fabric_spec_id: uuid.UUID
    fabric_code: str
    fabric_name: str
    quantity: Decimal
    unit: str
    shipped_quantity: Decimal
    produced_quantity: Decimal
    outstanding_quantity: Decimal
    stock_available: Decimal
    to_produce: Decimal
    estimated_ready_date: dt.date | None
    promised_date: dt.date
    unit_price: Decimal | None
    outstanding_value: Decimal | None
    blocked_batch_codes: list[str]
    batch_ids: list[uuid.UUID]


class OrderItemOut(BaseModel):
    """One line, reduced to what a list row can show."""

    fabric_code: str
    fabric_name: str
    quantity: Decimal
    outstanding_quantity: Decimal
    unit: str


class OrderSummaryOut(BaseModel):
    id: uuid.UUID
    number: str
    customer_id: uuid.UUID
    customer_name: str
    status: str
    order_date: dt.date
    promised_date: dt.date
    risk: str
    estimated_completion: dt.date | None
    days_ahead: int | None
    #: Why there is no estimated completion, when there is none. None means
    #: the order is finished — which is a very different thing from "nothing
    #: is planned", and the screen was showing the same sentence for both.
    completion_unknown_reason: str | None
    material_readiness: str
    production_status: str
    qc_status: str
    shipment_status: str
    outstanding_value: Decimal | None
    value_basis: str
    currency: str
    open_exception_count: int
    items: list[OrderItemOut] = []
    #: The first thing in the way, in words, or None when nothing the system can
    #: name is. See `orders.next_blocker`.
    next_blocker: str | None = None


class OrderDetailOut(OrderSummaryOut):
    lines: list[OrderLineOut]
    blocked_reasons: list[str]
    notes: str | None
    customer_reference: str | None
    open_exception_ids: list[uuid.UUID]


class OrderListOut(BaseModel):
    items: list[OrderSummaryOut]
    total: int
    counts_by_risk: dict[str, int]


def _summary(assessment: order_service.OrderAssessment, exception_count: int) -> OrderSummaryOut:
    return OrderSummaryOut(
        id=assessment.order_id,
        number=assessment.number,
        customer_id=assessment.customer_id,
        customer_name=assessment.customer_name,
        status=assessment.status.value,
        order_date=assessment.order_date,
        promised_date=assessment.promised_date,
        risk=assessment.risk.value,
        estimated_completion=assessment.estimated_completion,
        days_ahead=assessment.days_ahead,
        completion_unknown_reason=assessment.completion_unknown_reason,
        material_readiness=assessment.material_readiness,
        production_status=assessment.production_status,
        qc_status=assessment.qc_status,
        shipment_status=assessment.shipment_status,
        outstanding_value=assessment.outstanding_value,
        value_basis=assessment.value_basis,
        currency=assessment.currency,
        open_exception_count=exception_count,
        items=[
            OrderItemOut(
                fabric_code=line.fabric_code,
                fabric_name=line.fabric_name,
                quantity=line.quantity,
                outstanding_quantity=line.outstanding_quantity,
                unit=line.unit.value,
            )
            for line in assessment.lines
        ],
        next_blocker=order_service.next_blocker(assessment),
    )


def _exception_counts(session: DbSession, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not order_ids:
        return {}
    rows = session.execute(
        select(OperationalException.sales_order_id, func.count(OperationalException.id))
        .where(
            OperationalException.sales_order_id.in_(order_ids),
            OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES),
        )
        .group_by(OperationalException.sales_order_id)
    ).all()
    return {order_id: count for order_id, count in rows if order_id is not None}


@router.get("", response_model=OrderListOut)
def list_orders(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    risk: str | None = None,
    customer_id: uuid.UUID | None = None,
    search: str | None = None,
    include_closed: bool = False,
    limit: int = Query(100, ge=1, le=500),
) -> OrderListOut:
    stmt = select(SalesOrder).order_by(SalesOrder.promised_date)
    if status:
        stmt = stmt.where(SalesOrder.status == SalesOrderStatus(status))
    elif not include_closed:
        # "Open" means there is still something to do: drafts, delivered and
        # closed orders are history, and listing them under a cleared
        # "include closed and delivered" box would be a lie.
        stmt = stmt.where(SalesOrder.status.in_(OPEN_SALES_ORDER_STATUSES))
    if customer_id:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if search:
        stmt = stmt.where(SalesOrder.number.ilike(f"%{search}%"))

    found = list(session.scalars(stmt.limit(limit)).all())
    counts = _exception_counts(session, [order.id for order in found])
    assessments = [order_service.assess_order(session, order) for order in found]
    if risk:
        wanted = RiskLevel(risk)
        assessments = [a for a in assessments if a.risk == wanted]

    by_risk: dict[str, int] = {level.value: 0 for level in RiskLevel}
    for assessment in assessments:
        by_risk[assessment.risk.value] += 1

    return OrderListOut(
        items=[_summary(a, counts.get(a.order_id, 0)) for a in assessments],
        total=len(assessments),
        counts_by_risk=by_risk,
    )


@router.get("/{order_id}", response_model=OrderDetailOut)
def get_order(order_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> OrderDetailOut:
    order = session.get(SalesOrder, order_id)
    if order is None:
        raise NotFoundError(f"Order {order_id} not found.")
    assessment = order_service.assess_order(session, order)
    exception_ids = list(
        session.scalars(
            select(OperationalException.id).where(
                OperationalException.sales_order_id == order.id,
                OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES),
            )
        ).all()
    )
    base = _summary(assessment, len(exception_ids))
    return OrderDetailOut(
        **base.model_dump(),
        lines=[
            OrderLineOut(
                id=line.line_id,
                line_no=line.line_no,
                fabric_spec_id=line.fabric_spec_id,
                fabric_code=line.fabric_code,
                fabric_name=line.fabric_name,
                quantity=line.quantity,
                unit=line.unit.value,
                shipped_quantity=line.shipped_quantity,
                produced_quantity=line.produced_quantity,
                outstanding_quantity=line.outstanding_quantity,
                stock_available=line.stock_available,
                to_produce=line.to_produce,
                estimated_ready_date=line.estimated_ready_date,
                promised_date=line.promised_date,
                unit_price=line.unit_price,
                outstanding_value=line.outstanding_value,
                blocked_batch_codes=line.blocked_batch_codes,
                batch_ids=line.batch_ids,
            )
            for line in assessment.lines
        ],
        blocked_reasons=assessment.blocked_reasons,
        notes=order.notes,
        customer_reference=order.customer_reference,
        open_exception_ids=exception_ids,
    )


@router.get("/{order_id}/timeline", response_model=list[TimelineEntry])
def order_timeline(
    order_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> list[TimelineEntry]:
    order = session.get(SalesOrder, order_id)
    if order is None:
        raise NotFoundError(f"Order {order_id} not found.")
    return [
        TimelineEntry(
            at=event.at,
            kind=event.kind,
            title=event.title,
            detail=event.detail,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
        )
        for event in order_service.order_timeline(session, order)
    ]
