"""Inventory lots, movements and reservations.

Invariant enforced by :mod:`textileops.services.inventory`:
``lot.quantity_on_hand == sum(movement.quantity_delta for that lot)``.
"""

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
    Numeric,
    String,
    Text,
    text,
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
from textileops.models.enums import (
    Currency,
    EntityType,
    LotStatus,
    MovementType,
    ReservationStatus,
)

if TYPE_CHECKING:
    from textileops.models.catalog import FabricSpec, Material


class InventoryLot(Base, TimestampMixin):
    """A physically identifiable quantity of one material *or* one fabric spec."""

    __tablename__ = "inventory_lots"

    id: Mapped[uuid.UUID] = pk_column()
    lot_code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), nullable=True
    )
    fabric_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fabric_specs.id", ondelete="RESTRICT"), nullable=True
    )
    quantity_received: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    #: Physical stock present. Distinct from *available* (on hand − reserved).
    quantity_on_hand: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    status: Mapped[LotStatus] = mapped_column(
        enum_column(LotStatus, "lot_status"), nullable=False, default=LotStatus.AVAILABLE
    )
    location: Mapped[str] = mapped_column(String(64), nullable=False, default="MAIN")
    received_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    purchase_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="SET NULL"), nullable=True
    )
    production_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="SET NULL"), nullable=True
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[Currency | None] = mapped_column(
        enum_column(Currency, "currency"), nullable=True
    )
    #: Measured attributes of *this* lot (may differ from the spec).
    gsm_actual: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    width_cm_actual: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    shade_code_actual: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    material: Mapped[Material | None] = relationship(lazy="joined")
    fabric_spec: Mapped[FabricSpec | None] = relationship(lazy="joined")
    movements: Mapped[list[InventoryMovement]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "(material_id is not null) <> (fabric_spec_id is not null)",
            name="lot_is_material_xor_fabric",
        ),
        CheckConstraint("quantity_received >= 0", name="received_non_negative"),
        CheckConstraint("quantity_on_hand >= 0", name="on_hand_non_negative"),
        CheckConstraint("unit_cost is null or currency is not null", name="cost_requires_currency"),
        Index("ix_inventory_lots_material_status", "material_id", "status"),
        Index("ix_inventory_lots_spec_status", "fabric_spec_id", "status"),
    )


class InventoryMovement(Base, TimestampMixin):
    """An append-only ledger entry. ``quantity_delta`` is signed."""

    __tablename__ = "inventory_movements"

    id: Mapped[uuid.UUID] = pk_column()
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="CASCADE"), nullable=False
    )
    movement_type: Mapped[MovementType] = mapped_column(
        enum_column(MovementType, "movement_type"), nullable=False
    )
    #: Positive for inbound, negative for outbound. Expressed in the lot's unit.
    quantity_delta: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    reference_type: Mapped[EntityType | None] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=True
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    #: Guarantees replayed jobs do not double-post stock.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    lot: Mapped[InventoryLot] = relationship(back_populates="movements")

    __table_args__ = (
        CheckConstraint("quantity_delta <> 0", name="delta_non_zero"),
        Index("ix_inventory_movements_lot_time", "lot_id", "occurred_at"),
        Index("ix_inventory_movements_ref", "reference_type", "reference_id"),
    )


class InventoryReservation(Base, TimestampMixin):
    """A soft allocation of stock to a demand (order line or production batch)."""

    __tablename__ = "inventory_reservations"

    id: Mapped[uuid.UUID] = pk_column()
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=True
    )
    fabric_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fabric_specs.id", ondelete="CASCADE"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    status: Mapped[ReservationStatus] = mapped_column(
        enum_column(ReservationStatus, "reservation_status"),
        nullable=False,
        default=ReservationStatus.ACTIVE,
    )
    required_by: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    sales_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="CASCADE"), nullable=True
    )
    production_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=True
    )
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(material_id is not null) <> (fabric_spec_id is not null)",
            name="reservation_is_material_xor_fabric",
        ),
        CheckConstraint("quantity > 0", name="reservation_quantity_positive"),
        Index("ix_reservations_material_status", "material_id", "status"),
        Index("ix_reservations_spec_status", "fabric_spec_id", "status"),
        # A batch's material requirement already has uq_batch_material; its
        # mirror reservation had nothing, so re-exploding a batch's bill of
        # materials could leave two active reservations for the same material
        # and quietly halve the stock the rest of the business can see.
        Index(
            "uq_active_reservation_per_batch_material",
            "production_batch_id",
            "material_id",
            unique=True,
            postgresql_where=text("status = 'active' and production_batch_id is not null"),
        ),
        # Releasing a reservation without stamping when is how a released row
        # comes to look active again to anything reading timestamps.
        CheckConstraint(
            "status <> 'released' or released_at is not null",
            name="reservation_released_has_timestamp",
        ),
        # Covers release_reservations(production_batch_id=...), which runs on
        # every batch completion and cancellation and was a sequential scan.
        Index("ix_reservations_batch_status", "production_batch_id", "status"),
    )
