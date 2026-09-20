"""Customer orders."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.core.units import UnitOfMeasure
from textileops.models.base import (
    TS,
    Base,
    Money,
    Qty,
    TimestampMixin,
    enum_column,
    pk_column,
)
from textileops.models.enums import Currency, SalesOrderStatus

if TYPE_CHECKING:
    from textileops.models.catalog import FabricSpec
    from textileops.models.org import Customer


class SalesOrder(Base, TimestampMixin):
    __tablename__ = "sales_orders"

    id: Mapped[uuid.UUID] = pk_column()
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    order_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    #: The date committed to the customer. The single most important date here.
    promised_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    requested_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[SalesOrderStatus] = mapped_column(
        enum_column(SalesOrderStatus, "sales_order_status"),
        nullable=False,
        default=SalesOrderStatus.DRAFT,
    )
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "currency"), nullable=False, default=Currency.INR
    )
    #: 1 (highest) .. 9. Independent of customer tier so operators can override.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    incoterms: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="sales_orders", lazy="joined")
    lines: Mapped[list[SalesOrderLine]] = relationship(
        back_populates="sales_order", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("promised_date >= order_date", name="promised_after_order"),
        CheckConstraint("priority between 1 and 9", name="priority_range"),
        Index("ix_sales_orders_status_promised", "status", "promised_date"),
        Index("ix_sales_orders_customer", "customer_id"),
    )


class SalesOrderLine(Base, TimestampMixin):
    __tablename__ = "sales_order_lines"

    id: Mapped[uuid.UUID] = pk_column()
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    fabric_spec_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fabric_specs.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    unit_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    #: Quantity that has left the building. Maintained by shipment posting only.
    shipped_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    #: Good output accepted from production for this line.
    produced_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    promised_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    sales_order: Mapped[SalesOrder] = relationship(back_populates="lines")
    fabric_spec: Mapped[FabricSpec] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("sales_order_id", "line_no", name="uq_so_line_no"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("shipped_quantity >= 0", name="shipped_non_negative"),
        # Shipping more than was ordered gives cloth away and usually invoices
        # for it twice. The service refuses it; this is what holds when the
        # service is bypassed — a script, a migration, a future code path that
        # forgets.
        CheckConstraint(
            "shipped_quantity <= quantity", name="shipped_within_ordered"
        ),
        # Same argument for production: a batch cannot credit an order line
        # with more cloth than the line asked for.
        CheckConstraint(
            "produced_quantity <= quantity", name="produced_within_ordered"
        ),
        CheckConstraint("produced_quantity >= 0", name="produced_non_negative"),
        CheckConstraint("unit_price is null or unit_price >= 0", name="unit_price_non_negative"),
        Index("ix_sales_order_lines_spec", "fabric_spec_id"),
    )

    @property
    def outstanding_quantity(self) -> Decimal:
        return max(Decimal("0"), self.quantity - self.shipped_quantity)

    @property
    def line_value(self) -> Decimal | None:
        if self.unit_price is None:
            return None
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))
