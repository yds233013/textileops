"""The command centre: exceptions, their evidence, and their investigations."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from textileops.api.deps import ApproverUser, CurrentUser, DbSession
from textileops.core.errors import NotFoundError, ValidationError
from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    BusinessEventType,
    EntityType,
    ExceptionStatus,
    ExceptionType,
    Severity,
)
from textileops.models.exceptions import Investigation, OperationalException
from textileops.services import clock, exception_engine
from textileops.services import investigation as investigation_service
from textileops.services import metrics as metrics_service
from textileops.services.audit import record_audit, record_metric

router = APIRouter(prefix="/exceptions", tags=["exceptions"])


class EvidenceOut(BaseModel):
    id: uuid.UUID
    kind: str
    label: str
    detail: str
    data: dict[str, Any] | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    message_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    recorded_at: dt.datetime


class ExceptionOut(BaseModel):
    id: uuid.UUID
    code: str
    exception_type: str
    severity: str
    status: str
    title: str
    summary: str
    recommended_action: str | None
    detected_at: dt.datetime
    first_detected_at: dt.datetime
    last_evaluated_at: dt.datetime
    resolved_at: dt.datetime | None
    investigated_at: dt.datetime | None
    priority_score: int
    occurrence_count: int
    auto_resolved: bool
    entity_type: str
    entity_id: uuid.UUID
    customer_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    sales_order_id: uuid.UUID | None
    purchase_order_id: uuid.UUID | None
    production_batch_id: uuid.UUID | None
    material_id: uuid.UUID | None
    shipment_id: uuid.UUID | None
    impact: dict[str, Any] | None
    detection_metrics: dict[str, Any] | None
    owner_user_id: uuid.UUID | None
    resolution_note: str | None


class InvestigationOut(BaseModel):
    id: uuid.UUID
    started_at: dt.datetime
    completed_at: dt.datetime | None
    provider: str
    model: str | None
    findings: dict[str, Any] | None
    tool_calls: list[dict[str, Any]] | None
    error: str | None
    is_stubbed: bool


class ExceptionDetailOut(ExceptionOut):
    evidence: list[EvidenceOut]
    investigations: list[InvestigationOut]
    proposal_ids: list[uuid.UUID]


class ExceptionListOut(BaseModel):
    items: list[ExceptionOut]
    total: int
    counts_by_severity: dict[str, int]
    counts_by_type: dict[str, int]


def _out(exception: OperationalException) -> ExceptionOut:
    return ExceptionOut(
        id=exception.id,
        code=exception.code,
        exception_type=exception.exception_type.value,
        severity=exception.severity.value,
        status=exception.status.value,
        title=exception.title,
        summary=exception.summary,
        recommended_action=exception.recommended_action,
        detected_at=exception.detected_at,
        first_detected_at=exception.first_detected_at,
        last_evaluated_at=exception.last_evaluated_at,
        resolved_at=exception.resolved_at,
        investigated_at=exception.investigated_at,
        priority_score=exception.priority_score,
        occurrence_count=exception.occurrence_count,
        auto_resolved=exception.auto_resolved,
        entity_type=exception.entity_type.value,
        entity_id=exception.entity_id,
        customer_id=exception.customer_id,
        supplier_id=exception.supplier_id,
        sales_order_id=exception.sales_order_id,
        purchase_order_id=exception.purchase_order_id,
        production_batch_id=exception.production_batch_id,
        material_id=exception.material_id,
        shipment_id=exception.shipment_id,
        impact=exception.impact,
        detection_metrics=exception.detection_metrics,
        owner_user_id=exception.owner_user_id,
        resolution_note=exception.resolution_note,
    )


@router.get("", response_model=ExceptionListOut)
def list_exceptions(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    severity: str | None = None,
    exception_type: str | None = None,
    customer_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    sales_order_id: uuid.UUID | None = None,
    material_id: uuid.UUID | None = None,
    detected_since: dt.date | None = None,
    include_closed: bool = False,
    limit: int = Query(200, ge=1, le=500),
) -> ExceptionListOut:
    stmt = select(OperationalException).order_by(
        OperationalException.priority_score.desc(), OperationalException.detected_at.desc()
    )
    if status:
        stmt = stmt.where(OperationalException.status == ExceptionStatus(status))
    elif not include_closed:
        stmt = stmt.where(OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES))
    if severity:
        stmt = stmt.where(OperationalException.severity == Severity(severity))
    if exception_type:
        stmt = stmt.where(OperationalException.exception_type == ExceptionType(exception_type))
    if customer_id:
        stmt = stmt.where(OperationalException.customer_id == customer_id)
    if supplier_id:
        stmt = stmt.where(OperationalException.supplier_id == supplier_id)
    if sales_order_id:
        stmt = stmt.where(OperationalException.sales_order_id == sales_order_id)
    if material_id:
        stmt = stmt.where(OperationalException.material_id == material_id)
    if detected_since:
        stmt = stmt.where(
            OperationalException.detected_at
            >= dt.datetime.combine(detected_since, dt.time.min, dt.UTC)
        )

    items = list(session.scalars(stmt.limit(limit)).all())
    by_severity = {level.value: 0 for level in Severity}
    by_type: dict[str, int] = {}
    for exception in items:
        by_severity[exception.severity.value] += 1
        by_type[exception.exception_type.value] = (
            by_type.get(exception.exception_type.value, 0) + 1
        )
    return ExceptionListOut(
        items=[_out(exception) for exception in items],
        total=len(items),
        counts_by_severity=by_severity,
        counts_by_type=by_type,
    )


@router.get("/{exception_id}", response_model=ExceptionDetailOut)
def get_exception(
    exception_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> ExceptionDetailOut:
    exception = session.get(OperationalException, exception_id)
    if exception is None:
        raise NotFoundError(f"Exception {exception_id} not found.")

    # First open by a person starts the 'time to review' measurement.
    if exception.first_viewed_at is None:
        metrics_service.mark_exception_viewed(session, exception)
        record_metric(
            session,
            event_type=BusinessEventType.EXCEPTION_VIEWED,
            entity_type=EntityType.EXCEPTION,
            entity_id=exception.id,
            user_id=user.id,
            duration_ms=clock.elapsed_ms(exception.first_detected_at),
        )
        session.commit()

    from textileops.models.actions import ActionProposal

    proposal_ids = list(
        session.scalars(
            select(ActionProposal.id).where(ActionProposal.exception_id == exception.id)
        ).all()
    )
    investigations = session.scalars(
        select(Investigation)
        .where(Investigation.exception_id == exception.id)
        .order_by(Investigation.started_at.desc())
    ).all()

    return ExceptionDetailOut(
        **_out(exception).model_dump(),
        evidence=[
            EvidenceOut(
                id=item.id,
                kind=item.kind.value,
                label=item.label,
                detail=item.detail,
                data=item.data,
                entity_type=item.entity_type.value if item.entity_type else None,
                entity_id=item.entity_id,
                message_id=item.message_id,
                source_document_id=item.source_document_id,
                recorded_at=item.recorded_at,
            )
            for item in exception.evidence
        ],
        investigations=[
            InvestigationOut(
                id=record.id,
                started_at=record.started_at,
                completed_at=record.completed_at,
                provider=record.provider,
                model=record.model,
                findings=record.findings,
                tool_calls=record.tool_calls,
                error=record.error,
                is_stubbed=bool((record.findings or {}).get("stubbed")),
            )
            for record in investigations
        ],
        proposal_ids=proposal_ids,
    )


class InvestigateResponse(BaseModel):
    investigation: InvestigationOut
    proposal_ids: list[uuid.UUID]


@router.post("/{exception_id}/investigate", response_model=InvestigateResponse)
def investigate(
    exception_id: uuid.UUID, session: DbSession, user: ApproverUser
) -> InvestigateResponse:
    exception = session.get(OperationalException, exception_id)
    if exception is None:
        raise NotFoundError(f"Exception {exception_id} not found.")
    record = investigation_service.investigate_exception(session, exception, user_id=user.id)
    session.commit()

    from textileops.models.actions import ActionProposal

    proposal_ids = list(
        session.scalars(
            select(ActionProposal.id).where(ActionProposal.exception_id == exception.id)
        ).all()
    )
    return InvestigateResponse(
        investigation=InvestigationOut(
            id=record.id,
            started_at=record.started_at,
            completed_at=record.completed_at,
            provider=record.provider,
            model=record.model,
            findings=record.findings,
            tool_calls=record.tool_calls,
            error=record.error,
            is_stubbed=bool((record.findings or {}).get("stubbed")),
        ),
        proposal_ids=proposal_ids,
    )


class StatusChangeRequest(BaseModel):
    status: str = Field(pattern="^(open|investigating|resolved|dismissed)$")
    note: str | None = None
    owner_user_id: uuid.UUID | None = None


@router.post("/{exception_id}/status", response_model=ExceptionOut)
def change_status(
    exception_id: uuid.UUID,
    payload: StatusChangeRequest,
    session: DbSession,
    user: ApproverUser,
) -> ExceptionOut:
    exception = session.get(OperationalException, exception_id)
    if exception is None:
        raise NotFoundError(f"Exception {exception_id} not found.")
    target = ExceptionStatus(payload.status)
    if target in (ExceptionStatus.RESOLVED, ExceptionStatus.DISMISSED) and not payload.note:
        raise ValidationError(
            "Closing an exception requires a note saying what was done or why it was "
            "dismissed."
        )

    before = exception.status
    exception.status = target
    exception.resolution_note = payload.note or exception.resolution_note
    if payload.owner_user_id is not None:
        exception.owner_user_id = payload.owner_user_id
    now = clock.now()
    if target == ExceptionStatus.RESOLVED:
        exception.resolved_at = now
        exception.auto_resolved = False
    elif target == ExceptionStatus.DISMISSED:
        exception.dismissed_at = now
    else:
        exception.resolved_at = None
        exception.dismissed_at = None

    record_audit(
        session,
        action=f"exception.{target.value}",
        entity_type=EntityType.EXCEPTION,
        entity_id=exception.id,
        summary=f"{exception.code} moved from {before.value} to {target.value}."
        + (f" {payload.note}" if payload.note else ""),
        actor_type="user",
        actor_user_id=user.id,
        exception_id=exception.id,
        before={"status": before.value},
        after={"status": target.value, "note": payload.note},
    )
    if target in (ExceptionStatus.RESOLVED, ExceptionStatus.DISMISSED):
        record_metric(
            session,
            event_type=(
                BusinessEventType.EXCEPTION_RESOLVED
                if target == ExceptionStatus.RESOLVED
                else BusinessEventType.EXCEPTION_DISMISSED
            ),
            entity_type=EntityType.EXCEPTION,
            entity_id=exception.id,
            user_id=user.id,
            duration_ms=clock.elapsed_ms(exception.first_detected_at, now),
            payload={"auto": False, "exception_type": exception.exception_type.value},
        )
    session.commit()
    return _out(exception)


class RecomputeResponse(BaseModel):
    created: int
    updated: int
    auto_resolved: int
    unchanged: int
    created_codes: list[str]
    auto_resolved_codes: list[str]


@router.post("/recompute", response_model=RecomputeResponse)
def recompute(session: DbSession, user: ApproverUser) -> RecomputeResponse:
    """Re-derive every exception from current state. Idempotent."""
    from textileops.services import production as production_service

    production_service.refresh_all_estimates(session)
    result = exception_engine.run(session)
    session.commit()
    summary = result.summary()
    return RecomputeResponse(
        **summary,
        created_codes=result.created,
        auto_resolved_codes=result.auto_resolved,
    )
