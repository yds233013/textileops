"""Audit, instrumentation, jobs and AI call telemetry."""

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
from sqlalchemy.orm import Mapped, mapped_column

from textileops.models.base import TS, Base, TimestampMixin, enum_column, pk_column
from textileops.models.enums import (
    AICallStatus,
    BusinessEventType,
    EntityType,
    JobStatus,
)


class AuditEvent(Base):
    """Immutable record of every consequential state change.

    Written by services, never updated or deleted.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = pk_column()
    occurred_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False, index=True)
    #: "user" | "system" | "ai"
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        # RESTRICT, not SET NULL: this records what a person did, and
        # deleting their account must not rewrite that into "somebody".
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Dotted verb, e.g. "purchase_order.eta_revised", "proposal.approved".
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operational_exceptions.id", ondelete="SET NULL"), nullable=True
    )
    action_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("action_proposals.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("actor_type in ('user','system','ai')", name="actor_type_values"),
        Index("ix_audit_entity_time", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_action_time", "action", "occurred_at"),
    )


class BusinessMetricEvent(Base):
    """Product instrumentation.

    Deliberately records only *observed* facts (counts and durations). It never
    stores derived claims such as "hours saved" — those must be computed from
    real before/after measurement, not invented.
    """

    __tablename__ = "business_metric_events"

    id: Mapped[uuid.UUID] = pk_column()
    event_type: Mapped[BusinessEventType] = mapped_column(
        enum_column(BusinessEventType, "business_event_type"), nullable=False
    )
    occurred_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False, index=True)
    entity_type: Mapped[EntityType | None] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Elapsed time of the measured workflow step, when it has a duration.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    __table_args__ = (
        CheckConstraint("duration_ms is null or duration_ms >= 0", name="duration_non_negative"),
        Index("ix_metric_events_type_time", "event_type", "occurred_at"),
    )


class Job(Base, TimestampMixin):
    """Durable background job.

    PostgreSQL-backed queue using ``SELECT ... FOR UPDATE SKIP LOCKED``. Chosen
    over an external broker so local development needs one service, while
    keeping at-least-once delivery, retries and idempotency.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = pk_column()
    queue: Mapped[str] = mapped_column(String(48), nullable=False, default="default")
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, "job_status"), nullable=False, default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    locked_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    #: Enqueueing the same key twice is a no-op — jobs are idempotent by design.
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_jobs_queue_status_runafter", "queue", "status", "run_after"),
    )


class AICallLog(Base):
    """Telemetry for every model call, real or stubbed. Never stores prompts
    containing credentials, and never stores raw untrusted content wholesale."""

    __tablename__ = "ai_call_logs"

    id: Mapped[uuid.UUID] = pk_column()
    created_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False, index=True)
    #: e.g. "classify_document", "extract_supplier_message", "investigate_exception"
    workflow: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[AICallStatus] = mapped_column(
        enum_column(AICallStatus, "ai_call_status"), nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[EntityType | None] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_ai_calls_workflow_time", "workflow", "created_at"),
    )
