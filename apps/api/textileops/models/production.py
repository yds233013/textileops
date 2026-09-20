"""Production batches, their material requirements and their event log."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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
from textileops.models.base import TS, Base, Qty, TimestampMixin, enum_column, pk_column
from textileops.models.enums import ProductionEventType, ProductionStage, ProductionStatus

if TYPE_CHECKING:
    from textileops.models.catalog import FabricSpec, Material


class ProductionBatch(Base, TimestampMixin):
    __tablename__ = "production_batches"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    fabric_spec_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fabric_specs.id", ondelete="RESTRICT"), nullable=False
    )
    sales_order_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sales_order_lines.id", ondelete="SET NULL"), nullable=True
    )
    stage: Mapped[ProductionStage] = mapped_column(
        enum_column(ProductionStage, "production_stage"), nullable=False
    )
    status: Mapped[ProductionStatus] = mapped_column(
        enum_column(ProductionStatus, "production_status"),
        nullable=False,
        default=ProductionStatus.PLANNED,
    )
    planned_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    output_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    wastage_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    planned_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    planned_completion: Mapped[dt.date] = mapped_column(Date, nullable=False)
    actual_start: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    #: Forward-looking completion date, recomputed by the scheduling service.
    estimated_completion: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    actual_completion: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    depends_on_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="SET NULL"), nullable=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rework_of_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    fabric_spec: Mapped[FabricSpec] = relationship(lazy="joined")
    requirements: Mapped[list[ProductionMaterialRequirement]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", lazy="selectin"
    )
    events: Mapped[list[ProductionEvent]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("planned_completion >= planned_start", name="completion_after_start"),
        CheckConstraint("planned_quantity > 0", name="planned_quantity_positive"),
        CheckConstraint("output_quantity >= 0", name="output_non_negative"),
        CheckConstraint("wastage_quantity >= 0", name="wastage_non_negative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_non_negative"),
        CheckConstraint("priority between 1 and 9", name="priority_range"),
        CheckConstraint(
            "(status <> 'blocked') or (blocked_reason is not null)",
            name="blocked_requires_reason",
        ),
        Index("ix_production_batches_status_completion", "status", "planned_completion"),
        Index("ix_production_batches_order_line", "sales_order_line_id"),
    )

    @property
    def yield_pct(self) -> Decimal | None:
        """Good output ÷ planned quantity. ``None`` until output is recorded."""
        if self.output_quantity == 0:
            return None
        return (self.output_quantity / self.planned_quantity).quantize(Decimal("0.0001"))

    @property
    def effective_completion(self) -> dt.date:
        if self.actual_completion:
            return self.actual_completion.date()
        return self.estimated_completion or self.planned_completion


class ProductionMaterialRequirement(Base, TimestampMixin):
    __tablename__ = "production_material_requirements"

    id: Mapped[uuid.UUID] = pk_column()
    production_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False
    )
    material_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), nullable=False
    )
    required_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    issued_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    required_by: Mapped[dt.date] = mapped_column(Date, nullable=False)

    batch: Mapped[ProductionBatch] = relationship(back_populates="requirements")
    material: Mapped[Material] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("production_batch_id", "material_id", name="uq_batch_material"),
        CheckConstraint("required_quantity > 0", name="required_quantity_positive"),
        CheckConstraint("issued_quantity >= 0", name="issued_non_negative"),
        Index("ix_prod_requirements_material_date", "material_id", "required_by"),
    )

    @property
    def outstanding_quantity(self) -> Decimal:
        return max(Decimal("0"), self.required_quantity - self.issued_quantity)


class ProductionEvent(Base, TimestampMixin):
    """Append-only history of what happened to a batch."""

    __tablename__ = "production_events"

    id: Mapped[uuid.UUID] = pk_column()
    production_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[ProductionEventType] = mapped_column(
        enum_column(ProductionEventType, "production_event_type"), nullable=False
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    unit: Mapped[UnitOfMeasure | None] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        # RESTRICT, not SET NULL: this records what a person did, and
        # deleting their account must not rewrite that into "somebody".
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    batch: Mapped[ProductionBatch] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_production_events_batch_time", "production_batch_id", "occurred_at"),
        CheckConstraint("quantity is null or unit is not null", name="quantity_requires_unit"),
    )
