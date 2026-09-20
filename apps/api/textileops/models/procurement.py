"""Suppliers' purchase orders, lines and receipts."""

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
from textileops.models.enums import Currency, PurchaseOrderStatus

if TYPE_CHECKING:
    from textileops.models.catalog import Material
    from textileops.models.org import Supplier


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = pk_column()
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    order_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    #: The date originally agreed with the supplier. Immutable once sent.
    expected_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    #: The date we *currently* believe. Always carries provenance (see below).
    revised_expected_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        enum_column(PurchaseOrderStatus, "purchase_order_status"),
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
    )
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "currency"), nullable=False, default=Currency.INR
    )
    incoterms: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supplier_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)

    # --- Provenance for the current ETA belief --------------------------------
    # These columns answer: "Why does TextileOps believe PO-2231 arrives Oct 12?"
    eta_source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    eta_source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    eta_updated_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    eta_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    supplier: Mapped[Supplier] = relationship(back_populates="purchase_orders", lazy="joined")
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("expected_date >= order_date", name="expected_after_order"),
        Index("ix_purchase_orders_status_expected", "status", "expected_date"),
        Index("ix_purchase_orders_supplier", "supplier_id"),
    )

    @property
    def current_expected_date(self) -> dt.date:
        """The date we act on: the revised ETA when one exists."""
        return self.revised_expected_date or self.expected_date


class PurchaseOrderLine(Base, TimestampMixin):
    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = pk_column()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    ordered_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    #: Sum of accepted receipt quantities. Maintained only by receipt posting.
    received_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    unit_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    expected_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    material: Mapped[Material] = relationship(lazy="joined")
    receipts: Mapped[list[PurchaseOrderReceipt]] = relationship(
        back_populates="purchase_order_line", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("purchase_order_id", "line_no", name="uq_po_line_no"),
        CheckConstraint("ordered_quantity > 0", name="ordered_quantity_positive"),
        CheckConstraint("received_quantity >= 0", name="received_non_negative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_non_negative"),
        Index("ix_purchase_order_lines_material", "material_id"),
    )

    @property
    def outstanding_quantity(self) -> Decimal:
        """Ordered minus accepted. Never negative; over-receipt is its own exception."""
        return max(Decimal("0"), self.ordered_quantity - self.received_quantity)


class PurchaseOrderReceipt(Base, TimestampMixin):
    """A single (possibly partial) goods receipt against a PO line."""

    __tablename__ = "purchase_order_receipts"

    id: Mapped[uuid.UUID] = pk_column()
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="CASCADE"), nullable=False
    )
    received_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    accepted_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    supplier_document_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Replay guard. Distinct from ``supplier_document_ref``: a supplier's
    #: challan number identifies *their* paperwork, not our request, and
    #: overloading one for the other means a caller supplying both silently
    #: loses the guard.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    unit_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    purchase_order_line: Mapped[PurchaseOrderLine] = relationship(back_populates="receipts")
    corrections: Mapped[list[PurchaseOrderReceiptCorrection]] = relationship(
        back_populates="receipt",
        order_by="PurchaseOrderReceiptCorrection.corrected_at",
        cascade="all",
    )

    __table_args__ = (
        CheckConstraint("accepted_quantity >= 0", name="accepted_non_negative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_non_negative"),
        CheckConstraint(
            "accepted_quantity + rejected_quantity > 0", name="receipt_has_quantity"
        ),
        Index("ix_po_receipts_line_time", "purchase_order_line_id", "received_at"),
    )

    @property
    def corrected_accepted_quantity(self) -> Decimal:
        """Accepted quantity less every correction posted against this receipt."""
        return self.accepted_quantity - sum(
            (c.accepted_delta for c in self.corrections), Decimal("0")
        )

    @property
    def corrected_rejected_quantity(self) -> Decimal:
        return self.rejected_quantity - sum(
            (c.rejected_delta for c in self.corrections), Decimal("0")
        )

    @property
    def is_corrected(self) -> bool:
        return bool(self.corrections)


class PurchaseOrderReceiptCorrection(Base, TimestampMixin):
    """A reduction of a posted receipt, recorded rather than applied in place.

    A receipt is a statement about what physically arrived. When it turns out
    to be wrong the statement does not stop having been made — so the original
    row is immutable and this is a separate entry against it, the way a ledger
    reverses rather than erases.

    Corrections only ever reduce. If more arrived than was keyed, the extra
    genuinely turned up and is recorded as another receipt; a correction can
    therefore never create stock.
    """

    __tablename__ = "purchase_order_receipt_corrections"

    id: Mapped[uuid.UUID] = pk_column()
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        # RESTRICT: the correction is the evidence that the receipt was wrong.
        # Deleting the receipt must not be able to take that with it.
        ForeignKey("purchase_order_receipts.id", ondelete="RESTRICT"), nullable=False
    )
    #: Denormalised so a line's corrections can be found without joining every
    #: receipt — the coverage path reads this on every position query.
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="CASCADE"), nullable=False
    )
    #: How much of the accepted quantity did not arrive. A positive magnitude;
    #: the direction is fixed by what this row *is*.
    accepted_delta: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    rejected_delta: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    #: Why. Required — a quantity that moved without a stated reason is the
    #: thing an auditor asks about first.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    #: Who. RESTRICT, because "somebody removed 100 kg" is not an answer.
    corrected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True
    )
    #: The movement that took the stock back out, when there was any to take.
    inventory_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_movements.id", ondelete="RESTRICT"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )

    receipt: Mapped[PurchaseOrderReceipt] = relationship(back_populates="corrections")

    __table_args__ = (
        CheckConstraint("accepted_delta >= 0", name="accepted_delta_non_negative"),
        CheckConstraint("rejected_delta >= 0", name="rejected_delta_non_negative"),
        CheckConstraint(
            "accepted_delta + rejected_delta > 0", name="correction_has_quantity"
        ),
        CheckConstraint("length(trim(reason)) > 0", name="correction_has_reason"),
        Index("ix_receipt_corrections_receipt", "receipt_id"),
        Index("ix_receipt_corrections_line", "purchase_order_line_id"),
    )
