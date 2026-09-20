"""Read-only integrity checks over a whole TextileOps database.

Every check here states a relationship that must hold between two things the
system maintains separately. Where they disagree, one of them is wrong — and
an operations system that has quietly drifted is worse than one that is
visibly broken, because people keep acting on the numbers.

Strictly read-only. This is meant to be safe to point at a production database
at any time, including while the workers are running, so nothing here writes,
locks or repairs. Reporting a discrepancy is the whole job; deciding what the
truth was is a person's.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from textileops.models.actions import ActionProposal, Approval, Execution
from textileops.models.enums import (
    ApprovalDecision,
    EntityType,
    ExceptionStatus,
    ExecutionStatus,
    LotStatus,
    MovementType,
    ProposalStatus,
    QCOutcome,
    ReservationStatus,
    SalesOrderStatus,
    ShipmentStatus,
)
from textileops.models.exceptions import OperationalException
from textileops.models.intake import ExtractedFact
from textileops.models.inventory import (
    InventoryLot,
    InventoryMovement,
    InventoryReservation,
)
from textileops.models.logistics import Shipment, ShipmentLine
from textileops.models.procurement import (
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptCorrection,
)
from textileops.models.quality import QCInspection
from textileops.models.sales import SalesOrder, SalesOrderLine

ZERO = Decimal("0")


@dataclass
class Finding:
    """One thing that disagrees with something else."""

    check: str
    severity: str  # "critical" | "high" | "medium"
    entity: str
    detail: str
    values: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "entity": self.entity,
            "detail": self.detail,
            "values": {k: str(v) for k, v in self.values.items()},
        }


@dataclass
class IntegrityReport:
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    rows_examined: int = 0
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None

    @property
    def ok(self) -> bool:
        return not self.findings

    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks_run": self.checks_run,
            "rows_examined": self.rows_examined,
            "counts_by_severity": self.by_severity(),
            "findings": [f.to_dict() for f in self.findings],
            "duration_seconds": (
                round((self.finished_at - self.started_at).total_seconds(), 3)
                if self.started_at and self.finished_at
                else None
            ),
        }


# --- Individual checks --------------------------------------------------------


def _check_lot_ledger(session: Session, report: IntegrityReport) -> None:
    """A lot's stored balance must equal the sum of its own movements.

    The single most important relationship in the system. Every coverage,
    shortage and promised-date figure is computed from the stored balance, so a
    balance that has drifted from its history is a number nothing can explain.
    """
    ledger = (
        select(
            InventoryMovement.lot_id,
            func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO).label("total"),
        )
        .group_by(InventoryMovement.lot_id)
        .subquery()
    )
    rows = session.execute(
        select(InventoryLot, ledger.c.total)
        .outerjoin(ledger, ledger.c.lot_id == InventoryLot.id)
        .where(
            func.coalesce(ledger.c.total, ZERO) != InventoryLot.quantity_on_hand
        )
    ).all()
    for lot, total in rows:
        report.findings.append(
            Finding(
                check="lot_ledger",
                severity="critical",
                entity=lot.lot_code,
                detail=(
                    "The stored balance does not equal the sum of this lot's "
                    "movements. Stock has moved without a movement to explain it, "
                    "or a movement was written without the balance following."
                ),
                values={
                    "stored": lot.quantity_on_hand,
                    "ledger": total or ZERO,
                    "difference": lot.quantity_on_hand - (total or ZERO),
                },
            )
        )


def _check_no_negative_stock(session: Session, report: IntegrityReport) -> None:
    for lot in session.scalars(
        select(InventoryLot).where(InventoryLot.quantity_on_hand < ZERO)
    ).all():
        report.findings.append(
            Finding(
                check="negative_stock",
                severity="critical",
                entity=lot.lot_code,
                detail="A lot holds a negative quantity, which is not a physical state.",
                values={"on_hand": lot.quantity_on_hand},
            )
        )


def _check_lot_status_matches_balance(session: Session, report: IntegrityReport) -> None:
    for lot in session.scalars(
        select(InventoryLot).where(
            InventoryLot.status == LotStatus.CONSUMED,
            InventoryLot.quantity_on_hand > ZERO,
        )
    ).all():
        report.findings.append(
            Finding(
                check="lot_status_balance",
                severity="high",
                entity=lot.lot_code,
                detail=(
                    "The lot is marked consumed but still holds stock, so this "
                    "quantity is invisible to every availability query."
                ),
                values={"on_hand": lot.quantity_on_hand},
            )
        )


def _check_po_receipt_totals(session: Session, report: IntegrityReport) -> None:
    """The line's received figure must equal its receipts less its corrections."""
    for line in session.scalars(select(PurchaseOrderLine)).all():
        received = sum((r.accepted_quantity for r in line.receipts), ZERO)
        corrected = sum(
            (c.accepted_delta for r in line.receipts for c in r.corrections), ZERO
        )
        expected = received - corrected
        if line.received_quantity != expected:
            report.findings.append(
                Finding(
                    check="po_receipt_totals",
                    severity="critical",
                    entity=f"{line.purchase_order.number} line {line.line_no}",
                    detail=(
                        "The line's received quantity disagrees with its own "
                        "receipts and corrections."
                    ),
                    values={
                        "line_says": line.received_quantity,
                        "receipts": received,
                        "corrections": corrected,
                        "expected": expected,
                    },
                )
            )
        if line.received_quantity < ZERO:
            report.findings.append(
                Finding(
                    check="po_receipt_totals",
                    severity="critical",
                    entity=f"{line.purchase_order.number} line {line.line_no}",
                    detail="A line records a negative received quantity.",
                    values={"received": line.received_quantity},
                )
            )


def _check_no_over_shipping(session: Session, report: IntegrityReport) -> None:
    for line in session.scalars(
        select(SalesOrderLine).where(
            SalesOrderLine.shipped_quantity > SalesOrderLine.quantity
        )
    ).all():
        report.findings.append(
            Finding(
                check="over_shipped",
                severity="critical",
                entity=f"{line.sales_order.number} line {line.line_no}",
                detail=(
                    "More has shipped than was ordered. That is cloth out of the "
                    "building against no order, and usually invoiced twice."
                ),
                values={
                    "ordered": line.quantity,
                    "shipped": line.shipped_quantity,
                    "excess": line.shipped_quantity - line.quantity,
                },
            )
        )


def _check_no_over_production_credit(session: Session, report: IntegrityReport) -> None:
    for line in session.scalars(
        select(SalesOrderLine).where(
            SalesOrderLine.produced_quantity > SalesOrderLine.quantity
        )
    ).all():
        report.findings.append(
            Finding(
                check="over_produced_credit",
                severity="high",
                entity=f"{line.sales_order.number} line {line.line_no}",
                detail=(
                    "The line is credited with more production than it ordered, "
                    "which makes its outstanding quantity negative."
                ),
                values={"ordered": line.quantity, "produced": line.produced_quantity},
            )
        )


def _check_reservations(session: Session, report: IntegrityReport) -> None:
    duplicates = session.execute(
        select(
            InventoryReservation.production_batch_id,
            InventoryReservation.material_id,
            func.count(InventoryReservation.id).label("n"),
        )
        .where(
            InventoryReservation.status == ReservationStatus.ACTIVE,
            InventoryReservation.production_batch_id.is_not(None),
        )
        .group_by(
            InventoryReservation.production_batch_id, InventoryReservation.material_id
        )
        .having(func.count(InventoryReservation.id) > 1)
    ).all()
    for batch_id, material_id, count in duplicates:
        report.findings.append(
            Finding(
                check="duplicate_reservation",
                severity="high",
                entity=f"batch {batch_id}",
                detail=(
                    "A batch holds more than one active reservation for the same "
                    "material, so it has committed the same stock to itself twice "
                    "and halved what everyone else can see."
                ),
                values={"material_id": material_id, "reservations": count},
            )
        )

    unstamped = session.scalars(
        select(InventoryReservation).where(
            InventoryReservation.status == ReservationStatus.RELEASED,
            InventoryReservation.released_at.is_(None),
        )
    ).all()
    for reservation in unstamped:
        report.findings.append(
            Finding(
                check="reservation_released_unstamped",
                severity="medium",
                entity=str(reservation.id),
                detail=(
                    "A released reservation has no released_at, so anything "
                    "reading timestamps still sees it as live."
                ),
            )
        )


def _check_rejected_stock_not_sellable(session: Session, report: IntegrityReport) -> None:
    """Cloth an inspection rejected must have left the books.

    This used to assert that the batch's output lot was *not* available, which
    was right only while a rejection quarantined the whole lot. It does not
    any more, and should not: an inspection that accepts 700 of 1,000 metres
    is saying the 700 are good, and stranding them helps nobody.

    What has to be true is narrower and stronger — the rejected quantity was
    actually scrapped. A REWORK is excluded: that cloth is expected back from
    the dyehouse, so it is quarantined rather than destroyed.
    """
    for inspection in session.scalars(
        select(QCInspection).where(QCInspection.rejected_quantity > ZERO)
    ).all():
        if inspection.outcome == QCOutcome.REWORK:
            continue
        scrapped = session.scalar(
            select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
                InventoryMovement.movement_type == MovementType.SCRAP,
                InventoryMovement.reference_type == EntityType.QC_INSPECTION,
                InventoryMovement.reference_id == inspection.id,
            )
        ) or ZERO
        removed = -scrapped
        if removed >= inspection.rejected_quantity:
            continue
        report.findings.append(
            Finding(
                check="rejected_stock_available",
                severity="high",
                entity=inspection.code,
                detail=(
                    "The inspection rejected cloth that was never scrapped, so "
                    "it is still on the books and can still be shipped."
                ),
                values={
                    "rejected": inspection.rejected_quantity,
                    "scrapped": removed,
                    "short_by": inspection.rejected_quantity - removed,
                },
            )
        )


def _check_approval_execution_consistency(
    session: Session, report: IntegrityReport
) -> None:
    """An execution needs an approval; an approved proposal needs one approver."""
    executed = session.scalars(
        select(Execution).where(
            Execution.status.in_(
                (ExecutionStatus.SUCCEEDED, ExecutionStatus.AWAITING_EXTERNAL)
            )
        )
    ).all()
    for execution in executed:
        proposal = session.get(ActionProposal, execution.action_proposal_id)
        if proposal is None:
            report.findings.append(
                Finding(
                    check="execution_without_proposal",
                    severity="critical",
                    entity=str(execution.id),
                    detail="An execution exists with no proposal behind it.",
                )
            )
            continue
        approvals = [
            a for a in proposal.approvals if a.decision == ApprovalDecision.APPROVED
        ]
        if not approvals:
            report.findings.append(
                Finding(
                    check="execution_without_approval",
                    severity="critical",
                    entity=proposal.code,
                    detail=(
                        "An action was carried out with no approval recorded. "
                        "Every consequential action must pass through "
                        "proposal, approval, execution."
                    ),
                )
            )
        if len(approvals) > 1:
            report.findings.append(
                Finding(
                    check="multiple_approvals",
                    severity="high",
                    entity=proposal.code,
                    detail=(
                        "More than one approval is recorded, so 'who authorised "
                        "this?' has more than one answer."
                    ),
                    values={"approvals": len(approvals)},
                )
            )

    stale = session.scalars(
        select(ActionProposal).where(ActionProposal.status == ProposalStatus.APPROVED)
    ).all()
    for proposal in stale:
        succeeded = [
            e for e in proposal.executions if e.status == ExecutionStatus.SUCCEEDED
        ]
        if succeeded:
            report.findings.append(
                Finding(
                    check="proposal_status_behind_execution",
                    severity="high",
                    entity=proposal.code,
                    detail=(
                        "The proposal still reads APPROVED although it has already "
                        "run, so the queue is offering completed work for approval."
                    ),
                )
            )


def _check_exception_identity(session: Session, report: IntegrityReport) -> None:
    """One open exception per underlying condition."""
    duplicates = session.execute(
        select(OperationalException.dedupe_key, func.count(OperationalException.id))
        .where(
            OperationalException.status.in_(
                (
                    ExceptionStatus.OPEN,
                    ExceptionStatus.INVESTIGATING,
                    ExceptionStatus.ACTION_PROPOSED,
                )
            )
        )
        .group_by(OperationalException.dedupe_key)
        .having(func.count(OperationalException.id) > 1)
    ).all()
    for key, count in duplicates:
        report.findings.append(
            Finding(
                check="duplicate_open_exception",
                severity="high",
                entity=key,
                detail=(
                    "The same condition is open more than once, so the queue "
                    "overstates how much is wrong."
                ),
                values={"open": count},
            )
        )

    closed_without_reason = session.scalars(
        select(OperationalException).where(
            OperationalException.status == ExceptionStatus.RESOLVED,
            OperationalException.auto_resolved.is_(False),
            OperationalException.resolved_by_user_id.is_(None),
        )
    ).all()
    for exception in closed_without_reason:
        report.findings.append(
            Finding(
                check="resolution_without_actor",
                severity="medium",
                entity=exception.code,
                detail=(
                    "Resolved by a person, but no person is recorded. Either the "
                    "actor was lost or this was in fact an automatic resolution."
                ),
            )
        )


def _check_delivery_claims(session: Session, report: IntegrityReport) -> None:
    """An order claiming delivery needs a shipment that confirms it."""
    delivered = session.scalars(
        select(SalesOrder).where(SalesOrder.status == SalesOrderStatus.DELIVERED)
    ).all()
    for order in delivered:
        carrying = session.scalars(
            select(Shipment)
            .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.id)
            .join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
            .where(SalesOrderLine.sales_order_id == order.id)
            .distinct()
        ).all()
        live = [s for s in carrying if s.status != ShipmentStatus.CANCELLED]
        unarrived = [s for s in live if s.actual_delivery_date is None]
        if not live:
            report.findings.append(
                Finding(
                    check="delivery_without_shipment",
                    severity="high",
                    entity=order.number,
                    detail="Marked delivered, but no shipment carries this order.",
                )
            )
        elif unarrived:
            report.findings.append(
                Finding(
                    check="delivery_without_arrival",
                    severity="high",
                    entity=order.number,
                    detail=(
                        "Marked delivered while a shipment carrying it has no "
                        "confirmed arrival date. This figure feeds the on-time "
                        "percentage."
                    ),
                    values={"shipments": ", ".join(s.number for s in unarrived)},
                )
            )


def _check_orphan_provenance(session: Session, report: IntegrityReport) -> None:
    """A derived belief must still point at what caused it."""
    orphans = session.scalars(
        select(ExtractedFact).where(
            ExtractedFact.source_document_id.is_(None),
            ExtractedFact.message_id.is_(None),
        )
    ).all()
    for fact in orphans:
        report.findings.append(
            Finding(
                check="fact_without_source",
                severity="high",
                entity=str(fact.id),
                detail=(
                    "An extracted fact has neither a document nor a message "
                    "behind it, so nothing explains where the claim came from."
                ),
            )
        )


CHECKS = [
    ("lot_ledger", _check_lot_ledger),
    ("negative_stock", _check_no_negative_stock),
    ("lot_status_balance", _check_lot_status_matches_balance),
    ("po_receipt_totals", _check_po_receipt_totals),
    ("over_shipped", _check_no_over_shipping),
    ("over_produced_credit", _check_no_over_production_credit),
    ("reservations", _check_reservations),
    ("rejected_stock_available", _check_rejected_stock_not_sellable),
    ("approval_execution", _check_approval_execution_consistency),
    ("exception_identity", _check_exception_identity),
    ("delivery_claims", _check_delivery_claims),
    ("orphan_provenance", _check_orphan_provenance),
]


def run(session: Session, *, only: list[str] | None = None) -> IntegrityReport:
    """Run every check. Read-only; safe against a live database."""
    from textileops.services import clock

    report = IntegrityReport(started_at=clock.now())
    for name, check in CHECKS:
        if only and name not in only:
            continue
        check(session, report)
        report.checks_run.append(name)
    report.rows_examined = sum(
        session.scalar(select(func.count()).select_from(model)) or 0
        for model in (
            InventoryLot,
            InventoryMovement,
            PurchaseOrderLine,
            PurchaseOrderReceipt,
            PurchaseOrderReceiptCorrection,
            SalesOrderLine,
            InventoryReservation,
            ActionProposal,
            Approval,
            Execution,
            OperationalException,
        )
    )
    report.finished_at = clock.now()
    return report


__all__ = ["CHECKS", "Finding", "IntegrityReport", "run"]
