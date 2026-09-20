"""Product instrumentation read model.

What this measures, and what it deliberately does not:

* It counts real events (documents processed, exceptions detected/resolved,
  proposals accepted/rejected, drafts edited, reconciliations needed).
* It measures real durations (source event → detection, detection → first view,
  detection → resolution, proposal → decision).
* It **does not** report "hours saved". That number requires a measured
  baseline of how long these steps took before TextileOps existed, which this
  system cannot observe. :func:`workflow_durations` exposes the raw timings so
  that a genuine before/after study can be run against them later.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    BusinessEventType,
    Severity,
)
from textileops.models.exceptions import OperationalException
from textileops.models.intake import ReconciliationItem, SourceDocument
from textileops.models.platform import AICallLog, BusinessMetricEvent
from textileops.services import clock


@dataclass
class DurationStat:
    label: str
    unit: str = "minutes"
    count: int = 0
    median_value: float | None = None
    p90_value: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "unit": self.unit,
            "count": self.count,
            "median": self.median_value,
            "p90": self.p90_value,
            "note": self.note,
        }


@dataclass
class MetricsSnapshot:
    window_days: int
    counters: dict[str, int] = field(default_factory=dict)
    durations: list[DurationStat] = field(default_factory=list)
    ai: dict[str, Any] = field(default_factory=dict)
    caveat: str = (
        "These are observed counts and durations only. TextileOps does not estimate "
        "hours saved: that needs a measured baseline from before the system was in use."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "counters": self.counters,
            "durations": [d.to_dict() for d in self.durations],
            "ai": self.ai,
            "caveat": self.caveat,
        }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return round(ordered[index], 2)


def _stat(label: str, minutes: list[float], note: str | None = None) -> DurationStat:
    return DurationStat(
        label=label,
        count=len(minutes),
        median_value=round(median(minutes), 2) if minutes else None,
        p90_value=_percentile(minutes, 0.9),
        note=note or (None if minutes else "No completed occurrences yet."),
    )


def snapshot(session: Session, *, window_days: int = 30) -> MetricsSnapshot:
    since = clock.now() - dt.timedelta(days=window_days)
    result = MetricsSnapshot(window_days=window_days)

    def count_events(event_type: BusinessEventType) -> int:
        return int(
            session.scalar(
                select(func.count(BusinessMetricEvent.id)).where(
                    BusinessMetricEvent.event_type == event_type,
                    BusinessMetricEvent.occurred_at >= since,
                )
            )
            or 0
        )

    result.counters = {
        "documents_received": count_events(BusinessEventType.DOCUMENT_RECEIVED),
        "documents_processed": count_events(BusinessEventType.DOCUMENT_PROCESSED),
        "extractions_completed": count_events(BusinessEventType.EXTRACTION_COMPLETED),
        "reconciliations_required": count_events(BusinessEventType.RECONCILIATION_REQUIRED),
        "reconciliations_resolved": count_events(BusinessEventType.RECONCILIATION_RESOLVED),
        "exceptions_detected": count_events(BusinessEventType.EXCEPTION_DETECTED),
        "exceptions_investigated": count_events(BusinessEventType.EXCEPTION_INVESTIGATED),
        "exceptions_resolved": count_events(BusinessEventType.EXCEPTION_RESOLVED),
        "proposals_created": count_events(BusinessEventType.PROPOSAL_CREATED),
        "proposals_approved": count_events(BusinessEventType.PROPOSAL_APPROVED),
        "proposals_rejected": count_events(BusinessEventType.PROPOSAL_REJECTED),
        "drafts_edited": count_events(BusinessEventType.PROPOSAL_DRAFT_EDITED),
        "actions_executed": count_events(BusinessEventType.ACTION_EXECUTED),
        "open_exceptions": int(
            session.scalar(
                select(func.count(OperationalException.id)).where(
                    OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES)
                )
            )
            or 0
        ),
        "open_reconciliations": int(
            session.scalar(
                select(func.count(ReconciliationItem.id)).where(
                    ReconciliationItem.status == "open"
                )
            )
            or 0
        ),
        "documents_awaiting_review": int(
            session.scalar(
                select(func.count(SourceDocument.id)).where(
                    SourceDocument.status == "needs_review"
                )
            )
            or 0
        ),
    }

    approved = result.counters["proposals_approved"]
    rejected = result.counters["proposals_rejected"]
    decided = approved + rejected
    result.counters["proposal_acceptance_rate_pct"] = (
        round(100 * approved / decided) if decided else 0
    )

    result.durations = workflow_durations(session, since=since)
    result.ai = ai_summary(session, since=since)
    return result


def workflow_durations(session: Session, *, since: dt.datetime | None = None) -> list[DurationStat]:
    """Raw workflow timings — the honest basis for any future time-saved study."""
    since = since or (clock.now() - dt.timedelta(days=30))

    detection_latency = [
        row.duration_ms / 60000
        for row in session.scalars(
            select(BusinessMetricEvent).where(
                BusinessMetricEvent.event_type == BusinessEventType.EXCEPTION_DETECTED,
                BusinessMetricEvent.duration_ms.is_not(None),
                BusinessMetricEvent.occurred_at >= since,
            )
        ).all()
        if row.duration_ms is not None
    ]

    exceptions = session.scalars(
        select(OperationalException).where(OperationalException.first_detected_at >= since)
    ).all()

    def _minutes(start, end) -> float | None:
        elapsed = clock.elapsed_ms(start, end)
        return elapsed / 60000 if elapsed is not None else None

    time_to_view = [
        minutes
        for e in exceptions
        if e.first_viewed_at
        and (minutes := _minutes(e.first_detected_at, e.first_viewed_at)) is not None
    ]
    time_to_resolution = [
        minutes
        for e in exceptions
        if e.resolved_at
        and not e.auto_resolved
        and (minutes := _minutes(e.first_detected_at, e.resolved_at)) is not None
    ]

    approval_latency = [
        row.duration_ms / 60000
        for row in session.scalars(
            select(BusinessMetricEvent).where(
                BusinessMetricEvent.event_type == BusinessEventType.PROPOSAL_APPROVED,
                BusinessMetricEvent.duration_ms.is_not(None),
                BusinessMetricEvent.occurred_at >= since,
            )
        ).all()
        if row.duration_ms is not None
    ]

    reconciliation_latency = [
        row.duration_ms / 60000
        for row in session.scalars(
            select(BusinessMetricEvent).where(
                BusinessMetricEvent.event_type == BusinessEventType.RECONCILIATION_RESOLVED,
                BusinessMetricEvent.duration_ms.is_not(None),
                BusinessMetricEvent.occurred_at >= since,
            )
        ).all()
        if row.duration_ms is not None
    ]

    caught_early, total_with_orders = exceptions_caught_before_customer_impact(session, since)

    return [
        _stat(
            "Source event → exception detected",
            detection_latency,
            note="Only exceptions traceable to a timestamped source event are counted.",
        ),
        _stat("Detected → first opened by an operator", time_to_view),
        _stat("Detected → resolved by a person", time_to_resolution),
        _stat("Proposal created → approved", approval_latency),
        _stat("Reconciliation raised → resolved", reconciliation_latency),
        DurationStat(
            label="Exceptions raised before the customer's promised date",
            unit="count",
            count=total_with_orders,
            median_value=float(caught_early),
            note=(
                f"{caught_early} of {total_with_orders} order-linked exceptions were raised "
                "while there was still time to act."
            ),
        ),
    ]


def exceptions_caught_before_customer_impact(
    session: Session, since: dt.datetime
) -> tuple[int, int]:
    exceptions = session.scalars(
        select(OperationalException).where(
            OperationalException.first_detected_at >= since,
            OperationalException.sales_order_id.is_not(None),
        )
    ).all()
    early = 0
    total = 0
    for exception in exceptions:
        impact = exception.impact or {}
        orders = impact.get("affected_orders") or []
        if not orders:
            continue
        total += 1
        try:
            promised = min(dt.date.fromisoformat(o["promised_date"]) for o in orders)
        except (KeyError, ValueError):
            continue
        if clock.ensure_utc(exception.first_detected_at).date() < promised:
            early += 1
    return early, total


def ai_summary(session: Session, *, since: dt.datetime | None = None) -> dict[str, Any]:
    since = since or (clock.now() - dt.timedelta(days=30))
    rows = session.scalars(select(AICallLog).where(AICallLog.created_at >= since)).all()
    by_status: dict[str, int] = {}
    by_workflow: dict[str, int] = {}
    latencies: list[float] = []
    input_tokens = 0
    output_tokens = 0
    for row in rows:
        by_status[row.status.value] = by_status.get(row.status.value, 0) + 1
        by_workflow[row.workflow] = by_workflow.get(row.workflow, 0) + 1
        if row.latency_ms is not None:
            latencies.append(row.latency_ms)
        input_tokens += row.input_tokens or 0
        output_tokens += row.output_tokens or 0
    return {
        "calls": len(rows),
        "by_status": by_status,
        "by_workflow": by_workflow,
        "median_latency_ms": round(median(latencies)) if latencies else None,
        "input_tokens": input_tokens or None,
        "output_tokens": output_tokens or None,
        "stubbed_share_pct": (
            round(100 * by_status.get("stubbed", 0) / len(rows)) if rows else 0
        ),
    }


def exception_breakdown(session: Session) -> dict[str, Any]:
    rows = session.execute(
        select(
            OperationalException.exception_type,
            OperationalException.severity,
            func.count(OperationalException.id),
        )
        .where(OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES))
        .group_by(OperationalException.exception_type, OperationalException.severity)
    ).all()
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {severity.value: 0 for severity in Severity}
    for exception_type, severity, count in rows:
        by_type[exception_type.value] = by_type.get(exception_type.value, 0) + count
        by_severity[severity.value] += count
    return {"by_type": by_type, "by_severity": by_severity}


def mark_exception_viewed(session: Session, exception: OperationalException) -> None:
    """First open of an exception by a person — the 'time to review' clock."""
    if exception.first_viewed_at is None:
        exception.first_viewed_at = clock.now()
