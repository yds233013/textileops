"""Suppliers and purchase orders."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from textileops.api.deps import ApproverUser, CurrentUser, DbSession
from textileops.core.errors import NotFoundError
from textileops.core.units import parse_unit
from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    OPEN_PO_STATUSES,
    PurchaseOrderStatus,
)
from textileops.models.exceptions import OperationalException
from textileops.models.intake import Message
from textileops.models.org import Supplier
from textileops.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
)
from textileops.services import clock
from textileops.services import procurement as procurement_service
from textileops.workers.queue import enqueue_debounced

router = APIRouter(tags=["procurement"])


class SupplierOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    country: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    currency: str
    default_lead_time_days: int
    on_time_rate: Decimal | None
    is_active: bool
    open_po_count: int
    late_po_count: int
    open_exception_count: int


class POLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    material_id: uuid.UUID
    material_code: str
    material_name: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    rejected_quantity: Decimal
    outstanding_quantity: Decimal
    unit: str
    unit_price: Decimal | None
    expected_date: dt.date | None
    receipts: list[ReceiptOut]


class ReceiptOut(BaseModel):
    id: uuid.UUID
    received_at: dt.datetime
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    unit: str
    supplier_document_ref: str | None
    note: str | None


class ETAProvenanceOut(BaseModel):
    """Why we believe the current date — the answer to 'says who?'."""

    current_expected_date: dt.date
    original_expected_date: dt.date
    is_revised: bool
    reason: str | None
    updated_at: dt.datetime | None
    source_message_id: uuid.UUID | None
    source_message_excerpt: str | None
    source_document_id: uuid.UUID | None


class POItemOut(BaseModel):
    material_name: str
    ordered_quantity: Decimal
    received_quantity: Decimal
    unit: str


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    number: str
    supplier_id: uuid.UUID
    supplier_name: str
    status: str
    order_date: dt.date
    expected_date: dt.date
    revised_expected_date: dt.date | None
    current_expected_date: dt.date
    days_late: int
    currency: str
    notes: str | None
    total_ordered_lines: int
    is_partially_received: bool
    #: What is on order and what has arrived, per line, so the list can show
    #: it without opening every PO. Quantities in each line's own unit.
    items: list[POItemOut] = []


class PurchaseOrderDetailOut(PurchaseOrderOut):
    lines: list[POLineOut]
    eta_provenance: ETAProvenanceOut
    open_exception_ids: list[uuid.UUID]


def _po_out(po: PurchaseOrder) -> PurchaseOrderOut:
    today = clock.today()
    days_late = (
        (today - po.current_expected_date).days
        if po.status in OPEN_PO_STATUSES and po.current_expected_date < today
        else 0
    )
    return PurchaseOrderOut(
        id=po.id,
        number=po.number,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier.name,
        status=po.status.value,
        order_date=po.order_date,
        expected_date=po.expected_date,
        revised_expected_date=po.revised_expected_date,
        current_expected_date=po.current_expected_date,
        days_late=max(0, days_late),
        currency=po.currency.value,
        notes=po.notes,
        total_ordered_lines=len(po.lines),
        is_partially_received=any(
            0 < line.received_quantity < line.ordered_quantity for line in po.lines
        ),
        items=[
            POItemOut(
                material_name=line.material.name,
                ordered_quantity=line.ordered_quantity,
                received_quantity=line.received_quantity,
                unit=line.unit.value,
            )
            for line in sorted(po.lines, key=lambda line: line.line_no)
        ],
    )


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    session: DbSession, _user: CurrentUser, search: str | None = None
) -> list[SupplierOut]:
    stmt = select(Supplier).order_by(Supplier.name)
    if search:
        stmt = stmt.where(Supplier.name.ilike(f"%{search}%"))
    suppliers = list(session.scalars(stmt).all())
    today = clock.today()
    out: list[SupplierOut] = []
    for supplier in suppliers:
        open_pos = [po for po in supplier.purchase_orders if po.status in OPEN_PO_STATUSES]
        late = [po for po in open_pos if po.current_expected_date < today]
        exception_count = (
            session.scalar(
                select(func.count(OperationalException.id)).where(
                    OperationalException.supplier_id == supplier.id,
                    OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES),
                )
            )
            or 0
        )
        out.append(
            SupplierOut(
                id=supplier.id,
                code=supplier.code,
                name=supplier.name,
                country=supplier.country,
                contact_name=supplier.contact_name,
                contact_email=supplier.contact_email,
                contact_phone=supplier.contact_phone,
                currency=supplier.currency.value,
                default_lead_time_days=supplier.default_lead_time_days,
                on_time_rate=supplier.on_time_rate,
                is_active=supplier.is_active,
                open_po_count=len(open_pos),
                late_po_count=len(late),
                open_exception_count=int(exception_count),
            )
        )
    return out


class SupplierDetailOut(BaseModel):
    supplier: SupplierOut
    purchase_orders: list[PurchaseOrderOut]
    recent_messages: list[SupplierMessageOut]


class SupplierMessageOut(BaseModel):
    id: uuid.UUID
    received_at: dt.datetime
    sender: str
    subject: str | None
    intent: str
    body: str
    is_duplicate: bool


@router.get("/suppliers/{supplier_id}", response_model=SupplierDetailOut)
def get_supplier(
    supplier_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> SupplierDetailOut:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError(f"Supplier {supplier_id} not found.")
    summary = next(s for s in list_suppliers(session, user) if s.id == supplier_id)
    messages = session.scalars(
        select(Message)
        .where(Message.supplier_id == supplier_id)
        .order_by(Message.received_at.desc())
        .limit(20)
    ).all()
    return SupplierDetailOut(
        supplier=summary,
        purchase_orders=[_po_out(po) for po in supplier.purchase_orders],
        recent_messages=[
            SupplierMessageOut(
                id=message.id,
                received_at=message.received_at,
                sender=message.sender,
                subject=message.subject,
                intent=message.intent.value,
                body=message.body,
                is_duplicate=message.duplicate_of_id is not None,
            )
            for message in messages
        ],
    )


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    supplier_id: uuid.UUID | None = None,
    late_only: bool = False,
    search: str | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[PurchaseOrderOut]:
    # Open orders first — ten closed POs from June used to head the list —
    # then by the date we currently expect them, soonest first.
    is_open = PurchaseOrder.status.in_(OPEN_PO_STATUSES)
    stmt = select(PurchaseOrder).order_by(is_open.desc(), PurchaseOrder.expected_date)
    if status:
        stmt = stmt.where(PurchaseOrder.status == PurchaseOrderStatus(status))
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if search:
        stmt = stmt.where(PurchaseOrder.number.ilike(f"%{search}%"))
    items = [_po_out(po) for po in session.scalars(stmt.limit(limit)).all()]
    if late_only:
        items = [item for item in items if item.days_late > 0]
    return items


@router.get("/purchase-orders/{po_id}", response_model=PurchaseOrderDetailOut)
def get_purchase_order(
    po_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> PurchaseOrderDetailOut:
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found.")
    message = (
        session.get(Message, po.eta_source_message_id) if po.eta_source_message_id else None
    )
    exception_ids = list(
        session.scalars(
            select(OperationalException.id).where(
                OperationalException.purchase_order_id == po.id,
                OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES),
            )
        ).all()
    )
    return PurchaseOrderDetailOut(
        **_po_out(po).model_dump(),
        lines=[
            POLineOut(
                id=line.id,
                line_no=line.line_no,
                material_id=line.material_id,
                material_code=line.material.code,
                material_name=line.material.name,
                ordered_quantity=line.ordered_quantity,
                received_quantity=line.received_quantity,
                rejected_quantity=line.rejected_quantity,
                outstanding_quantity=line.outstanding_quantity,
                unit=line.unit.value,
                unit_price=line.unit_price,
                expected_date=line.expected_date,
                receipts=[
                    ReceiptOut(
                        id=receipt.id,
                        received_at=receipt.received_at,
                        accepted_quantity=receipt.accepted_quantity,
                        rejected_quantity=receipt.rejected_quantity,
                        unit=receipt.unit.value,
                        supplier_document_ref=receipt.supplier_document_ref,
                        note=receipt.note,
                    )
                    for receipt in sorted(line.receipts, key=lambda r: r.received_at)
                ],
            )
            for line in sorted(po.lines, key=lambda line_: line_.line_no)
        ],
        eta_provenance=ETAProvenanceOut(
            current_expected_date=po.current_expected_date,
            original_expected_date=po.expected_date,
            is_revised=po.revised_expected_date is not None,
            reason=po.eta_note,
            updated_at=po.eta_updated_at,
            source_message_id=po.eta_source_message_id,
            source_message_excerpt=message.body[:800] if message else None,
            source_document_id=po.eta_source_document_id,
        ),
        open_exception_ids=exception_ids,
    )


class ReceiveRequest(BaseModel):
    purchase_order_line_id: uuid.UUID
    accepted_quantity: Decimal = Field(gt=0)
    unit: str
    rejected_quantity: Decimal = Field(default=Decimal("0"), ge=0)
    supplier_document_ref: str | None = None
    note: str | None = None
    #: Send a stable value (the client generates one per receipt) so that a
    #: double-submitted form or a retried request cannot post the goods twice.
    idempotency_key: str | None = Field(default=None, max_length=128)


class ReceiveResponse(BaseModel):
    lot_code: str | None
    received_to_date: Decimal
    outstanding: Decimal
    unit: str
    purchase_order_status: str
    over_received_by: Decimal
    #: True when this request matched an earlier one and changed nothing.
    was_replay: bool = False


@router.post("/purchase-orders/receipts", response_model=ReceiveResponse)
def post_receipt(
    payload: ReceiveRequest, session: DbSession, user: ApproverUser
) -> ReceiveResponse:
    line = session.get(PurchaseOrderLine, payload.purchase_order_line_id)
    if line is None:
        raise NotFoundError(f"Purchase order line {payload.purchase_order_line_id} not found.")
    # Without a key from the caller, derive one from what makes this receipt
    # unique. It will not catch two genuinely identical deliveries recorded
    # deliberately, but it does stop a double-submitted form posting the goods
    # twice — which is the failure that actually happens.
    key = payload.idempotency_key or (
        f"receipt:{payload.purchase_order_line_id}:{payload.supplier_document_ref}"
        if payload.supplier_document_ref
        else None
    )
    outcome = procurement_service.receive(
        session,
        line,
        accepted_quantity=payload.accepted_quantity,
        rejected_quantity=payload.rejected_quantity,
        unit=parse_unit(payload.unit),
        supplier_document_ref=payload.supplier_document_ref,
        note=payload.note,
        user_id=user.id,
        idempotency_key=key,
    )
    session.commit()
    return ReceiveResponse(
        lot_code=outcome.lot_code,
        received_to_date=line.received_quantity,
        outstanding=line.outstanding_quantity,
        unit=line.unit.value,
        purchase_order_status=outcome.purchase_order_status.value,
        over_received_by=outcome.over_received_by,
        was_replay=outcome.was_replay,
    )


class ReceiptCorrectionRequest(BaseModel):
    """Reduce a posted receipt by what did not actually arrive.

    There is deliberately no field for increasing a receipt. If more arrived
    than was keyed, the extra physically turned up and is recorded by posting
    another receipt — which is both what happened and what keeps a correction
    from ever being able to create stock.
    """

    receipt_id: uuid.UUID
    accepted_delta: Decimal = Field(default=Decimal("0"), ge=0)
    rejected_delta: Decimal = Field(default=Decimal("0"), ge=0)
    unit: str | None = None
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ReceiptCorrectionResponse(BaseModel):
    receipt_id: uuid.UUID
    original_accepted: Decimal
    corrected_accepted: Decimal
    stock_removed: Decimal
    received_to_date: Decimal
    outstanding: Decimal
    unit: str
    purchase_order_status: str
    was_replay: bool = False


@router.post(
    "/purchase-orders/receipts/corrections", response_model=ReceiptCorrectionResponse
)
def post_receipt_correction(
    payload: ReceiptCorrectionRequest, session: DbSession, user: ApproverUser
) -> ReceiptCorrectionResponse:
    receipt = session.get(PurchaseOrderReceipt, payload.receipt_id)
    if receipt is None:
        raise NotFoundError(f"Receipt {payload.receipt_id} not found.")
    outcome = procurement_service.correct_receipt(
        session,
        receipt,
        accepted_delta=payload.accepted_delta,
        rejected_delta=payload.rejected_delta,
        unit=parse_unit(payload.unit) if payload.unit else None,
        reason=payload.reason,
        user_id=user.id,
        idempotency_key=payload.idempotency_key,
    )
    # Stock and outstanding supply both moved, so what was true about coverage
    # and order risk a moment ago may not be any more. Recomputed out of band
    # rather than inline: the operator's correction should not fail because a
    # sweep did.
    enqueue_debounced(session, "recompute_exceptions", {})
    session.commit()
    return ReceiptCorrectionResponse(
        receipt_id=receipt.id,
        original_accepted=receipt.accepted_quantity,
        corrected_accepted=receipt.corrected_accepted_quantity,
        stock_removed=outcome.stock_removed,
        received_to_date=outcome.line_received_quantity,
        outstanding=outcome.line_outstanding_quantity,
        unit=receipt.unit.value,
        purchase_order_status=outcome.purchase_order_status.value,
        was_replay=outcome.was_replay,
    )
