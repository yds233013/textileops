"""The dashboard: what needs attention right now, and why."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from textileops.api.deps import CurrentUser, DbSession
from textileops.models.actions import ActionProposal
from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    OPEN_PO_STATUSES,
    ProposalStatus,
    ReconciliationStatus,
    RiskLevel,
    Severity,
)
from textileops.models.exceptions import OperationalException
from textileops.models.intake import ReconciliationItem, SourceDocument
from textileops.models.procurement import PurchaseOrder
from textileops.services import clock
from textileops.services import metrics as metrics_service
from textileops.services import orders as order_service
from textileops.services import production as production_service
from textileops.services.prose import plural

router = APIRouter(tags=["dashboard"])


class AttentionCard(BaseModel):
    """One item in the attention queue, in the four parts an operator needs."""

    exception_id: uuid.UUID
    code: str
    exception_type: str
    severity: str
    status: str
    priority_score: int
    #: WHAT happened
    what: str
    #: WHY it matters
    why: str
    #: IMPACT if nothing is done
    impact_headline: str
    impact_metrics: list[dict[str, Any]]
    #: RECOMMENDED next step
    recommended_action: str | None
    customers_affected: list[str]
    revenue_exposure: str | None
    revenue_basis: str
    #: Why there is no figure, when there is none. Without it the card can only
    #: stay silent, and silence reads as "nothing is at stake".
    revenue_note: str | None
    currency: str | None
    detected_at: dt.datetime
    age_hours: float
    has_investigation: bool
    pending_proposal_count: int
    links: dict[str, str | None]


class MetricTile(BaseModel):
    key: str
    label: str
    value: float | int | str | None
    unit: str | None = None
    hint: str | None = None
    tone: str = "neutral"  # neutral | good | warn | bad


class UpcomingOrder(BaseModel):
    id: uuid.UUID
    number: str
    customer_name: str
    promised_date: dt.date
    risk: str


class DashboardOut(BaseModel):
    greeting: str
    as_of: dt.datetime
    attention_queue: list[AttentionCard]
    metrics: list[MetricTile]
    counts_by_severity: dict[str, int]
    counts_by_type: dict[str, int]
    ai_mode: str
    ai_note: str
    #: Open orders promised within ``UPCOMING_DAYS``, soonest first. From the
    #: assessments this endpoint already makes, so the Command Centre does not
    #: assess every order a second time through /orders.
    upcoming: list[UpcomingOrder]


UPCOMING_DAYS = 21
UPCOMING_LIMIT = 6


def _greeting(now: dt.datetime) -> str:
    hour = now.hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    session: DbSession, _user: CurrentUser, limit: int = Query(12, ge=1, le=50)
) -> DashboardOut:
    from textileops.core.config import settings

    now = clock.now()
    today = now.date()

    exceptions = list(
        session.scalars(
            select(OperationalException)
            .where(OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES))
            .order_by(
                OperationalException.priority_score.desc(),
                OperationalException.detected_at.desc(),
            )
            .limit(limit)
        ).all()
    )
    pending_counts: dict[uuid.UUID, int] = {
        exception_id: count
        for exception_id, count in session.execute(
            select(ActionProposal.exception_id, func.count(ActionProposal.id))
            .where(ActionProposal.status == ProposalStatus.PENDING_APPROVAL)
            .group_by(ActionProposal.exception_id)
        ).all()
        if exception_id is not None
    }

    cards = [_card(exception, pending_counts.get(exception.id, 0), now) for exception in exceptions]

    all_active = list(
        session.scalars(
            select(OperationalException).where(
                OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES)
            )
        ).all()
    )
    by_severity = {level.value: 0 for level in Severity}
    by_type: dict[str, int] = {}
    for exception in all_active:
        by_severity[exception.severity.value] += 1
        by_type[exception.exception_type.value] = by_type.get(exception.exception_type.value, 0) + 1

    assessments = order_service.assess_open_orders(session)
    at_risk = [a for a in assessments if a.risk == RiskLevel.AT_RISK]
    late = [a for a in assessments if a.risk == RiskLevel.LATE]

    # Measured from confirmed arrivals, never from an internal closure stamp.
    delivery = metrics_service.on_time_delivery(session)

    open_pos = list(
        session.scalars(
            select(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        ).all()
    )
    late_pos = [po for po in open_pos if po.current_expected_date < today]

    open_batches = production_service.open_batches(session)
    blocked = [b for b in open_batches if b.status.value == "blocked"]
    shortage_count = by_type.get("MATERIAL_SHORTAGE", 0)

    pending_proposals = int(
        session.scalar(
            select(func.count(ActionProposal.id)).where(
                ActionProposal.status == ProposalStatus.PENDING_APPROVAL
            )
        )
        or 0
    )
    open_reconciliations = int(
        session.scalar(
            select(func.count(ReconciliationItem.id)).where(
                ReconciliationItem.status == ReconciliationStatus.OPEN
            )
        )
        or 0
    )
    docs_needing_review = int(
        session.scalar(
            select(func.count(SourceDocument.id)).where(
                SourceDocument.status == "needs_review"
            )
        )
        or 0
    )

    metrics = [
        MetricTile(
            key="open_orders",
            label="Open orders",
            value=len(assessments),
            hint="Confirmed through to partially shipped.",
        ),
        MetricTile(
            key="orders_at_risk",
            label="Orders at risk",
            value=len(at_risk),
            tone="warn" if at_risk else "good",
            hint="Earliest completion is after the promised date.",
        ),
        MetricTile(
            key="orders_late",
            label="Orders late",
            value=len(late),
            tone="bad" if late else "good",
            hint="Promised date has passed with quantity outstanding.",
        ),
        MetricTile(
            key="on_time_pct",
            label="On-time delivery",
            value=delivery.percentage,
            unit="%" if delivery.percentage is not None else None,
            tone=(
                "neutral"
                if delivery.percentage is None
                else "good"
                if delivery.percentage >= 90
                else "warn"
            ),
            hint=(
                (
                    f"Across {plural(delivery.measured, 'order')} with a confirmed delivery date."
                    + (
                        f" {delivery.unmeasured} more are finished but not confirmed "
                        "delivered, so they are not counted."
                        if delivery.unmeasured
                        else ""
                    )
                )
                if delivery.measured
                else "No order has a confirmed delivery date yet, so no rate can be shown."
            ),
        ),
        MetricTile(key="open_pos", label="Open purchase orders", value=len(open_pos)),
        MetricTile(
            key="late_pos",
            label="Late purchase orders",
            value=len(late_pos),
            tone="bad" if late_pos else "good",
        ),
        MetricTile(
            key="batches_in_flight",
            label="Batches in flight",
            value=len(open_batches),
            hint=f"{len(blocked)} blocked." if blocked else None,
            tone="warn" if blocked else "neutral",
        ),
        MetricTile(
            key="material_shortages",
            label="Materials short",
            value=shortage_count,
            tone="bad" if shortage_count else "good",
        ),
        MetricTile(
            key="pending_approvals",
            label="Awaiting your approval",
            value=pending_proposals,
            tone="warn" if pending_proposals else "neutral",
        ),
        MetricTile(
            key="reconciliation_queue",
            label="Needs reconciliation",
            value=open_reconciliations + docs_needing_review,
            tone="warn" if (open_reconciliations + docs_needing_review) else "neutral",
            hint="Documents or messages TextileOps could not map with confidence.",
        ),
    ]

    return DashboardOut(
        greeting=f"{_greeting(now)}. Here is what needs your attention.",
        as_of=now,
        attention_queue=cards,
        metrics=metrics,
        counts_by_severity=by_severity,
        counts_by_type=by_type,
        ai_mode="model" if settings.ai_enabled else "deterministic",
        ai_note=(
            f"AI features are using {settings.ai_model}."
            if settings.ai_enabled
            else "No model credentials are configured. Extraction and investigation are "
            "running on the deterministic rule engine, and every AI-derived item is "
            "labelled accordingly."
        ),
        upcoming=[
            UpcomingOrder(
                id=a.order_id,
                number=a.number,
                customer_name=a.customer_name,
                promised_date=a.promised_date,
                risk=a.risk.value,
            )
            for a in sorted(assessments, key=lambda a: (a.promised_date, a.number))
            if (a.promised_date - today).days <= UPCOMING_DAYS
        ][:UPCOMING_LIMIT],
    )


def _card(
    exception: OperationalException, pending_proposals: int, now: dt.datetime
) -> AttentionCard:
    impact = exception.impact or {}
    financial = impact.get("financial") or {}
    return AttentionCard(
        exception_id=exception.id,
        code=exception.code,
        exception_type=exception.exception_type.value,
        severity=exception.severity.value,
        status=exception.status.value,
        priority_score=exception.priority_score,
        what=exception.title,
        why=exception.summary,
        impact_headline=impact.get("headline", "Impact not yet calculated."),
        impact_metrics=impact.get("metrics", []),
        recommended_action=exception.recommended_action,
        customers_affected=impact.get("customers_affected", []),
        revenue_exposure=financial.get("revenue_exposure"),
        revenue_basis=financial.get("basis", "unavailable"),
        revenue_note=financial.get("note"),
        currency=financial.get("currency"),
        detected_at=exception.detected_at,
        age_hours=round(
            (now - clock.ensure_utc(exception.first_detected_at)).total_seconds() / 3600, 1
        ),
        has_investigation=exception.investigated_at is not None,
        pending_proposal_count=pending_proposals,
        links={
            "order": str(exception.sales_order_id) if exception.sales_order_id else None,
            "purchase_order": str(exception.purchase_order_id)
            if exception.purchase_order_id
            else None,
            "batch": str(exception.production_batch_id)
            if exception.production_batch_id
            else None,
            "material": str(exception.material_id) if exception.material_id else None,
            "shipment": str(exception.shipment_id) if exception.shipment_id else None,
        },
    )
