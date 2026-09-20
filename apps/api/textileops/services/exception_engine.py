"""The deterministic exception engine.

Exceptions are *derived*, not authored. Every detector is a pure function of
current database state, so the same data always produces the same exceptions —
no model call, no randomness, no drift.

Three properties matter:

**Deduplication.** Each detection carries a ``dedupe_key`` identifying the
underlying issue (not the occurrence). Re-running the engine updates the
existing exception — severity, evidence, impact, occurrence count — instead of
creating a second copy.

**Lifecycle.** ``OPEN → INVESTIGATING → ACTION_PROPOSED → RESOLVED/DISMISSED``.
Human-set states are never overwritten by a re-run.

**Auto-resolution.** When a condition stops being detected, its exception is
closed with ``auto_resolved=True`` so the queue reflects reality rather than
accumulating stale alerts.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.db import advisory_xact_lock
from textileops.core.logging import get_logger
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    SEVERITY_RANK,
    BusinessEventType,
    EntityType,
    EvidenceKind,
    ExceptionStatus,
    ExceptionType,
    QCOutcome,
    RiskLevel,
    Severity,
)
from textileops.models.exceptions import ExceptionEvidence, OperationalException
from textileops.models.intake import Message
from textileops.models.org import Customer
from textileops.models.procurement import PurchaseOrder
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection
from textileops.models.sales import SalesOrder
from textileops.services import clock, coverage, impact, orders, procurement, production, shipments
from textileops.services.audit import record_audit, record_metric
from textileops.services.impact import Impact, Metric

logger = get_logger(__name__)
ZERO = Decimal("0")


def _date_text(value: dt.date | dt.datetime | None, fallback: str = "unknown") -> str:
    """Render a date for an operator, saying so plainly when there isn't one."""
    return value.isoformat() if value is not None else fallback


@dataclass
class EvidenceItem:
    kind: EvidenceKind
    label: str
    detail: str
    data: dict | None = None
    entity_type: EntityType | None = None
    entity_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    source_document_id: uuid.UUID | None = None


@dataclass
class Detection:
    """A detector's finding, before it is reconciled with what is already open."""

    dedupe_key: str
    exception_type: ExceptionType
    severity: Severity
    title: str
    summary: str
    entity_type: EntityType
    entity_id: uuid.UUID
    impact: Impact
    recommended_action: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    detection_metrics: dict = field(default_factory=dict)
    source_event_at: dt.datetime | None = None
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    production_batch_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    shipment_id: uuid.UUID | None = None
    qc_inspection_id: uuid.UUID | None = None
    #: Days of lateness/urgency, used for ranking.
    urgency_days: int = 0


@dataclass
class EngineResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    auto_resolved: list[str] = field(default_factory=list)
    unchanged: int = 0

    def summary(self) -> dict[str, int]:
        return {
            "created": len(self.created),
            "updated": len(self.updated),
            "auto_resolved": len(self.auto_resolved),
            "unchanged": self.unchanged,
        }


# =============================================================================
# Detectors
# =============================================================================


def detect_order_risk(session: Session) -> list[Detection]:
    """ORDER_LATE and ORDER_AT_RISK from the deterministic order assessment."""
    out: list[Detection] = []
    today = clock.today()

    for assessment in orders.assess_open_orders(session):
        if assessment.risk in (RiskLevel.ON_TRACK, RiskLevel.WATCH):
            continue
        order = session.get(SalesOrder, assessment.order_id)
        if order is None:
            continue
        customer = session.get(Customer, assessment.customer_id)
        tier = customer.priority_tier if customer else 5
        affected = impact.affected_order(order)
        outstanding = sum((line.outstanding_quantity for line in assessment.lines), ZERO)
        unit = assessment.lines[0].unit if assessment.lines else UnitOfMeasure.METRE

        if assessment.risk == RiskLevel.LATE:
            days_late = (today - assessment.promised_date).days
            severity = (
                Severity.CRITICAL if days_late >= 5 or tier <= 2 else Severity.HIGH
            )
            metrics = [
                impact.days_metric("days_late", "Days past promised date", days_late),
                impact.quantity_metric(
                    "quantity_outstanding", "Quantity not yet shipped", outstanding, unit
                ),
                impact.margin_metric(1),
            ]
            detection_impact = Impact(
                headline=(
                    f"{assessment.customer_name} is {days_late} day(s) past the promised "
                    f"date with {outstanding} {unit.value} undelivered."
                ),
                metrics=metrics,
                affected_orders=[affected],
            )
            out.append(
                Detection(
                    dedupe_key=f"{ExceptionType.ORDER_LATE.value}:{order.id}",
                    exception_type=ExceptionType.ORDER_LATE,
                    severity=severity,
                    title=f"{order.number} is late for {assessment.customer_name}",
                    summary=(
                        f"Order {order.number} was promised on "
                        f"{assessment.promised_date.isoformat()} and {outstanding} "
                        f"{unit.value} is still outstanding."
                    ),
                    entity_type=EntityType.SALES_ORDER,
                    entity_id=order.id,
                    impact=detection_impact,
                    recommended_action=(
                        "Confirm a realistic revised date with production, then tell the "
                        "customer before they ask."
                    ),
                    evidence=_order_evidence(session, assessment, days_late=days_late),
                    detection_metrics={
                        "days_late": days_late,
                        "outstanding_quantity": str(outstanding),
                        "unit": unit.value,
                        "estimated_completion": (
                            assessment.estimated_completion.isoformat()
                            if assessment.estimated_completion
                            else None
                        ),
                    },
                    customer_id=assessment.customer_id,
                    sales_order_id=order.id,
                    urgency_days=days_late,
                )
            )
        else:  # AT_RISK
            if assessment.estimated_completion is None:
                shortfall_days = 0
                detail = (
                    "No completion date can be given: the outstanding quantity has "
                    "neither finished stock nor a planned production batch."
                )
            else:
                shortfall_days = (
                    assessment.estimated_completion - assessment.promised_date
                ).days
                detail = (
                    f"Earliest completion is "
                    f"{assessment.estimated_completion.isoformat()}, which is "
                    f"{shortfall_days} day(s) after the promised date."
                )
            severity = (
                Severity.CRITICAL
                if tier <= 2 and shortfall_days >= 3
                else Severity.HIGH
                if shortfall_days >= 3 or tier <= 2
                else Severity.MEDIUM
            )
            detection_impact = Impact(
                headline=(
                    f"{assessment.customer_name}'s order {order.number} will miss its "
                    f"promised date"
                    + (f" by {shortfall_days} day(s)." if shortfall_days else ".")
                ),
                metrics=[
                    impact.days_metric("days_short", "Days beyond promise", shortfall_days),
                    impact.quantity_metric(
                        "quantity_at_risk", "Quantity at risk", outstanding, unit
                    ),
                    impact.margin_metric(1),
                ],
                affected_orders=[affected],
                notes=[detail],
            )
            out.append(
                Detection(
                    dedupe_key=f"{ExceptionType.ORDER_AT_RISK.value}:{order.id}",
                    exception_type=ExceptionType.ORDER_AT_RISK,
                    severity=severity,
                    title=f"{order.number} at risk of missing "
                    f"{assessment.promised_date.isoformat()}",
                    summary=detail,
                    entity_type=EntityType.SALES_ORDER,
                    entity_id=order.id,
                    impact=detection_impact,
                    recommended_action=(
                        "Review the blocking batch or material, and decide between "
                        "expediting supply, re-prioritising production, or renegotiating "
                        "the date."
                    ),
                    evidence=_order_evidence(session, assessment, days_late=shortfall_days),
                    detection_metrics={
                        "days_short": shortfall_days,
                        "estimated_completion": (
                            assessment.estimated_completion.isoformat()
                            if assessment.estimated_completion
                            else None
                        ),
                        "promised_date": assessment.promised_date.isoformat(),
                        "material_readiness": assessment.material_readiness,
                        "production_status": assessment.production_status,
                    },
                    customer_id=assessment.customer_id,
                    sales_order_id=order.id,
                    urgency_days=max(shortfall_days, 0),
                )
            )
    return out


def _order_evidence(
    session: Session, assessment: orders.OrderAssessment, *, days_late: int
) -> list[EvidenceItem]:
    items = [
        EvidenceItem(
            kind=EvidenceKind.CALCULATION,
            label="Order position",
            detail=(
                f"Promised {assessment.promised_date.isoformat()}; estimated completion "
                f"{_date_text(assessment.estimated_completion)}; "
                f"material readiness {assessment.material_readiness}; "
                f"production {assessment.production_status}; QC {assessment.qc_status}."
            ),
            data={
                "promised_date": assessment.promised_date.isoformat(),
                "estimated_completion": (
                    assessment.estimated_completion.isoformat()
                    if assessment.estimated_completion
                    else None
                ),
                "days": days_late,
            },
            entity_type=EntityType.SALES_ORDER,
            entity_id=assessment.order_id,
        )
    ]
    for reason in assessment.blocked_reasons:
        items.append(
            EvidenceItem(
                kind=EvidenceKind.RECORD,
                label="Blocked production",
                detail=reason,
                entity_type=EntityType.SALES_ORDER,
                entity_id=assessment.order_id,
            )
        )
    return items


def detect_material_shortage(session: Session) -> list[Detection]:
    """MATERIAL_SHORTAGE — demand that supply cannot meet, and who it hits."""
    out: list[Detection] = []
    for result in coverage.analyse_all_materials(session):
        starved = [a for a in result.allocations if a.is_short or a.is_late]
        if not starved:
            continue

        affected_orders = []
        seen: set[uuid.UUID] = set()
        for allocation in starved:
            if allocation.sales_order_id and allocation.sales_order_id not in seen:
                seen.add(allocation.sales_order_id)
                affected = impact.affected_order_from_id(session, allocation.sales_order_id)
                if affected:
                    affected_orders.append(affected)

        first_needed = min(a.requirement.required_by for a in starved)
        days_until = (first_needed - clock.today()).days
        hard_short = any(a.is_short for a in starved)
        severity = (
            Severity.CRITICAL
            if hard_short and days_until <= 7
            else Severity.HIGH
            if hard_short or days_until <= 3
            else Severity.MEDIUM
        )

        batch_codes = [a.requirement.production_batch_code for a in starved]
        detection_impact = Impact(
            headline=(
                f"{result.shortage} {result.unit.value} of {result.material_name} short "
                f"for {len(batch_codes)} batch(es) from {first_needed.isoformat()}."
                if hard_short
                else f"{result.material_name} arrives after it is needed for "
                f"{len(batch_codes)} batch(es)."
            ),
            metrics=[
                impact.quantity_metric(
                    "shortage", "Quantity short", result.shortage, result.unit
                ),
                impact.quantity_metric(
                    "available", "On site and drawable", result.available, result.unit
                ),
                impact.quantity_metric(
                    "incoming", "Confirmed incoming", result.incoming, result.unit
                ),
                impact.quantity_metric(
                    "required", "Required in horizon", result.required, result.unit
                ),
                Metric(
                    key="batches_affected",
                    label="Production batches affected",
                    value=len(batch_codes),
                ),
                impact.margin_metric(len(affected_orders)),
            ],
            affected_orders=affected_orders,
            notes=[
                f"Demand is allocated earliest-required-first; "
                f"{', '.join(batch_codes[:5])} are the batches left uncovered."
            ],
        )

        evidence = [
            EvidenceItem(
                kind=EvidenceKind.CALCULATION,
                label="Coverage calculation",
                detail=(
                    f"On site and drawable {result.available} {result.unit.value} + "
                    f"incoming {result.incoming} − required {result.required} = "
                    f"{result.available + result.incoming - result.required} "
                    f"{result.unit.value}."
                ),
                data={
                    "available": str(result.available),
                    "on_hand": str(result.on_hand),
                    "incoming": str(result.incoming),
                    "required": str(result.required),
                    "shortage": str(result.shortage),
                    "unit": result.unit.value,
                },
                entity_type=EntityType.MATERIAL,
                entity_id=result.material_id,
            )
        ]
        for line in result.incoming_lines[:5]:
            evidence.append(
                EvidenceItem(
                    kind=EvidenceKind.RECORD,
                    label=f"Incoming: {line.purchase_order_number}",
                    detail=(
                        f"{line.quantity} {line.unit.value} from {line.supplier_name} "
                        f"expected {line.expected_date.isoformat()}"
                        + (" (revised)" if line.is_revised else "")
                    ),
                    entity_type=EntityType.PURCHASE_ORDER,
                    entity_id=line.purchase_order_id,
                )
            )
        for allocation in starved[:6]:
            evidence.append(
                EvidenceItem(
                    kind=EvidenceKind.RECORD,
                    label=f"Demand: {allocation.requirement.production_batch_code}",
                    detail=(
                        f"Needs {allocation.requirement.quantity} "
                        f"{allocation.requirement.unit.value} by "
                        f"{allocation.requirement.required_by.isoformat()}; short by "
                        f"{allocation.shortfall_quantity}"
                        + (
                            f"; covering stock only lands "
                            f"{allocation.covered_by_date.isoformat()}"
                            if allocation.is_late and allocation.covered_by_date
                            else ""
                        )
                    ),
                    entity_type=EntityType.PRODUCTION_BATCH,
                    entity_id=allocation.requirement.production_batch_id,
                )
            )

        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.MATERIAL_SHORTAGE.value}:{result.material_id}",
                exception_type=ExceptionType.MATERIAL_SHORTAGE,
                severity=severity,
                title=f"{result.material_name} short for production",
                summary=(
                    f"{result.material_code} is short by {result.shortage} "
                    f"{result.unit.value} against demand due from "
                    f"{first_needed.isoformat()}."
                    if hard_short
                    else f"{result.material_code} is covered only by stock arriving after "
                    f"it is needed ({first_needed.isoformat()})."
                ),
                entity_type=EntityType.MATERIAL,
                entity_id=result.material_id,
                impact=detection_impact,
                recommended_action=(
                    "Chase the open purchase order for an earlier date, or raise a "
                    "top-up order with an alternative supplier."
                ),
                evidence=evidence,
                detection_metrics={
                    "shortage": str(result.shortage),
                    "available": str(result.available),
                    "incoming": str(result.incoming),
                    "required": str(result.required),
                    "unit": result.unit.value,
                    "first_needed": first_needed.isoformat(),
                },
                material_id=result.material_id,
                customer_id=affected_orders[0].customer_id if affected_orders else None,
                sales_order_id=(
                    affected_orders[0].sales_order_id if len(affected_orders) == 1 else None
                ),
                urgency_days=max(0, 30 - days_until),
            )
        )
    return out


def detect_po_issues(session: Session) -> list[Detection]:
    """PO_LATE, SUPPLIER_DELAY and QUANTITY_MISMATCH."""
    out: list[Detection] = []
    today = clock.today()

    # --- PO_LATE: the believed date has passed and goods are outstanding -----
    for status in procurement.late_purchase_orders(session, as_of=today):
        po = status.purchase_order
        blocked_orders = _orders_waiting_on_po(session, po)
        severity = (
            Severity.CRITICAL
            if status.days_late >= 7 and blocked_orders
            else Severity.HIGH
            if status.days_late >= 3 or blocked_orders
            else Severity.MEDIUM
        )
        outstanding_text = ", ".join(
            f"{qty} {unit.value} of {code}"
            for code, (qty, unit) in status.outstanding_by_material.items()
        )
        detection_impact = Impact(
            headline=(
                f"{po.supplier.name} is {status.days_late} day(s) late on {po.number} "
                f"({outstanding_text})."
            ),
            metrics=[
                impact.days_metric("days_late", "Days late", status.days_late),
                Metric(
                    key="materials_outstanding",
                    label="Materials outstanding",
                    value=len(status.outstanding_by_material),
                ),
                impact.margin_metric(len(blocked_orders)),
            ],
            affected_orders=blocked_orders,
        )
        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.PO_LATE.value}:{po.id}",
                exception_type=ExceptionType.PO_LATE,
                severity=severity,
                title=f"{po.number} overdue from {po.supplier.name}",
                summary=(
                    f"Expected {po.current_expected_date.isoformat()}; still outstanding: "
                    f"{outstanding_text}."
                ),
                entity_type=EntityType.PURCHASE_ORDER,
                entity_id=po.id,
                impact=detection_impact,
                recommended_action=(
                    f"Ask {po.supplier.name} for a firm revised date and confirm whether "
                    "a part-shipment can be released now."
                ),
                evidence=_po_evidence(session, po, days_late=status.days_late),
                detection_metrics={
                    "days_late": status.days_late,
                    "expected_date": po.current_expected_date.isoformat(),
                    "has_partial_receipt": status.has_partial_receipt,
                },
                supplier_id=po.supplier_id,
                purchase_order_id=po.id,
                urgency_days=status.days_late,
            )
        )

    # --- SUPPLIER_DELAY: a revised ETA that pushes past the original ---------
    for po in procurement.open_purchase_orders(session):
        if po.revised_expected_date is None:
            continue
        delay_days = (po.revised_expected_date - po.expected_date).days
        if delay_days < settings.supplier_delay_warn_days:
            continue
        blocked_orders = _orders_waiting_on_po(session, po)
        severity = (
            Severity.HIGH if blocked_orders or delay_days >= 5 else Severity.MEDIUM
        )
        detection_impact = Impact(
            headline=(
                f"{po.supplier.name} moved {po.number} out by {delay_days} day(s), to "
                f"{po.revised_expected_date.isoformat()}."
            ),
            metrics=[
                impact.days_metric("delay_days", "Days pushed out", delay_days),
                impact.margin_metric(len(blocked_orders)),
            ],
            affected_orders=blocked_orders,
            notes=[po.eta_note] if po.eta_note else [],
        )
        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.SUPPLIER_DELAY.value}:{po.id}",
                exception_type=ExceptionType.SUPPLIER_DELAY,
                severity=severity,
                title=f"{po.supplier.name} delayed {po.number} by {delay_days} day(s)",
                # Deliberately no quoted reason. This summary is rendered into
                # the investigator's brief under "what the deterministic engine
                # found" — outside the untrusted fence — so a supplier's prose
                # here arrives dressed as our own conclusion, forged delimiters
                # and all. The words themselves are kept, as fenced evidence.
                summary=(
                    f"Original date {po.expected_date.isoformat()}, now "
                    f"{po.revised_expected_date.isoformat()}."
                    + (" A reason was given; see the evidence." if po.eta_note else "")
                ),
                entity_type=EntityType.PURCHASE_ORDER,
                entity_id=po.id,
                impact=detection_impact,
                recommended_action=(
                    "Check whether the new date still supports the batches that need "
                    "this material; expedite or re-plan if it does not."
                ),
                evidence=_po_evidence(session, po, days_late=delay_days),
                detection_metrics={
                    "delay_days": delay_days,
                    "original_expected": po.expected_date.isoformat(),
                    "revised_expected": po.revised_expected_date.isoformat(),
                },
                supplier_id=po.supplier_id,
                purchase_order_id=po.id,
                source_event_at=po.eta_updated_at,
                urgency_days=delay_days,
            )
        )

        # --- QUANTITY_MISMATCH: received more than ordered -------------------
    for po in session.scalars(select(PurchaseOrder)).all():
        for line in po.lines:
            if line.ordered_quantity <= ZERO:
                continue
            over = line.received_quantity - line.ordered_quantity
            if over <= ZERO:
                continue
            tolerance = line.ordered_quantity * procurement.OVER_RECEIPT_TOLERANCE
            if over <= tolerance:
                continue
            detection_impact = Impact(
                headline=(
                    f"{po.number} line {line.line_no} received {over} "
                    f"{line.unit.value} more than ordered."
                ),
                metrics=[
                    impact.quantity_metric("ordered", "Ordered", line.ordered_quantity, line.unit),
                    impact.quantity_metric(
                        "received", "Received", line.received_quantity, line.unit
                    ),
                    impact.quantity_metric("difference", "Over-receipt", over, line.unit),
                ],
            )
            out.append(
                Detection(
                    dedupe_key=f"{ExceptionType.QUANTITY_MISMATCH.value}:{line.id}",
                    exception_type=ExceptionType.QUANTITY_MISMATCH,
                    severity=Severity.MEDIUM,
                    title=f"Over-receipt on {po.number} line {line.line_no}",
                    summary=(
                        f"Ordered {line.ordered_quantity} {line.unit.value} of "
                        f"{line.material.code}; received {line.received_quantity}."
                    ),
                    entity_type=EntityType.PURCHASE_ORDER_LINE,
                    entity_id=line.id,
                    impact=detection_impact,
                    recommended_action=(
                        "Confirm with the supplier whether the excess is billable, "
                        "returnable, or a recording error."
                    ),
                    evidence=[
                        EvidenceItem(
                            kind=EvidenceKind.CALCULATION,
                            label="Quantity comparison",
                            detail=(
                                f"Ordered {line.ordered_quantity} {line.unit.value}; "
                                f"accepted receipts total {line.received_quantity} "
                                f"{line.unit.value}."
                            ),
                            data={
                                "ordered": str(line.ordered_quantity),
                                "received": str(line.received_quantity),
                                "unit": line.unit.value,
                            },
                            entity_type=EntityType.PURCHASE_ORDER_LINE,
                            entity_id=line.id,
                        )
                    ],
                    detection_metrics={
                        "ordered": str(line.ordered_quantity),
                        "received": str(line.received_quantity),
                        "over_by": str(over),
                    },
                    supplier_id=po.supplier_id,
                    purchase_order_id=po.id,
                    material_id=line.material_id,
                    urgency_days=0,
                )
            )
    return out


def _po_evidence(session: Session, po: PurchaseOrder, *, days_late: int) -> list[EvidenceItem]:
    items: list[EvidenceItem] = [
        EvidenceItem(
            kind=EvidenceKind.RECORD,
            label="Purchase order",
            detail=(
                f"{po.number} to {po.supplier.name}, ordered "
                f"{po.order_date.isoformat()}, originally expected "
                f"{po.expected_date.isoformat()}."
            ),
            entity_type=EntityType.PURCHASE_ORDER,
            entity_id=po.id,
        )
    ]
    if po.eta_note:
        # MESSAGE, not RECORD: these are the supplier's words, not ours.
        # The kind is what puts it behind the fence when the investigator's
        # brief is built, so getting it wrong here would put quoted prose back
        # into the trusted half by another route.
        items.append(
            EvidenceItem(
                kind=EvidenceKind.MESSAGE,
                label="Reason given by the supplier",
                detail=po.eta_note,
                entity_type=EntityType.PURCHASE_ORDER,
                entity_id=po.id,
            )
        )
    for line in po.lines:
        items.append(
            EvidenceItem(
                kind=EvidenceKind.CALCULATION,
                label=f"Line {line.line_no}: {line.material.code}",
                detail=(
                    f"Ordered {line.ordered_quantity} {line.unit.value}, received "
                    f"{line.received_quantity}, outstanding {line.outstanding_quantity}."
                ),
                data={
                    "ordered": str(line.ordered_quantity),
                    "received": str(line.received_quantity),
                    "outstanding": str(line.outstanding_quantity),
                    "unit": line.unit.value,
                },
                entity_type=EntityType.PURCHASE_ORDER_LINE,
                entity_id=line.id,
            )
        )
    if po.eta_source_message_id:
        message = session.get(Message, po.eta_source_message_id)
        if message:
            items.append(
                EvidenceItem(
                    kind=EvidenceKind.MESSAGE,
                    label=f"Supplier message of {message.received_at.date().isoformat()}",
                    detail=message.body[:500],
                    message_id=message.id,
                    entity_type=EntityType.MESSAGE,
                    entity_id=message.id,
                )
            )
    return items


def _orders_waiting_on_po(session: Session, po: PurchaseOrder) -> list[impact.AffectedOrder]:
    """Customer orders whose batches consume a material on this PO."""
    material_ids = {line.material_id for line in po.lines if line.outstanding_quantity > ZERO}
    if not material_ids:
        return []
    line_ids: list[uuid.UUID] = []
    for material_id in material_ids:
        result = coverage.analyse_material(session, material_id)
        for allocation in result.allocations:
            if allocation.requirement.sales_order_line_id:
                line_ids.append(allocation.requirement.sales_order_line_id)
    return impact.orders_for_lines(session, line_ids)


def detect_production_delay(session: Session) -> list[Detection]:
    """PRODUCTION_DELAY — a batch whose honest estimate slips past the plan."""
    out: list[Detection] = []
    for delay in production.delayed_batches(session):
        batch = delay.batch
        affected = impact.orders_for_lines(
            session, [batch.sales_order_line_id] if batch.sales_order_line_id else []
        )
        makes_order_late = False
        for order in affected:
            if batch.estimated_completion and batch.estimated_completion > order.promised_date:
                makes_order_late = True
        severity = (
            Severity.HIGH
            if makes_order_late or delay.delay_days >= 5
            else Severity.MEDIUM
        )
        detection_impact = Impact(
            headline=(
                f"{batch.code} is running {delay.delay_days} day(s) late"
                if delay.delay_days
                else f"{batch.code} has no achievable completion date"
            ),
            metrics=[
                impact.days_metric("delay_days", "Days late against plan", delay.delay_days),
                impact.quantity_metric(
                    "planned_quantity", "Batch quantity", batch.planned_quantity, batch.unit
                ),
                impact.margin_metric(len(affected)),
            ],
            affected_orders=affected,
            notes=[delay.reason],
        )
        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.PRODUCTION_DELAY.value}:{batch.id}",
                exception_type=ExceptionType.PRODUCTION_DELAY,
                severity=severity,
                title=f"Batch {batch.code} behind schedule",
                summary=(
                    f"Planned completion {batch.planned_completion.isoformat()}; "
                    f"current estimate {_date_text(batch.estimated_completion)}. "
                    f"{delay.reason}"
                ),
                entity_type=EntityType.PRODUCTION_BATCH,
                entity_id=batch.id,
                impact=detection_impact,
                recommended_action=(
                    "Re-sequence the line or add a shift; if neither recovers the date, "
                    "tell the customer early."
                ),
                evidence=[
                    EvidenceItem(
                        kind=EvidenceKind.CALCULATION,
                        label="Schedule",
                        detail=(
                            f"Planned {batch.planned_start.isoformat()} → "
                            f"{batch.planned_completion.isoformat()}; status "
                            f"{batch.status.value}; estimate "
                            f"{_date_text(batch.estimated_completion, 'none')}."
                        ),
                        data={
                            "planned_start": batch.planned_start.isoformat(),
                            "planned_completion": batch.planned_completion.isoformat(),
                            "estimated_completion": (
                                batch.estimated_completion.isoformat()
                                if batch.estimated_completion
                                else None
                            ),
                            "delay_days": delay.delay_days,
                        },
                        entity_type=EntityType.PRODUCTION_BATCH,
                        entity_id=batch.id,
                    )
                ],
                detection_metrics={
                    "delay_days": delay.delay_days,
                    "status": batch.status.value,
                    "reason": delay.reason,
                },
                production_batch_id=batch.id,
                sales_order_id=affected[0].sales_order_id if affected else None,
                customer_id=affected[0].customer_id if affected else None,
                urgency_days=delay.delay_days,
            )
        )
    return out


def detect_qc_failures(session: Session) -> list[Detection]:
    """QC_FAILURE — a rejection or rework that has not yet been closed out."""
    out: list[Detection] = []
    inspections = session.scalars(
        select(QCInspection)
        .where(QCInspection.outcome.in_([QCOutcome.REJECT, QCOutcome.REWORK]))
        .order_by(QCInspection.inspected_at.desc())
    ).all()

    for inspection in inspections:
        # A failure that has already been re-inspected and passed is closed.
        passed_later = session.scalar(
            select(func.count(QCInspection.id)).where(
                QCInspection.reinspection_of_id == inspection.id,
                QCInspection.outcome.in_([QCOutcome.PASS, QCOutcome.CONDITIONAL_PASS]),
            )
        )
        if passed_later:
            continue

        batch = (
            session.get(ProductionBatch, inspection.production_batch_id)
            if inspection.production_batch_id
            else None
        )
        affected = impact.orders_for_lines(
            session,
            [batch.sales_order_line_id] if batch and batch.sales_order_line_id else [],
        )
        severity = (
            Severity.CRITICAL
            if inspection.outcome == QCOutcome.REJECT and affected
            else Severity.HIGH
        )
        failed_measurements = [
            m
            for m in inspection.measurements
            if m.result.value == "out_of_tolerance" or (m.kind.value == "shade" and m.observed_text)
        ]
        detail = "; ".join(
            f"{m.kind.value}: observed "
            f"{m.observed_text or m.observed_value}"
            + (f" (target {m.target_value})" if m.target_value is not None else "")
            for m in failed_measurements
        ) or (inspection.notes or "No measurement detail recorded.")

        detection_impact = Impact(
            headline=(
                f"{inspection.rejected_quantity} {inspection.unit.value} failed QC"
                + (f" on {batch.code}" if batch else "")
                + "."
            ),
            metrics=[
                impact.quantity_metric(
                    "rejected_quantity",
                    "Quantity rejected",
                    inspection.rejected_quantity,
                    inspection.unit,
                ),
                impact.quantity_metric(
                    "inspected_quantity",
                    "Quantity inspected",
                    inspection.inspected_quantity,
                    inspection.unit,
                ),
                impact.margin_metric(len(affected)),
            ],
            affected_orders=affected,
            notes=[detail],
        )
        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.QC_FAILURE.value}:{inspection.id}",
                exception_type=ExceptionType.QC_FAILURE,
                severity=severity,
                title=(
                    f"QC {inspection.outcome.value.replace('_', ' ')} on "
                    f"{batch.code if batch else inspection.code}"
                ),
                summary=(
                    f"Inspection {inspection.code} on "
                    f"{inspection.inspected_at.date().isoformat()} rejected "
                    f"{inspection.rejected_quantity} {inspection.unit.value}. {detail}"
                ),
                entity_type=EntityType.QC_INSPECTION,
                entity_id=inspection.id,
                impact=detection_impact,
                recommended_action=(
                    "Confirm the replacement batch is scheduled and check whether the "
                    "customer's date still holds."
                ),
                evidence=[
                    EvidenceItem(
                        kind=EvidenceKind.RECORD,
                        label="Inspection result",
                        detail=detail,
                        data={
                            "outcome": inspection.outcome.value,
                            "rejected": str(inspection.rejected_quantity),
                            "unit": inspection.unit.value,
                        },
                        entity_type=EntityType.QC_INSPECTION,
                        entity_id=inspection.id,
                    )
                ]
                + (
                    [
                        EvidenceItem(
                            kind=EvidenceKind.RECORD,
                            label=f"Batch {batch.code}",
                            detail=(
                                f"Status {batch.status.value}; output "
                                f"{batch.output_quantity} {batch.unit.value}; estimate "
                                f"{_date_text(batch.estimated_completion)}."
                            ),
                            entity_type=EntityType.PRODUCTION_BATCH,
                            entity_id=batch.id,
                        )
                    ]
                    if batch
                    else []
                ),
                detection_metrics={
                    "outcome": inspection.outcome.value,
                    "rejected_quantity": str(inspection.rejected_quantity),
                    "unit": inspection.unit.value,
                },
                qc_inspection_id=inspection.id,
                production_batch_id=batch.id if batch else None,
                sales_order_id=affected[0].sales_order_id if affected else None,
                customer_id=affected[0].customer_id if affected else None,
                source_event_at=inspection.inspected_at,
                urgency_days=7,
            )
        )
    return out


def detect_shipment_delay(session: Session) -> list[Detection]:
    out: list[Detection] = []
    today = clock.today()
    for shipment in shipments.delayed_shipments(session, as_of=today):
        assert shipment.expected_delivery_date is not None
        days_late = (today - shipment.expected_delivery_date).days
        if days_late <= settings.shipment_delay_grace_days:
            continue
        affected = impact.orders_for_lines(
            session, [line.sales_order_line_id for line in shipment.lines]
        )
        severity = Severity.HIGH if days_late >= 3 else Severity.MEDIUM
        detection_impact = Impact(
            headline=(
                f"Shipment {shipment.number} to {shipment.customer.name} is "
                f"{days_late} day(s) past its expected delivery date."
            ),
            metrics=[impact.days_metric("days_late", "Days overdue", days_late)],
            affected_orders=affected,
        )
        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.SHIPMENT_DELAY.value}:{shipment.id}",
                exception_type=ExceptionType.SHIPMENT_DELAY,
                severity=severity,
                title=f"Shipment {shipment.number} overdue",
                summary=(
                    f"Dispatched {_date_text(shipment.dispatch_date)}, "
                    f"expected {shipment.expected_delivery_date.isoformat()}, not yet "
                    f"confirmed delivered."
                ),
                entity_type=EntityType.SHIPMENT,
                entity_id=shipment.id,
                impact=detection_impact,
                recommended_action=(
                    "Chase the carrier for a status update and tell the customer the "
                    "revised arrival."
                ),
                evidence=[
                    EvidenceItem(
                        kind=EvidenceKind.RECORD,
                        label="Shipment record",
                        detail=(
                            f"Carrier {shipment.carrier or 'not recorded'}; reference "
                            f"{shipment.tracking_reference or 'not recorded'}."
                        ),
                        entity_type=EntityType.SHIPMENT,
                        entity_id=shipment.id,
                    )
                ],
                detection_metrics={"days_late": days_late},
                shipment_id=shipment.id,
                customer_id=shipment.customer_id,
                urgency_days=days_late,
            )
        )
    return out


def detect_inventory_anomalies(session: Session) -> list[Detection]:
    """INVENTORY_ANOMALY — the ledger and the stored balance disagree, or a lot
    is impossible (negative / reserved beyond existence)."""
    from textileops.services.inventory import ledger_discrepancies

    out: list[Detection] = []
    for discrepancy in ledger_discrepancies(session):
        lot_id = discrepancy["lot_id"]
        detection_impact = Impact(
            headline=(
                f"Lot {discrepancy['lot_code']} shows {discrepancy['stored_on_hand']} "
                f"{discrepancy['unit']} but its movements total "
                f"{discrepancy['ledger_on_hand']}."
            ),
            metrics=[
                Metric(
                    key="difference",
                    label="Unexplained difference",
                    value=str(discrepancy["difference"]),
                    unit=str(discrepancy["unit"]),
                )
            ],
        )
        out.append(
            Detection(
                dedupe_key=f"{ExceptionType.INVENTORY_ANOMALY.value}:{lot_id}",
                exception_type=ExceptionType.INVENTORY_ANOMALY,
                severity=Severity.HIGH,
                title=f"Stock ledger mismatch on lot {discrepancy['lot_code']}",
                summary=(
                    "The recorded on-hand quantity does not equal the sum of this lot's "
                    "movements. Inventory figures involving this lot cannot be trusted "
                    "until it is reconciled."
                ),
                entity_type=EntityType.INVENTORY_LOT,
                entity_id=lot_id,  # type: ignore[arg-type]
                impact=detection_impact,
                recommended_action=(
                    "Physically count the lot and post an adjustment movement with the "
                    "reason, rather than editing the balance."
                ),
                evidence=[
                    EvidenceItem(
                        kind=EvidenceKind.CALCULATION,
                        label="Ledger reconciliation",
                        detail=(
                            f"Stored {discrepancy['stored_on_hand']} vs ledger "
                            f"{discrepancy['ledger_on_hand']} {discrepancy['unit']}."
                        ),
                        data={k: str(v) for k, v in discrepancy.items()},
                        entity_type=EntityType.INVENTORY_LOT,
                        entity_id=lot_id,  # type: ignore[arg-type]
                    )
                ],
                detection_metrics={k: str(v) for k, v in discrepancy.items()},
                urgency_days=3,
            )
        )
    return out


DETECTORS = (
    detect_order_risk,
    detect_material_shortage,
    detect_po_issues,
    detect_production_delay,
    detect_qc_failures,
    detect_shipment_delay,
    detect_inventory_anomalies,
)


# =============================================================================
# Engine
# =============================================================================


def priority_score(detection: Detection, *, customer_tier: int = 5) -> int:
    """Rank for the attention queue. Deterministic and explainable:
    severity dominates, then urgency in days, then customer importance."""
    severity_component = (4 - SEVERITY_RANK[detection.severity]) * 1000
    urgency_component = min(detection.urgency_days, 60) * 10
    customer_component = (9 - customer_tier) * 5
    order_component = 25 if detection.sales_order_id else 0
    return severity_component + urgency_component + customer_component + order_component


def run(session: Session, *, request_id: str | None = None) -> EngineResult:
    """Recompute every exception. Idempotent: safe to run as often as you like."""
    # Two passes must not overlap. ``workers/tasks.py`` enqueues a recompute on
    # every processed document and message with no idempotency key, so
    # overlapping passes are the normal case, not a rare one.
    advisory_xact_lock(session, "exception_engine.run")
    result = EngineResult()
    detections: list[Detection] = []
    for detector in DETECTORS:
        detections.extend(detector(session))

    seen_keys = {d.dedupe_key for d in detections}
    now = clock.now()

    existing_by_key = {
        exception.dedupe_key: exception
        for exception in session.scalars(
            select(OperationalException).where(
                OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES)
            )
        ).all()
    }

    for detection in detections:
        customer_tier = 5
        if detection.customer_id:
            customer = session.get(Customer, detection.customer_id)
            if customer:
                customer_tier = customer.priority_tier
        score = priority_score(detection, customer_tier=customer_tier)

        existing = existing_by_key.get(detection.dedupe_key)
        if existing is None:
            existing = session.scalar(
                select(OperationalException).where(
                    OperationalException.dedupe_key == detection.dedupe_key
                )
            )
        if existing is not None and existing.status == ExceptionStatus.DISMISSED:
            # Someone looked at this and decided it was not worth acting on.
            # Re-raising it on the next ingestion would train them to ignore the
            # queue. It stays dismissed unless the condition materially worsens.
            if not _materially_worse(existing, detection):
                result.unchanged += 1
                existing.last_evaluated_at = now
                continue
            existing.status = ExceptionStatus.OPEN
            existing.dismissed_at = None
            # Whoever closed it no longer closed it. The HTTP route already
            # clears this on reopen; these two paths did not, so an
            # engine-reopened exception came back as `status: open` still
            # naming the person who had dismissed it.
            existing.resolved_by_user_id = None
            existing.occurrence_count += 1
            existing.resolution_note = (
                "Reopened: the condition got worse after it was dismissed."
            )
        elif existing is not None and existing.status == ExceptionStatus.RESOLVED:
            # A resolved issue that is happening again reopens in place, so the
            # history of a recurring problem stays in one record.
            existing.status = ExceptionStatus.OPEN
            existing.resolved_at = None
            existing.auto_resolved = False
            existing.resolved_by_user_id = None
            existing.occurrence_count += 1

        if existing is None:
            exception = OperationalException(
                code=_next_code(session),
                exception_type=detection.exception_type,
                severity=detection.severity,
                status=ExceptionStatus.OPEN,
                dedupe_key=detection.dedupe_key,
                title=detection.title,
                summary=detection.summary,
                recommended_action=detection.recommended_action,
                first_detected_at=now,
                detected_at=now,
                last_evaluated_at=now,
                source_event_at=detection.source_event_at,
                entity_type=detection.entity_type,
                entity_id=detection.entity_id,
                customer_id=detection.customer_id,
                supplier_id=detection.supplier_id,
                sales_order_id=detection.sales_order_id,
                purchase_order_id=detection.purchase_order_id,
                production_batch_id=detection.production_batch_id,
                material_id=detection.material_id,
                shipment_id=detection.shipment_id,
                qc_inspection_id=detection.qc_inspection_id,
                impact=detection.impact.to_dict(),
                detection_metrics=detection.detection_metrics,
                priority_score=score,
            )
            session.add(exception)
            session.flush()
            _replace_evidence(session, exception, detection)
            result.created.append(exception.code)

            record_audit(
                session,
                action="exception.detected",
                entity_type=EntityType.EXCEPTION,
                entity_id=exception.id,
                summary=f"{exception.code} {exception.exception_type.value}: {exception.title}",
                actor_type="system",
                actor_label="exception-engine",
                request_id=request_id,
                exception_id=exception.id,
                after={"severity": exception.severity.value},
            )
            detection_latency = clock.elapsed_ms(detection.source_event_at, now)
            record_metric(
                session,
                event_type=BusinessEventType.EXCEPTION_DETECTED,
                entity_type=EntityType.EXCEPTION,
                entity_id=exception.id,
                duration_ms=detection_latency,
                payload={
                    "exception_type": exception.exception_type.value,
                    "severity": exception.severity.value,
                },
            )
        else:
            changed = (
                existing.severity != detection.severity
                or existing.summary != detection.summary
                or existing.title != detection.title
                or existing.priority_score != score
            )
            existing.severity = detection.severity
            existing.title = detection.title
            existing.summary = detection.summary
            existing.recommended_action = detection.recommended_action
            existing.impact = detection.impact.to_dict()
            existing.detection_metrics = detection.detection_metrics
            existing.priority_score = score
            existing.last_evaluated_at = now
            if detection.source_event_at:
                existing.source_event_at = detection.source_event_at
            _replace_evidence(session, existing, detection)
            if changed:
                existing.occurrence_count += 1
                result.updated.append(existing.code)
            else:
                result.unchanged += 1

    # --- auto-resolution --------------------------------------------------
    for key, exception in existing_by_key.items():
        if key in seen_keys:
            continue
        # This map was loaded at the top of the pass. An operator who resolved
        # or dismissed the exception while the pass was running holds the more
        # recent truth, and writing our stale copy over it would silently
        # replace their decision with "automatically resolved".
        session.refresh(exception)
        if exception.status not in ACTIVE_EXCEPTION_STATUSES:
            result.unchanged += 1
            continue
        exception.status = ExceptionStatus.RESOLVED
        exception.resolved_at = now
        exception.auto_resolved = True
        exception.last_evaluated_at = now
        exception.resolution_note = (
            "Automatically resolved: the underlying condition is no longer detected."
        )
        result.auto_resolved.append(exception.code)
        record_audit(
            session,
            action="exception.auto_resolved",
            entity_type=EntityType.EXCEPTION,
            entity_id=exception.id,
            summary=f"{exception.code} auto-resolved; condition no longer present.",
            actor_type="system",
            actor_label="exception-engine",
            exception_id=exception.id,
        )
        record_metric(
            session,
            event_type=BusinessEventType.EXCEPTION_RESOLVED,
            entity_type=EntityType.EXCEPTION,
            entity_id=exception.id,
            duration_ms=clock.elapsed_ms(exception.first_detected_at, now),
            payload={"auto": True, "exception_type": exception.exception_type.value},
        )

    session.flush()
    logger.info("exception_engine_run", **result.summary())
    return result


def _materially_worse(
    existing: OperationalException, detection: Detection
) -> bool:
    """Has a dismissed condition deteriorated enough to be worth raising again?"""
    if SEVERITY_RANK[detection.severity] < SEVERITY_RANK[existing.severity]:
        return True
    previous_days = (existing.detection_metrics or {}).get("days_late") or (
        existing.detection_metrics or {}
    ).get("delay_days") or (existing.detection_metrics or {}).get("days_short")
    current_days = (
        detection.detection_metrics.get("days_late")
        or detection.detection_metrics.get("delay_days")
        or detection.detection_metrics.get("days_short")
    )
    if previous_days is not None and current_days is not None:
        try:
            return int(current_days) > int(previous_days)
        except (TypeError, ValueError):
            return False
    return False


def _replace_evidence(
    session: Session, exception: OperationalException, detection: Detection
) -> None:
    """Evidence always reflects the latest evaluation, so it can never drift
    away from the numbers shown next to it."""
    for stored in list(exception.evidence):
        session.delete(stored)
    session.flush()
    for order_index, item in enumerate(detection.evidence):
        session.add(
            ExceptionEvidence(
                exception_id=exception.id,
                kind=item.kind,
                label=item.label,
                detail=item.detail,
                data=item.data,
                entity_type=item.entity_type,
                entity_id=item.entity_id,
                message_id=item.message_id,
                source_document_id=item.source_document_id,
                recorded_at=clock.now(),
                sort_order=order_index,
            )
        )


def _next_code(session: Session) -> str:
    count = session.scalar(select(func.count(OperationalException.id))) or 0
    candidate = count + 1
    while session.scalar(
        select(OperationalException.id).where(
            OperationalException.code == f"EXC-{candidate:05d}"
        )
    ):
        candidate += 1
    return f"EXC-{candidate:05d}"
