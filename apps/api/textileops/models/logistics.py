"""Shipments to customers, including partial dispatches."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.core.units import UnitOfMeasure
from textileops.models.base import TS, Base, Qty, TimestampMixin, enum_column, pk_column
from textileops.models.enums import ShipmentStatus

if TYPE_CHECKING:
    from textileops.models.org import Customer


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = pk_column()
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        enum_column(ShipmentStatus, "shipment_status"),
        nullable=False,
        default=ShipmentStatus.PLANNED,
    )
    carrier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tracking_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dispatch_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    expected_delivery_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    actual_delivery_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    dispatched_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped[Customer] = relationship(lazy="joined")
    lines: Mapped[list[ShipmentLine]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status not in ('dispatched','in_transit','delivered') or dispatch_date is not null",
            name="dispatched_requires_date",
        ),
        CheckConstraint(
            "actual_delivery_date is null or dispatch_date is null "
            "or actual_delivery_date >= dispatch_date",
            name="delivery_after_dispatch",
        ),
        Index("ix_shipments_status_expected", "status", "expected_delivery_date"),
        Index("ix_shipments_customer", "customer_id"),
    )


class ShipmentLine(Base, TimestampMixin):
    __tablename__ = "shipment_lines"

    id: Mapped[uuid.UUID] = pk_column()
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    sales_order_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    shipment: Mapped[Shipment] = relationship(back_populates="lines")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="shipment_line_quantity_positive"),
        Index("ix_shipment_lines_order_line", "sales_order_line_id"),
    )
