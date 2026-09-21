"""Shipments, including partial dispatch against customer order lines."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.db import lock_row
from textileops.core.errors import ConflictError, NotFoundError, ValidationError
from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.enums import (
    EntityType,
    MovementType,
    SalesOrderStatus,
    ShipmentStatus,
)
from textileops.models.inventory import InventoryLot
from textileops.models.logistics import Shipment, ShipmentLine
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock, inventory, prose
from textileops.services.audit import record_audit

ZERO = Decimal("0")

#: An order in one of these states is finished with, and nothing more may leave
#: the building against it.
_UNSHIPPABLE_ORDER_STATUSES = (
    SalesOrderStatus.CANCELLED,
    SalesOrderStatus.CLOSED,
)

#: Shipments that have not yet left. Their quantities are already spoken for,
#: so a new plan may not promise the same cloth again.
_OPEN_SHIPMENT_STATUSES = (
    ShipmentStatus.PLANNED,
    ShipmentStatus.PACKED,
)


def _committed_elsewhere(
    session: Session, order_line: SalesOrderLine, *, excluding: uuid.UUID | None = None
) -> Decimal:
    """Quantity on other shipments that are planned but have not yet gone.

    Two open plans for the same cloth is not a clever way to keep options
    open; it guarantees that one of them reaches the loading bay and finds
    nothing there.
    """
    stmt = (
        select(ShipmentLine.quantity, ShipmentLine.unit)
        .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
        .where(
            ShipmentLine.sales_order_line_id == order_line.id,
            Shipment.status.in_(_OPEN_SHIPMENT_STATUSES),
        )
    )
    if excluding is not None:
        stmt = stmt.where(Shipment.id != excluding)
    rows = session.execute(stmt).all()
    return quantize(
        sum((convert(q, u, order_line.unit) for q, u in rows), ZERO)
    )


def _remaining_to_ship(session: Session, order_line: SalesOrderLine) -> Decimal:
    """Ordered, less what has shipped. Never negative."""
    return quantize(max(ZERO, order_line.quantity - order_line.shipped_quantity))


def _assert_shippable(order_line: SalesOrderLine) -> None:
    order = order_line.sales_order
    if order.status in _UNSHIPPABLE_ORDER_STATUSES:
        raise ConflictError(
            f"Sales order {order.number} is {order.status.value}; nothing further "
            "can be shipped against it.",
            details={
                "sales_order": order.number,
                "status": order.status.value,
                "line_no": order_line.line_no,
            },
        )


def create_shipment(
    session: Session,
    *,
    number: str,
    customer_id: uuid.UUID,
    lines: list[tuple[uuid.UUID, Decimal, UnitOfMeasure]],
    carrier: str | None = None,
    expected_delivery_date: dt.date | None = None,
    notes: str | None = None,
) -> Shipment:
    shipment = Shipment(
        number=number,
        customer_id=customer_id,
        status=ShipmentStatus.PLANNED,
        carrier=carrier,
        expected_delivery_date=expected_delivery_date,
        notes=notes,
    )
    session.add(shipment)
    session.flush()
    for line_id, quantity, unit in lines:
        order_line = session.get(SalesOrderLine, line_id)
        if order_line is None:
            raise NotFoundError(f"Sales order line {line_id} not found.")
        if quantity <= ZERO:
            raise ValidationError("Shipment line quantity must be positive.")
        _assert_shippable(order_line)

        # Convert here rather than at dispatch. A fabric sold by the metre and
        # a shipment keyed in kilograms is a mistake, not a conversion, and
        # discovering it at the loading bay means the lorry is already there.
        try:
            wanted = convert(quantize(quantity), unit, order_line.unit)
        except Exception as exc:
            raise ValidationError(
                f"Line {order_line.line_no} of {order_line.sales_order.number} is "
                f"sold in {order_line.unit.value}, and {unit.value} cannot be "
                f"converted to it: {exc}",
                details={"line_no": order_line.line_no, "unit": unit.value},
            ) from exc

        remaining = _remaining_to_ship(session, order_line)
        already_planned = _committed_elsewhere(session, order_line)
        if wanted > quantize(remaining - already_planned):
            raise ConflictError(
                f"Line {order_line.line_no} of {order_line.sales_order.number} has "
                f"{remaining} {order_line.unit.value} still to ship"
                + (
                    f", of which {already_planned} {order_line.unit.value} is already "
                    "on another open shipment"
                    if already_planned > ZERO
                    else ""
                )
                + f"; this plan plans {wanted} {order_line.unit.value}. Shipping "
                "more than was ordered gives away cloth and usually invoices for "
                "it twice.",
                details={
                    "sales_order": order_line.sales_order.number,
                    "line_no": order_line.line_no,
                    "ordered": str(order_line.quantity),
                    "shipped": str(order_line.shipped_quantity),
                    "remaining": str(remaining),
                    "already_planned": str(already_planned),
                    "requested": str(wanted),
                },
            )
        session.add(
            ShipmentLine(
                shipment_id=shipment.id,
                sales_order_line_id=line_id,
                quantity=quantize(quantity),
                unit=unit,
            )
        )
    session.flush()
    return shipment


def dispatch(
    session: Session,
    shipment: Shipment,
    *,
    dispatch_date: dt.date | None = None,
    tracking_reference: str | None = None,
    user_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> Shipment:
    """Dispatch a shipment: deduct stock, advance order lines, record audit."""
    if shipment.status in (ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT,
                           ShipmentStatus.DELIVERED):
        return shipment
    if shipment.status == ShipmentStatus.CANCELLED:
        raise ConflictError(f"Shipment {shipment.number} is cancelled.")

    when = dispatch_date or clock.today()
    shipment.dispatch_date = when
    shipment.dispatched_at = clock.now()
    shipment.status = ShipmentStatus.DISPATCHED
    if tracking_reference:
        shipment.tracking_reference = tracking_reference

    shortfalls: list[str] = []
    # Lock the parent orders first, then the lines, then the lots — one order
    # for every transaction that touches them, so nothing can cycle.
    #
    # The parents matter because `_refresh_order_status` derives the order's
    # status from *all* its lines while the caller has locked only the line it
    # is writing. Two dispatches on different lines of one order therefore
    # each saw the other's line as stale, both concluded "partially shipped",
    # and a fully shipped order stayed PARTIALLY_SHIPPED for ever. That is not
    # just a wrong label: PARTIALLY_SHIPPED is an *open* status, so the order's
    # batches went on claiming yarn nobody needed, inflating every shortage
    # and purchase recommendation derived from it.
    ordered_lines = sorted(shipment.lines, key=lambda sl: str(sl.sales_order_line_id))
    parent_ids = sorted(
        {
            order_line.sales_order_id
            for order_line in (
                session.get(SalesOrderLine, sl.sales_order_line_id)
                for sl in ordered_lines
            )
            if order_line is not None
        },
        key=str,
    )
    for parent_id in parent_ids:
        parent = session.get(SalesOrder, parent_id)
        if parent is not None:
            lock_row(session, parent)
    for line in ordered_lines:
        order_line = session.get(SalesOrderLine, line.sales_order_line_id)
        if order_line is None:
            continue
        # Lock before reading shipped_quantity: the cap below is a
        # read-calculate-write, and another dispatch committing in between
        # would make the figure it is checked against stale.
        lock_row(session, order_line)
        _assert_shippable(order_line)

        wanted = convert(line.quantity, line.unit, order_line.unit)
        remaining = _remaining_to_ship(session, order_line)
        if remaining <= ZERO:
            raise ConflictError(
                f"Line {order_line.line_no} of {order_line.sales_order.number} has "
                f"already shipped in full ({order_line.shipped_quantity} of "
                f"{order_line.quantity} {order_line.unit.value}). Dispatching this "
                "shipment would send cloth the customer did not order.",
                details={
                    "sales_order": order_line.sales_order.number,
                    "line_no": order_line.line_no,
                    "ordered": str(order_line.quantity),
                    "shipped": str(order_line.shipped_quantity),
                },
            )
        # Never draw more than the order can absorb, however much was packed.
        # Anything beyond this is cloth given away and, usually, invoiced twice.
        allowed = min(wanted, remaining)
        drawn = _consume_finished_stock(
            session, line, order_line, idempotency_key, limit=allowed
        )
        # Report what actually left the building, not what the paperwork said.
        # Crediting the planned quantity would close the line, drop the order
        # out of the open set, and leave the difference invoiced but unshipped
        # with nothing to detect it.
        order_line.shipped_quantity = quantize(order_line.shipped_quantity + drawn)
        if drawn < wanted:
            reason = (
                "beyond the ordered quantity"
                if allowed < wanted
                else "finished stock could not cover it"
            )
            shortfalls.append(
                f"line {order_line.line_no}: {quantize(wanted - drawn)} "
                f"{order_line.unit.value} short ({reason})"
            )
        _refresh_order_status(session, order_line.sales_order_id)

    if shortfalls:
        note = "Dispatched short of the packed quantity — " + "; ".join(shortfalls) + "."
        shipment.notes = f"{shipment.notes}\n{note}" if shipment.notes else note

    record_audit(
        session,
        action="shipment.dispatched",
        entity_type=EntityType.SHIPMENT,
        entity_id=shipment.id,
        summary=f"Shipment {shipment.number} dispatched on {prose.when(when)}.",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
        after={"dispatch_date": when, "tracking_reference": shipment.tracking_reference},
    )
    return shipment


def _consume_finished_stock(
    session: Session,
    line: ShipmentLine,
    order_line: SalesOrderLine,
    idempotency_key: str | None,
    *,
    limit: Decimal | None = None,
) -> Decimal:
    """Draw the shipped quantity from finished-goods lots, oldest first.

    Returns how much was actually drawn, in the order line's unit. The caller
    credits that figure — never the planned one.

    ``limit`` caps the draw at what the order line can still absorb. It is
    applied here rather than by trimming afterwards because the stock has
    physically moved by then: drawing 1,200 m and crediting 1,000 would leave
    200 m out of the warehouse and out of the ledger's explanation for it.
    """
    wanted = convert(line.quantity, line.unit, order_line.unit)
    if limit is not None:
        wanted = min(wanted, quantize(limit))
    remaining = wanted
    # Ordered by receipt date for FIFO, then by id so the sequence is identical
    # in every transaction. Two dispatches drawing the same fabric therefore
    # take the lot locks in the same order and queue rather than deadlock.
    lots = session.scalars(
        select(InventoryLot)
        .where(
            InventoryLot.fabric_spec_id == order_line.fabric_spec_id,
            InventoryLot.status == "available",
            InventoryLot.quantity_on_hand > 0,
        )
        .order_by(InventoryLot.received_at, InventoryLot.id)
    ).all()
    for lot in lots:
        if remaining <= ZERO:
            break
        take = min(convert(lot.quantity_on_hand, lot.unit, order_line.unit), remaining)
        if take <= ZERO:
            continue
        inventory.post_movement(
            session,
            lot=lot,
            movement_type=MovementType.SHIPMENT,
            quantity=convert(take, order_line.unit, lot.unit),
            reference_type=EntityType.SHIPMENT,
            reference_id=line.shipment_id,
            idempotency_key=(
                f"{idempotency_key}:{lot.id}" if idempotency_key else None
            ),
            note=f"Dispatched on shipment line {line.id}.",
        )
        if line.inventory_lot_id is None:
            line.inventory_lot_id = lot.id
        remaining = quantize(remaining - take)
    return quantize(wanted - remaining)


def _refresh_order_status(session: Session, sales_order_id: uuid.UUID) -> None:
    order = session.get(SalesOrder, sales_order_id)
    if order is None or order.status in (
        SalesOrderStatus.CANCELLED,
        SalesOrderStatus.CLOSED,
    ):
        return
    outstanding = sum((line.outstanding_quantity for line in order.lines), ZERO)
    shipped_any = any(line.shipped_quantity > ZERO for line in order.lines)
    if outstanding <= ZERO:
        order.status = SalesOrderStatus.SHIPPED
    elif shipped_any:
        order.status = SalesOrderStatus.PARTIALLY_SHIPPED


def mark_delivered(
    session: Session,
    shipment: Shipment,
    *,
    delivered_on: dt.date | None = None,
    user_id: uuid.UUID | None = None,
) -> Shipment:
    shipment.actual_delivery_date = delivered_on or clock.today()
    shipment.status = ShipmentStatus.DELIVERED
    for line in shipment.lines:
        order_line = session.get(SalesOrderLine, line.sales_order_line_id)
        if order_line is None:
            continue
        order = session.get(SalesOrder, order_line.sales_order_id)
        if order and all(line_.outstanding_quantity <= ZERO for line_ in order.lines):
            order.status = SalesOrderStatus.DELIVERED
    record_audit(
        session,
        action="shipment.delivered",
        entity_type=EntityType.SHIPMENT,
        entity_id=shipment.id,
        summary=f"Shipment {shipment.number} delivered on "
        f"{shipment.actual_delivery_date.isoformat()}.",
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
    )
    return shipment


def delayed_shipments(session: Session, *, as_of: dt.date | None = None) -> list[Shipment]:
    as_of = as_of or clock.today()
    return [
        shipment
        for shipment in session.scalars(
            select(Shipment).where(
                Shipment.status.in_(
                    [ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT, ShipmentStatus.DELAYED]
                ),
                Shipment.actual_delivery_date.is_(None),
                Shipment.expected_delivery_date.is_not(None),
            )
        ).all()
        if shipment.expected_delivery_date and shipment.expected_delivery_date < as_of
    ]
