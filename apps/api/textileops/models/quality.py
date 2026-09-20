"""Quality control inspections and their measurements."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.core.units import UnitOfMeasure
from textileops.models.base import TS, Base, Qty, TimestampMixin, enum_column, pk_column
from textileops.models.enums import MeasurementResult, QCMeasurementKind, QCOutcome


class QCInspection(Base, TimestampMixin):
    __tablename__ = "qc_inspections"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    production_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=True
    )
    inventory_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="CASCADE"), nullable=True
    )
    inspected_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    outcome: Mapped[QCOutcome] = mapped_column(
        enum_column(QCOutcome, "qc_outcome"), nullable=False, default=QCOutcome.PENDING
    )
    inspected_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    accepted_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Qty, nullable=False, default=Decimal("0"), server_default="0"
    )
    unit: Mapped[UnitOfMeasure] = mapped_column(
        enum_column(UnitOfMeasure, "unit_of_measure"), nullable=False
    )
    inspector_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reinspection_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("qc_inspections.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    measurements: Mapped[list[QCMeasurement]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "(production_batch_id is not null) or (inventory_lot_id is not null)",
            name="inspection_targets_something",
        ),
        CheckConstraint("inspected_quantity > 0", name="inspected_quantity_positive"),
        CheckConstraint("accepted_quantity >= 0", name="accepted_non_negative"),
        CheckConstraint("rejected_quantity >= 0", name="rejected_non_negative"),
        CheckConstraint(
            "accepted_quantity + rejected_quantity <= inspected_quantity",
            name="qc_quantities_balance",
        ),
        Index("ix_qc_inspections_batch", "production_batch_id"),
        Index("ix_qc_inspections_outcome_time", "outcome", "inspected_at"),
    )

    @property
    def failed(self) -> bool:
        return self.outcome in (QCOutcome.REJECT, QCOutcome.REWORK)


class QCMeasurement(Base, TimestampMixin):
    """One observation. Numeric *or* textual (shade is judged, not measured)."""

    __tablename__ = "qc_measurements"

    id: Mapped[uuid.UUID] = pk_column()
    qc_inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("qc_inspections.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[QCMeasurementKind] = mapped_column(
        enum_column(QCMeasurementKind, "qc_measurement_kind"), nullable=False
    )
    #: Free-text label, required when ``kind`` is ``other``.
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    observed_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    tolerance_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    tolerance_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    #: Unit of the measurement itself, e.g. "gsm", "cm", "points". Text because
    #: QC units (GSM, defect points) are attributes, not stock quantities.
    unit_text: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[MeasurementResult] = mapped_column(
        enum_column(MeasurementResult, "measurement_result"),
        nullable=False,
        default=MeasurementResult.NOT_ASSESSED,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    inspection: Mapped[QCInspection] = relationship(back_populates="measurements")

    __table_args__ = (
        CheckConstraint(
            "observed_value is not null or observed_text is not null",
            name="measurement_has_observation",
        ),
        CheckConstraint("kind <> 'other' or label is not null", name="other_kind_needs_label"),
        Index("ix_qc_measurements_inspection", "qc_inspection_id"),
    )
