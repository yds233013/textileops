"""Operational exceptions and the evidence behind them."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.models.base import TS, Base, TimestampMixin, enum_column, pk_column
from textileops.models.enums import (
    EntityType,
    EvidenceKind,
    ExceptionStatus,
    ExceptionType,
    Severity,
)


class OperationalException(Base, TimestampMixin):
    """Something that needs a human's attention, with why and what it costs."""

    __tablename__ = "operational_exceptions"

    id: Mapped[uuid.UUID] = pk_column()
    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    exception_type: Mapped[ExceptionType] = mapped_column(
        enum_column(ExceptionType, "exception_type"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(enum_column(Severity, "severity"), nullable=False)
    status: Mapped[ExceptionStatus] = mapped_column(
        enum_column(ExceptionStatus, "exception_status"),
        nullable=False,
        default=ExceptionStatus.OPEN,
    )
    #: Stable identity of the *underlying issue*. Unique — this is what stops
    #: the engine raising the same problem twice on every recomputation.
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_detected_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    detected_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    last_evaluated_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    #: Timestamp of the business event that caused this — powers the
    #: "time from source event to detection" instrumentation.
    source_event_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    first_viewed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    dismissed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    investigated_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    #: Set when the engine no longer detects the condition but a human has not
    #: closed it: used to auto-resolve cleanly.
    auto_resolved: Mapped[bool] = mapped_column(nullable=False, default=False)

    #: An assignment, not an act: SET NULL is right here, because unassigning
    #: an open exception when somebody leaves is exactly what should happen.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Who decided this was dealt with. An act, so RESTRICT. Null when the
    #: engine auto-resolved it — which is why ``auto_resolved`` is a separate
    #: flag rather than being inferred from this being empty.
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Primary subject ------------------------------------------------------
    entity_type: Mapped[EntityType] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    # --- Denormalised links for filtering (all optional) ----------------------
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=True
    )
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=True
    )
    production_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("production_batches.id", ondelete="CASCADE"), nullable=True
    )
    material_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), nullable=True
    )
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=True
    )
    qc_inspection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("qc_inspections.id", ondelete="CASCADE"), nullable=True
    )

    #: Deterministically calculated impact (see services/impact.py). Any field
    #: that could not be computed from trusted data is explicitly marked
    #: unavailable rather than guessed.
    impact: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    #: Raw numbers the detector used, kept for explainability.
    detection_metrics: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    #: Ranking score used by the attention queue (higher = more urgent).
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Number of times the detector has re-confirmed this condition.
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    evidence: Mapped[list[ExceptionEvidence]] = relationship(
        back_populates="exception",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExceptionEvidence.sort_order",
    )
    investigations: Mapped[list[Investigation]] = relationship(
        back_populates="exception", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "(status <> 'resolved') or (resolved_at is not null)",
            name="resolved_requires_timestamp",
        ),
        CheckConstraint(
            "(status <> 'dismissed') or (dismissed_at is not null)",
            name="dismissed_requires_timestamp",
        ),
        Index("ix_exceptions_status_severity", "status", "severity"),
        Index("ix_exceptions_type_status", "exception_type", "status"),
        Index("ix_exceptions_entity", "entity_type", "entity_id"),
        Index("ix_exceptions_priority", "priority_score"),
    )


class ExceptionEvidence(Base, TimestampMixin):
    """A single piece of *why*: a calculation, record, message or document."""

    __tablename__ = "exception_evidence"

    id: Mapped[uuid.UUID] = pk_column()
    exception_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operational_exceptions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[EvidenceKind] = mapped_column(
        enum_column(EvidenceKind, "evidence_kind"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    entity_type: Mapped[EntityType | None] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    exception: Mapped[OperationalException] = relationship(back_populates="evidence")

    __table_args__ = (Index("ix_evidence_exception_order", "exception_id", "sort_order"),)


class Investigation(Base, TimestampMixin):
    """A read-only AI (or rule-based) investigation of one exception."""

    __tablename__ = "investigations"

    id: Mapped[uuid.UUID] = pk_column()
    exception_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("operational_exceptions.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Validated investigation payload (what happened / evidence / root cause /
    #: impact / options / recommendation / missing information).
    findings: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    #: Names of the read-only tools the agent called, in order.
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        # RESTRICT, not SET NULL: this records what a person did, and
        # deleting their account must not rewrite that into "somebody".
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    exception: Mapped[OperationalException] = relationship(back_populates="investigations")

    __table_args__ = (Index("ix_investigations_exception", "exception_id", "started_at"),)
