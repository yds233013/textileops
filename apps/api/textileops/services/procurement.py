"""Purchase orders: receipts, ETA revisions and supplier performance.

Two rules matter most here and are enforced by the code, not by convention:

1. **Ordered quantity is not received quantity.** A receipt never overwrites
   the order; it accumulates against it, and over-receipt is surfaced as a
   quantity mismatch rather than silently accepted.
2. **Every ETA change carries provenance.** Changing what we believe about a
   delivery date always records *which message or document* said so.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from textileops.core.db import lock_row
from textileops.core.errors import ConflictError, ValidationError
from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.enums import (
    OPEN_PO_STATUSES,
    EntityType,
    LotStatus,
    MovementType,
    PurchaseOrderStatus,
)
from textileops.models.inventory import InventoryLot
from textileops.models.org import Supplier
from textileops.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptCorrection,
)
from textileops.services import clock, inventory, prose
from textileops.services.audit import record_audit

ZERO = Decimal("0")
#: Receiving more than ordered by up to this fraction is treated as normal
#: trade tolerance; beyond it we raise a quantity mismatch.
OVER_RECEIPT_TOLERANCE = Decimal("0.02")


@dataclass
class ReceiptOutcome:
    receipt: PurchaseOrderReceipt
    lot_code: str | None
    line_fully_received: bool
    over_received_by: Decimal
    purchase_order_status: PurchaseOrderStatus
    #: True when this call matched an earlier receipt and changed nothing.
    was_replay: bool = False


def revise_eta(
    session: Session,
    purchase_order: PurchaseOrder,
    *,
    new_date: dt.date,
    reason: str,
    message_id: uuid.UUID | None = None,
    source_document_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    actor_type: str = "system",
) -> PurchaseOrder:
    """Record a new believed arrival date, with the evidence for it.

    This is what makes the question *"why do we believe PO-2231 arrives on the
    12th?"* answerable: the answer is stored next to the belief.
    """
    if message_id is None and source_document_id is None and user_id is None:
        raise ValidationError(
            "An ETA revision must cite a message, a document or the person making it."
        )
    previous = purchase_order.current_expected_date
    before = {
        "revised_expected_date": purchase_order.revised_expected_date,
        "expected_date": purchase_order.expected_date,
    }
    purchase_order.revised_expected_date = new_date
    purchase_order.eta_source_message_id = message_id
    purchase_order.eta_source_document_id = source_document_id
    purchase_order.eta_updated_at = clock.now()
    purchase_order.eta_note = reason

    record_audit(
        session,
        action="purchase_order.eta_revised",
        entity_type=EntityType.PURCHASE_ORDER,
        entity_id=purchase_order.id,
        summary=(
            f"{purchase_order.number} now expected {new_date.isoformat()} "
            f"(was {previous.isoformat()}): {reason}"
        ),
        actor_type=actor_type,
        actor_user_id=user_id,
        before=before,
        after={"revised_expected_date": new_date, "reason": reason},
        source_document_id=source_document_id,
    )
    return purchase_order


def receive(
    session: Session,
    line: PurchaseOrderLine,
    *,
    accepted_quantity: Decimal,
    unit: UnitOfMeasure | None = None,
    rejected_quantity: Decimal = ZERO,
    received_at: dt.datetime | None = None,
    lot_code: str | None = None,
    supplier_document_ref: str | None = None,
    unit_price: Decimal | None = None,
    source_document_id: uuid.UUID | None = None,
    note: str | None = None,
    user_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> ReceiptOutcome:
    """Post a (possibly partial) goods receipt and bring the stock on hand."""
    unit = unit or line.unit
    accepted = convert(Decimal(str(accepted_quantity)), unit, line.unit)
    rejected = convert(Decimal(str(rejected_quantity)), unit, line.unit)
    if accepted < ZERO or rejected < ZERO:
        raise ValidationError("Receipt quantities cannot be negative.")
    if accepted + rejected <= ZERO:
        raise ValidationError("A receipt must record some quantity.")

    # Parent first, then the line, then the lot — the same order everywhere
    # that touches them. `_refresh_po_status` reads *every* line of the order,
    # so locking only the line being written let two concurrent receipts on
    # different lines each see the other as stale: both wrote
    # PARTIALLY_RECEIVED, and a fully received order stayed "partially" for
    # ever, keeping it in the open-purchase-order list with no way back.
    lock_row(session, line.purchase_order)

    # Serialise receipts against this line. ``received_quantity`` is
    # accumulated read-modify-write and ``_next_lot_code`` is a count(*) + 1,
    # so two deliveries keyed in at the same moment either both compute the
    # same lot code (one insert dies on the unique index and a whole delivery
    # is lost) or both write the same total (the line claims 500 kg received
    # when 1000 kg is physically in the warehouse, and the phantom 500 kg of
    # outstanding supply never clears). Locking the line first makes both
    # sequences well defined.
    lock_row(session, line)

    if idempotency_key:
        existing = session.scalar(
            select(PurchaseOrderReceipt).where(
                PurchaseOrderReceipt.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            # A replay: return what the first call produced, change nothing.
            po = line.purchase_order
            return ReceiptOutcome(
                receipt=existing,
                lot_code=None,
                line_fully_received=line.outstanding_quantity <= ZERO,
                over_received_by=ZERO,
                purchase_order_status=po.status,
                was_replay=True,
            )

    occurred = received_at or clock.now()
    receipt = PurchaseOrderReceipt(
        purchase_order_line_id=line.id,
        received_at=occurred,
        accepted_quantity=accepted,
        rejected_quantity=rejected,
        unit=line.unit,
        supplier_document_ref=supplier_document_ref,
        idempotency_key=idempotency_key,
        unit_price=unit_price,
        source_document_id=source_document_id,
        note=note,
    )
    session.add(receipt)
    # Keep the in-session collection consistent: anything that reads
    # ``line.receipts`` in the same transaction — the on-time calculation, for
    # one — must see this receipt.
    line.receipts.append(receipt)

    line.received_quantity = quantize(line.received_quantity + accepted)
    line.rejected_quantity = quantize(line.rejected_quantity + rejected)

    lot = None
    if accepted > ZERO:
        po = line.purchase_order
        lot = inventory.create_lot(
            session,
            lot_code=lot_code or _next_lot_code(session, line),
            material_id=line.material_id,
            quantity=accepted,
            unit=line.unit,
            received_at=occurred,
            status=LotStatus.AVAILABLE,
            supplier_id=po.supplier_id,
            purchase_order_line_id=line.id,
            unit_cost=unit_price or line.unit_price,
            currency=po.currency if (unit_price or line.unit_price) else None,
            notes=f"Receipt against {po.number} line {line.line_no}.",
            movement_type=MovementType.RECEIPT,
            reference_type=EntityType.PURCHASE_ORDER_LINE,
            reference_id=line.id,
            source_document_id=source_document_id,
            idempotency_key=(f"po-receipt:{idempotency_key}" if idempotency_key else None),
            movement_note=f"Goods receipt against {po.number}.",
        )
        session.flush()
        receipt.inventory_lot_id = lot.id

    over_received = quantize(
        max(ZERO, line.received_quantity - line.ordered_quantity)
    )
    status = _refresh_po_status(session, line.purchase_order)
    # The supplier's on-time rate is a measurement, so it is re-derived from
    # actual receipt dates every time one arrives — never set by hand.
    recompute_supplier_on_time_rate(session, line.purchase_order.supplier)

    record_audit(
        session,
        action="purchase_order.received",
        entity_type=EntityType.PURCHASE_ORDER_LINE,
        entity_id=line.id,
        summary=(
            f"Received {prose.qty(accepted, line.unit)} against "
            f"{line.purchase_order.number} line {line.line_no} "
            f"({prose.num(line.received_quantity)} of "
            f"{prose.qty(line.ordered_quantity, line.unit)} to date)."
        ),
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
        after={
            "accepted": accepted,
            "rejected": rejected,
            "received_to_date": line.received_quantity,
            "ordered": line.ordered_quantity,
        },
        source_document_id=source_document_id,
    )
    session.flush()
    return ReceiptOutcome(
        receipt=receipt,
        lot_code=lot.lot_code if lot else None,
        line_fully_received=line.outstanding_quantity <= ZERO,
        over_received_by=over_received,
        purchase_order_status=status,
    )


def _next_lot_code(session: Session, line: PurchaseOrderLine) -> str:
    """Sequential lot code per PO line, counting receipts already posted."""
    posted = session.scalar(
        select(func.count(PurchaseOrderReceipt.id)).where(
            PurchaseOrderReceipt.purchase_order_line_id == line.id
        )
    )
    return f"LOT-{line.purchase_order.number}-{line.line_no}-{int(posted or 0) + 1}"


#: Statuses that are a claim about goods having arrived, as opposed to a
#: lifecycle state somebody set. Only these may be derived — and, because they
#: are derived, only these may be taken back.
_RECEIPT_CLAIM_STATUSES = (
    PurchaseOrderStatus.PARTIALLY_RECEIVED,
    PurchaseOrderStatus.RECEIVED,
)


def _refresh_po_status(session: Session, po: PurchaseOrder) -> PurchaseOrderStatus:
    """Derive PO status from its lines. Never set by hand during receiving.

    This used to be a ratchet: it could advance to PARTIALLY_RECEIVED or
    RECEIVED and never come back. That was safe only while received quantities
    could not fall. Corrections make them fall, so an order whose only receipt
    was reversed would otherwise sit there saying RECEIVED with nothing in the
    warehouse — the strongest claim the field can make, made about nothing.

    Falling back is deliberately limited to the two statuses this function
    owns. DRAFT and SENT are things a person did, not conclusions from the
    ledger, so a reversal returns the order to ACKNOWLEDGED — the goods were
    ordered and the supplier knew about it, which is all that is still true.
    """
    if po.status in (PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.CLOSED):
        return po.status
    totals = [(line.received_quantity, line.ordered_quantity) for line in po.lines]
    if not totals:
        return po.status
    if all(received >= ordered for received, ordered in totals):
        po.status = PurchaseOrderStatus.RECEIVED
    elif any(received > ZERO for received, _ in totals):
        po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED
    elif po.status in _RECEIPT_CLAIM_STATUSES:
        po.status = PurchaseOrderStatus.ACKNOWLEDGED
    return po.status


def open_purchase_orders(session: Session) -> list[PurchaseOrder]:
    return list(
        session.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
            .order_by(PurchaseOrder.expected_date)
        ).all()
    )


@dataclass
class POStatusLine:
    purchase_order: PurchaseOrder
    days_late: int
    outstanding_by_material: dict[str, tuple[Decimal, UnitOfMeasure]]
    has_partial_receipt: bool


def late_purchase_orders(session: Session, *, as_of: dt.date | None = None) -> list[POStatusLine]:
    """Open POs whose currently-believed arrival date has already passed."""
    as_of = as_of or clock.today()
    out: list[POStatusLine] = []
    for po in open_purchase_orders(session):
        expected = po.current_expected_date
        if expected >= as_of:
            continue
        outstanding: dict[str, tuple[Decimal, UnitOfMeasure]] = {}
        partial = False
        for line in po.lines:
            if line.outstanding_quantity > ZERO:
                outstanding[line.material.code] = (line.outstanding_quantity, line.unit)
            if ZERO < line.received_quantity < line.ordered_quantity:
                partial = True
        if not outstanding:
            continue
        out.append(
            POStatusLine(
                purchase_order=po,
                days_late=(as_of - expected).days,
                outstanding_by_material=outstanding,
                has_partial_receipt=partial,
            )
        )
    return out


def recompute_supplier_on_time_rate(
    session: Session, supplier: Supplier, *, as_of: dt.date | None = None
) -> Decimal | None:
    """On-time delivery rate, measured **per purchase-order line**.

    Two things this deliberately gets right:

    * The population is order lines, not receipts. Counting receipts would let
      a supplier who split one late line into five partial deliveries score
      5/5, and would let a supplier who has simply never delivered score 100%.
    * A line that is past its promised date with nothing received counts as a
      miss. Silence is the most common way a supplier is late.

    Measured against the **originally agreed** date, not a revised one — a
    supplier does not improve their record by telling you later.

    Returns ``None`` when there is nothing to measure: an unmeasured supplier
    is not a perfect supplier.
    """
    as_of = as_of or clock.today()
    rows = session.execute(
        select(PurchaseOrderLine, PurchaseOrder)
        .join(PurchaseOrder, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.supplier_id == supplier.id,
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
        )
    ).all()

    assessed = 0
    on_time = 0
    for line, po in rows:
        promised = line.expected_date or po.expected_date
        receipts = sorted(line.receipts, key=lambda receipt: receipt.received_at)
        if not receipts:
            if promised < as_of:
                # Promised, past due, nothing arrived: a miss.
                assessed += 1
            continue
        assessed += 1
        # Judged on when the line was *completed*, not when the first box came.
        if line.received_quantity >= line.ordered_quantity:
            completed_at = receipts[-1].received_at.date()
            if completed_at <= promised:
                on_time += 1
        elif promised >= as_of:
            # Partly delivered but not yet due — not a miss yet.
            assessed -= 1

    if assessed == 0:
        supplier.on_time_rate = None
        return None
    rate = (Decimal(on_time) / Decimal(assessed)).quantize(Decimal("0.0001"))
    supplier.on_time_rate = rate
    return rate


def recompute_all_supplier_rates(session: Session) -> int:
    """Re-score every supplier. Returns how many rates changed.

    ``recompute_supplier_on_time_rate`` was only ever called from ``receive``,
    which means a supplier's score could only move when they *delivered*. The
    commonest way to be late is to send nothing at all, and that path updated
    no score: a supplier whose promised date quietly passed kept whatever
    rating their last delivery earned them, and the procurement screen went on
    recommending them.
    """
    changed = 0
    for supplier in session.scalars(select(Supplier)).all():
        before = supplier.on_time_rate
        after = recompute_supplier_on_time_rate(session, supplier)
        if before != after:
            changed += 1
    return changed


@dataclass
class CorrectionOutcome:
    """What a correction did, in terms an operator can check against paperwork."""

    correction: PurchaseOrderReceiptCorrection
    receipt: PurchaseOrderReceipt
    stock_removed: Decimal
    line_received_quantity: Decimal
    line_outstanding_quantity: Decimal
    purchase_order_status: PurchaseOrderStatus
    was_replay: bool = False


def correct_receipt(
    session: Session,
    receipt: PurchaseOrderReceipt,
    *,
    accepted_delta: Decimal = ZERO,
    rejected_delta: Decimal = ZERO,
    reason: str,
    user_id: uuid.UUID | None = None,
    unit: UnitOfMeasure | None = None,
    corrected_at: dt.datetime | None = None,
    source_document_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> CorrectionOutcome:
    """Reduce a posted receipt by what did not actually arrive.

    The receipt itself is never touched. What this writes is a correction row
    against it plus, when stock had been brought in, the movement that takes
    that stock back out — so the ledger still explains every kilogram it ever
    claimed to hold.

    Refused when the lot no longer holds the stock the correction would remove.
    That is not a rounding problem: if 1,000 kg was received and 950 consumed,
    correcting to 900 would mean 50 kg of the *consumption* also did not
    happen, and only a person can say which of the two records is wrong.

    Locks the PO line before the lot, matching ``receive``, so a correction
    and a delivery racing on the same line queue rather than deadlock.
    """
    unit = unit or receipt.unit
    accepted_drop = convert(Decimal(str(accepted_delta)), unit, receipt.unit)
    rejected_drop = convert(Decimal(str(rejected_delta)), unit, receipt.unit)
    if accepted_drop < ZERO or rejected_drop < ZERO:
        raise ValidationError(
            "A correction is expressed as the quantity that did not arrive, so "
            "it cannot be negative. To record that more arrived than was keyed, "
            "post another receipt — the extra goods physically turned up."
        )
    if accepted_drop + rejected_drop <= ZERO:
        raise ValidationError("A correction must change some quantity.")
    if not reason or not reason.strip():
        raise ValidationError(
            "A correction needs a reason. A quantity that moved with no stated "
            "cause is the first thing anyone auditing this will ask about."
        )

    if idempotency_key:
        existing = session.scalar(
            select(PurchaseOrderReceiptCorrection).where(
                PurchaseOrderReceiptCorrection.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            line = existing.receipt.purchase_order_line
            return CorrectionOutcome(
                correction=existing,
                receipt=existing.receipt,
                stock_removed=ZERO,
                line_received_quantity=line.received_quantity,
                line_outstanding_quantity=line.outstanding_quantity,
                purchase_order_status=line.purchase_order.status,
                was_replay=True,
            )

    line = receipt.purchase_order_line
    lock_row(session, line.purchase_order)
    lock_row(session, line)
    session.refresh(receipt)

    already_accepted = sum(
        (c.accepted_delta for c in receipt.corrections), ZERO
    )
    already_rejected = sum(
        (c.rejected_delta for c in receipt.corrections), ZERO
    )
    if quantize(already_accepted + accepted_drop) > receipt.accepted_quantity:
        raise ConflictError(
            f"This receipt recorded {receipt.accepted_quantity} {receipt.unit.value} "
            f"accepted and {quantize(already_accepted)} has already been corrected "
            f"away; {accepted_drop} more would take it below zero.",
            details={
                "receipt_id": str(receipt.id),
                "accepted_quantity": str(receipt.accepted_quantity),
                "already_corrected": str(quantize(already_accepted)),
                "requested": str(accepted_drop),
            },
        )
    if quantize(already_rejected + rejected_drop) > receipt.rejected_quantity:
        raise ConflictError(
            f"This receipt recorded {receipt.rejected_quantity} {receipt.unit.value} "
            f"rejected and {quantize(already_rejected)} has already been corrected "
            "away; the remainder is smaller than this correction.",
            details={
                "receipt_id": str(receipt.id),
                "rejected_quantity": str(receipt.rejected_quantity),
                "already_corrected": str(quantize(already_rejected)),
                "requested": str(rejected_drop),
            },
        )

    occurred = corrected_at or clock.now()
    movement = None
    stock_removed = ZERO

    if accepted_drop > ZERO:
        lot = (
            session.get(InventoryLot, receipt.inventory_lot_id)
            if receipt.inventory_lot_id
            else None
        )
        if lot is None:
            raise ConflictError(
                "This receipt has no stock lot recorded against it, so there is "
                "nothing to take back out. Raise an inventory adjustment instead, "
                "which records that the stock itself is in question.",
                details={"receipt_id": str(receipt.id)},
            )
        lock_row(session, lot)
        removable = convert(lot.quantity_on_hand, lot.unit, receipt.unit)
        if removable < accepted_drop:
            raise ConflictError(
                f"Lot {lot.lot_code} holds {removable} {receipt.unit.value}, which "
                f"is less than the {accepted_drop} {receipt.unit.value} this "
                "correction would remove. The stock has already been used, so "
                "either the correction or the later movements are wrong — and "
                "only a person can say which. Nothing has been changed.",
                details={
                    "lot_code": lot.lot_code,
                    "on_hand": str(removable),
                    "requested": str(accepted_drop),
                    "short_by": str(quantize(accepted_drop - removable)),
                },
            )
        movement = inventory.post_movement(
            session,
            lot=lot,
            movement_type=MovementType.RECEIPT_CORRECTION,
            quantity=convert(accepted_drop, receipt.unit, lot.unit),
            occurred_at=occurred,
            reference_type=EntityType.PURCHASE_ORDER_LINE,
            reference_id=line.id,
            idempotency_key=(
                f"receipt-correction:{idempotency_key}" if idempotency_key else None
            ),
            note=f"Receipt correction: {reason.strip()[:200]}",
            source_document_id=source_document_id,
            created_by_user_id=user_id,
        )
        session.flush()
        stock_removed = accepted_drop

    correction = PurchaseOrderReceiptCorrection(
        receipt_id=receipt.id,
        purchase_order_line_id=line.id,
        accepted_delta=accepted_drop,
        rejected_delta=rejected_drop,
        unit=receipt.unit,
        reason=reason.strip(),
        corrected_at=occurred,
        corrected_by_user_id=user_id,
        idempotency_key=idempotency_key,
        inventory_movement_id=movement.id if movement is not None else None,
        source_document_id=source_document_id,
    )
    session.add(correction)
    # Anything reading receipt.corrections in this transaction — the cumulative
    # check above, on a second correction — must see this one.
    receipt.corrections.append(correction)

    line.received_quantity = quantize(line.received_quantity - accepted_drop)
    line.rejected_quantity = quantize(line.rejected_quantity - rejected_drop)

    status = _refresh_po_status(session, line.purchase_order)
    # The supplier delivered less than we thought, and on-time is measured from
    # what they actually delivered, so their record changes too.
    recompute_supplier_on_time_rate(session, line.purchase_order.supplier)

    record_audit(
        session,
        action="purchase_order.receipt_corrected",
        entity_type=EntityType.PURCHASE_ORDER_LINE,
        entity_id=line.id,
        summary=(
            f"Receipt corrected down by {prose.qty(accepted_drop, receipt.unit)} "
            f"accepted"
            + (f" and {rejected_drop} rejected" if rejected_drop > ZERO else "")
            + f" against {line.purchase_order.number} line {line.line_no} "
            f"({prose.num(line.received_quantity)} of "
            f"{prose.qty(line.ordered_quantity, line.unit)} now recorded). "
            f"Reason: {reason.strip()[:200]}"
        ),
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
        before={"received_to_date": quantize(line.received_quantity + accepted_drop)},
        after={
            "received_to_date": line.received_quantity,
            "ordered": line.ordered_quantity,
            "stock_removed": stock_removed,
            "reason": reason.strip(),
        },
        source_document_id=source_document_id,
    )
    session.flush()
    return CorrectionOutcome(
        correction=correction,
        receipt=receipt,
        stock_removed=stock_removed,
        line_received_quantity=line.received_quantity,
        line_outstanding_quantity=line.outstanding_quantity,
        purchase_order_status=status,
    )
