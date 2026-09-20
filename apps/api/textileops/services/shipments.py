"""Shipments, including partial dispatch against customer order lines."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from textileops.services import clock, inventory
from textileops.services.audit import record_audit

ZERO = Decimal("0")


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
    for line in shipment.lines:
        order_line = session.get(SalesOrderLine, line.sales_order_line_id)
        if order_line is None:
            continue
        drawn = _consume_finished_stock(session, line, order_line, idempotency_key)
        # Report what actually left the building, not what the paperwork said.
        # Crediting the planned quantity would close the line, drop the order
        # out of the open set, and leave the difference invoiced but unshipped
        # with nothing to detect it.
        order_line.shipped_quantity = quantize(order_line.shipped_quantity + drawn)
        wanted = convert(line.quantity, line.unit, order_line.unit)
        if drawn < wanted:
            shortfalls.append(
                f"line {order_line.line_no}: {quantize(wanted - drawn)} "
                f"{order_line.unit.value} short"
            )
        _refresh_order_status(session, order_line.sales_order_id)

    if shortfalls:
        note = (
            "Dispatched short of the packed quantity — "
            + "; ".join(shortfalls)
            + ". Finished stock could not cover it."
        )
        shipment.notes = f"{shipment.notes}\n{note}" if shipment.notes else note

    record_audit(
        session,
        action="shipment.dispatched",
        entity_type=EntityType.SHIPMENT,
        entity_id=shipment.id,
        summary=f"Shipment {shipment.number} dispatched on {when.isoformat()}.",
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
) -> Decimal:
    """Draw the shipped quantity from finished-goods lots, oldest first.

    Returns how much was actually drawn, in the order line's unit. The caller
    credits that figure — never the planned one.
    """
    wanted = convert(line.quantity, line.unit, order_line.unit)
    remaining = wanted
    lots = session.scalars(
        select(InventoryLot)
        .where(
            InventoryLot.fabric_spec_id == order_line.fabric_spec_id,
            InventoryLot.status == "available",
            InventoryLot.quantity_on_hand > 0,
        )
        .order_by(InventoryLot.received_at)
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
