"""The action system: ActionProposal → Approval → Execution → AuditEvent.

This is the only route by which anything consequential happens. AI may create
proposals and write drafts; it cannot approve and it cannot execute.

Two execution modes, and the difference is deliberate honesty:

``INTERNAL``
    TextileOps owns the effect (schedule a batch, change a priority, move a
    reservation, raise a draft PO). It is executed deterministically here.

``EXTERNAL_DRAFT``
    The effect belongs to a system we are not connected to — email, WhatsApp, a
    carrier portal. TextileOps produces a copyable draft, records the approval,
    and marks the execution ``awaiting_external``. **It never claims to have
    sent anything.**
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.db import lock_row
from textileops.core.errors import (
    ConflictError,
    IllegalStateTransition,
    NotFoundError,
    PermissionError_,
    PilotModeRestriction,
    ValidationError,
)
from textileops.core.logging import get_logger
from textileops.core.units import parse_unit, quantize
from textileops.models.actions import ActionProposal, Approval, Execution
from textileops.models.enums import (
    ActionType,
    ApprovalDecision,
    BusinessEventType,
    EntityType,
    ExceptionStatus,
    ExecutionMode,
    ExecutionStatus,
    ProposalOrigin,
    ProposalStatus,
    QCOutcome,
    UserRole,
)
from textileops.models.exceptions import OperationalException
from textileops.models.inventory import InventoryReservation
from textileops.models.org import User
from textileops.models.procurement import PurchaseOrder, PurchaseOrderLine
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection
from textileops.services import clock, production
from textileops.services.audit import record_audit, record_metric

logger = get_logger(__name__)
ZERO = Decimal("0")

#: Which actions TextileOps can actually carry out itself.
EXECUTION_MODES: dict[ActionType, ExecutionMode] = {
    ActionType.CONTACT_SUPPLIER: ExecutionMode.EXTERNAL_DRAFT,
    ActionType.REQUEST_REVISED_ETA: ExecutionMode.EXTERNAL_DRAFT,
    ActionType.NOTIFY_CUSTOMER: ExecutionMode.EXTERNAL_DRAFT,
    ActionType.EXPEDITE_SHIPMENT: ExecutionMode.EXTERNAL_DRAFT,
    ActionType.SCHEDULE_REPLACEMENT_BATCH: ExecutionMode.INTERNAL,
    ActionType.REQUEST_QC_REINSPECTION: ExecutionMode.INTERNAL,
    ActionType.CHANGE_PRODUCTION_PRIORITY: ExecutionMode.INTERNAL,
    ActionType.REALLOCATE_INVENTORY: ExecutionMode.INTERNAL,
    ActionType.RAISE_PURCHASE_ORDER: ExecutionMode.INTERNAL,
    ActionType.ACKNOWLEDGE_ONLY: ExecutionMode.INTERNAL,
}


# --- Payload contracts --------------------------------------------------------


class MessageDraftPayload(BaseModel):
    """Drafts are addressed to a recorded contact, never to a free-text address
    supplied by an ingested document."""

    recipient_kind: str = Field(pattern="^(supplier|customer)$")
    recipient_id: uuid.UUID
    purchase_order_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    shipment_id: uuid.UUID | None = None


class ReplacementBatchPayload(BaseModel):
    production_batch_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit: str
    duration_days: int = Field(ge=1, le=120)


class ReinspectionPayload(BaseModel):
    qc_inspection_id: uuid.UUID
    note: str | None = None


class PriorityPayload(BaseModel):
    production_batch_id: uuid.UUID
    priority: int = Field(ge=1, le=9)


class ReallocatePayload(BaseModel):
    reservation_id: uuid.UUID
    to_sales_order_line_id: uuid.UUID | None = None
    to_production_batch_id: uuid.UUID | None = None


class RaisePurchaseOrderPayload(BaseModel):
    supplier_id: uuid.UUID
    material_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit: str
    needed_by: dt.date


class AcknowledgePayload(BaseModel):
    note: str | None = None


PAYLOAD_MODELS: dict[ActionType, type[BaseModel]] = {
    ActionType.CONTACT_SUPPLIER: MessageDraftPayload,
    ActionType.REQUEST_REVISED_ETA: MessageDraftPayload,
    ActionType.NOTIFY_CUSTOMER: MessageDraftPayload,
    ActionType.EXPEDITE_SHIPMENT: MessageDraftPayload,
    ActionType.SCHEDULE_REPLACEMENT_BATCH: ReplacementBatchPayload,
    ActionType.REQUEST_QC_REINSPECTION: ReinspectionPayload,
    ActionType.CHANGE_PRODUCTION_PRIORITY: PriorityPayload,
    ActionType.REALLOCATE_INVENTORY: ReallocatePayload,
    ActionType.RAISE_PURCHASE_ORDER: RaisePurchaseOrderPayload,
    ActionType.ACKNOWLEDGE_ONLY: AcknowledgePayload,
}


def validate_payload(action_type: ActionType, payload: dict[str, Any]) -> BaseModel:
    model = PAYLOAD_MODELS[action_type]
    try:
        return model.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(
            f"Proposal payload is not valid for {action_type.value}.",
            details={"errors": exc.errors(include_url=False)},
        )


# --- Creation -----------------------------------------------------------------


def create_proposal(
    session: Session,
    *,
    action_type: ActionType,
    title: str,
    rationale: str,
    payload: dict[str, Any],
    origin: ProposalOrigin,
    exception_id: uuid.UUID | None = None,
    draft_subject: str | None = None,
    draft_body: str | None = None,
    created_by_user_id: uuid.UUID | None = None,
    ai_request_id: str | None = None,
    model: str | None = None,
    expires_in_days: int | None = 14,
) -> ActionProposal:
    validate_payload(action_type, payload)
    mode = EXECUTION_MODES[action_type]
    if mode == ExecutionMode.EXTERNAL_DRAFT and not draft_body:
        raise ValidationError(
            f"{action_type.value} produces an external communication and therefore "
            "requires a draft the operator can review."
        )

    proposal = ActionProposal(
        code=_next_code(session),
        exception_id=exception_id,
        action_type=action_type,
        execution_mode=mode,
        status=ProposalStatus.PENDING_APPROVAL,
        origin=origin,
        title=title,
        rationale=rationale,
        payload=_jsonable(payload),
        draft_subject=draft_subject,
        draft_body=draft_body,
        draft_original_body=draft_body,
        created_by_user_id=created_by_user_id,
        ai_request_id=ai_request_id,
        model=model,
        expires_at=(
            clock.now() + dt.timedelta(days=expires_in_days) if expires_in_days else None
        ),
    )
    session.add(proposal)
    session.flush()

    if exception_id:
        exception = session.get(OperationalException, exception_id)
        if exception and exception.status in (
            ExceptionStatus.OPEN,
            ExceptionStatus.INVESTIGATING,
        ):
            exception.status = ExceptionStatus.ACTION_PROPOSED

    record_audit(
        session,
        action="proposal.created",
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        summary=f"{proposal.code} proposed: {title}",
        actor_type="ai" if origin == ProposalOrigin.AI_INVESTIGATION else (
            "user" if created_by_user_id else "system"
        ),
        actor_user_id=created_by_user_id,
        actor_label=model if origin == ProposalOrigin.AI_INVESTIGATION else None,
        action_proposal_id=proposal.id,
        exception_id=exception_id,
        after={"action_type": action_type.value, "execution_mode": mode.value},
    )
    record_metric(
        session,
        event_type=BusinessEventType.PROPOSAL_CREATED,
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        user_id=created_by_user_id,
        payload={"action_type": action_type.value, "origin": origin.value},
    )
    return proposal


def edit_draft(
    session: Session,
    proposal: ActionProposal,
    *,
    body: str,
    subject: str | None = None,
    user_id: uuid.UUID,
) -> ActionProposal:
    """Operators may rewrite an AI draft. We record that they did — it is one of
    the few honest signals of whether the drafting is actually any good."""
    if proposal.status != ProposalStatus.PENDING_APPROVAL:
        raise IllegalStateTransition("Only a pending proposal's draft can be edited.")
    changed = body != (proposal.draft_body or "")
    proposal.draft_body = body
    if subject is not None:
        proposal.draft_subject = subject
    if changed:
        proposal.draft_edited = True
        record_metric(
            session,
            event_type=BusinessEventType.PROPOSAL_DRAFT_EDITED,
            entity_type=EntityType.ACTION_PROPOSAL,
            entity_id=proposal.id,
            user_id=user_id,
        )
    return proposal


# --- Approval -----------------------------------------------------------------


def approve(
    session: Session,
    proposal: ActionProposal,
    *,
    user_id: uuid.UUID,
    note: str | None = None,
    modified_payload: dict[str, Any] | None = None,
    execute_now: bool = True,
) -> tuple[Approval, Execution | None]:
    # Lock the proposal before reading its status. Two operators clicking
    # Approve at the same moment otherwise both pass ``_assert_actionable``:
    # the audit trail ends up claiming two people each authorised the action,
    # and the loser's write puts the status back to APPROVED after the winner
    # set EXECUTED — so the queue shows work as still pending that has in fact
    # already run, inviting somebody to approve it a third time.
    lock_row(session, proposal)

    _assert_actionable(proposal)

    # Separation of duties, but only where it is meaningful. Most proposals
    # originate from the rule engine or an investigation and have no human
    # author, so there is nobody to separate from. When a *person* raised one,
    # a second person should approve it — otherwise "proposal, approval,
    # execution" is one person clicking twice, which is a log rather than a
    # control.
    #
    # A mill's operations desk can be two people, so this is not absolute:
    # an owner can approve their own proposal, because the alternative is a
    # business that cannot act on a Saturday.
    if (
        proposal.origin == ProposalOrigin.HUMAN
        and proposal.created_by_user_id is not None
        and proposal.created_by_user_id == user_id
    ):
        approver = session.get(User, user_id)
        if approver is None or approver.role != UserRole.OWNER:
            raise PermissionError_(
                f"{proposal.code} was raised by you. Somebody else needs to "
                "approve it — an approval by its own author is not a second "
                "pair of eyes. An owner may override this.",
                details={"proposal": proposal.code},
            )

    if modified_payload:
        validate_payload(proposal.action_type, modified_payload)
        proposal.payload = _jsonable(modified_payload)

    approval = Approval(
        action_proposal_id=proposal.id,
        decision=ApprovalDecision.APPROVED,
        decided_by_user_id=user_id,
        decided_at=clock.now(),
        note=note,
        modified_payload=_jsonable(modified_payload) if modified_payload else None,
    )
    session.add(approval)
    proposal.approvals.append(approval)
    proposal.status = ProposalStatus.APPROVED
    session.flush()

    record_audit(
        session,
        action="proposal.approved",
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        summary=f"{proposal.code} approved.",
        actor_type="user",
        actor_user_id=user_id,
        action_proposal_id=proposal.id,
        exception_id=proposal.exception_id,
        after={"note": note},
    )
    record_metric(
        session,
        event_type=BusinessEventType.PROPOSAL_APPROVED,
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        user_id=user_id,
        duration_ms=clock.elapsed_ms(proposal.created_at),
        payload={"action_type": proposal.action_type.value, "edited": proposal.draft_edited},
    )

    execution = execute(session, proposal, user_id=user_id) if execute_now else None
    return approval, execution


def reject(
    session: Session,
    proposal: ActionProposal,
    *,
    user_id: uuid.UUID,
    note: str | None = None,
) -> Approval:
    _assert_actionable(proposal)
    approval = Approval(
        action_proposal_id=proposal.id,
        decision=ApprovalDecision.REJECTED,
        decided_by_user_id=user_id,
        decided_at=clock.now(),
        note=note,
    )
    session.add(approval)
    proposal.approvals.append(approval)
    proposal.status = ProposalStatus.REJECTED
    record_audit(
        session,
        action="proposal.rejected",
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        summary=f"{proposal.code} rejected." + (f" {note}" if note else ""),
        actor_type="user",
        actor_user_id=user_id,
        action_proposal_id=proposal.id,
        exception_id=proposal.exception_id,
    )
    record_metric(
        session,
        event_type=BusinessEventType.PROPOSAL_REJECTED,
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        user_id=user_id,
        payload={"action_type": proposal.action_type.value, "note": note},
    )
    return approval


def _assert_actionable(proposal: ActionProposal) -> None:
    if proposal.status != ProposalStatus.PENDING_APPROVAL:
        raise IllegalStateTransition(
            f"Proposal {proposal.code} is {proposal.status.value}; only a proposal "
            "awaiting approval can be decided."
        )
    if proposal.expires_at and clock.now() > clock.ensure_utc(proposal.expires_at):
        proposal.status = ProposalStatus.EXPIRED
        raise ConflictError(f"Proposal {proposal.code} expired and must be re-proposed.")


# --- Execution ----------------------------------------------------------------


Executor = Callable[[Session, ActionProposal, BaseModel], dict[str, Any]]


def execute(
    session: Session, proposal: ActionProposal, *, user_id: uuid.UUID | None = None
) -> Execution:
    """Carry out an approved proposal exactly once.

    Calling this again for a proposal that already ran returns the original
    execution rather than repeating the effect — the worker queue is
    at-least-once, so a replay must be a no-op. A proposal whose execution
    *failed* may be retried, and that retry gets its own attempt record.
    """
    completed = [
        execution
        for execution in proposal.executions
        if execution.status
        in (ExecutionStatus.SUCCEEDED, ExecutionStatus.AWAITING_EXTERNAL)
    ]
    if completed:
        return completed[-1]

    if proposal.status not in (ProposalStatus.APPROVED, ProposalStatus.FAILED):
        raise IllegalStateTransition(
            f"Proposal {proposal.code} must be approved before it can be executed."
        )

    # In pilot mode an action needs a named person behind it, not merely a
    # status that says APPROVED. The status is a column; a person is a
    # decision, and during a pilot that distinction is the whole point.
    if settings.pilot_mode:
        approver = next(
            (
                approval
                for approval in proposal.approvals
                if approval.decision == ApprovalDecision.APPROVED
                and approval.decided_by_user_id is not None
            ),
            None,
        )
        if approver is None:
            raise PilotModeRestriction(
                f"Pilot mode: {proposal.code} has no recorded human approval, so "
                "TextileOps will not carry it out. Approve it in the proposals "
                "queue and it will run.",
                details={"proposal": proposal.code, "status": proposal.status.value},
            )

    attempt = len(proposal.executions) + 1
    key = f"proposal:{proposal.id}:attempt-{attempt}"
    existing = session.scalar(select(Execution).where(Execution.idempotency_key == key))
    if existing is not None:
        return existing

    execution = Execution(
        action_proposal_id=proposal.id,
        mode=proposal.execution_mode,
        status=ExecutionStatus.PENDING,
        attempted_at=clock.now(),
        idempotency_key=key,
        executed_by_user_id=user_id,
    )
    session.add(execution)
    # Keep the in-session collection consistent: a caller that inspects
    # ``proposal.executions`` must see this attempt without another round trip.
    proposal.executions.append(execution)
    session.flush()

    # The executor runs inside a SAVEPOINT. Without it, an executor that fails
    # half way (having already created a batch and its reservations, say)
    # leaves those writes in the session, the route commits them, and a retry
    # creates a second set.
    savepoint = session.begin_nested()
    try:
        payload = validate_payload(proposal.action_type, proposal.payload)
        if proposal.execution_mode == ExecutionMode.EXTERNAL_DRAFT:
            execution.status = ExecutionStatus.AWAITING_EXTERNAL
            execution.result = {
                "mode": "external_draft",
                "message": (
                    "Approved. TextileOps has no connected channel for this action, so "
                    "the draft below must be sent by a person. Nothing has been sent."
                ),
                "draft_subject": proposal.draft_subject,
                "draft_body": proposal.draft_body,
            }
            proposal.status = ProposalStatus.AWAITING_EXTERNAL
        else:
            executor = INTERNAL_EXECUTORS[proposal.action_type]
            execution.result = executor(session, proposal, payload)
            execution.status = ExecutionStatus.SUCCEEDED
            execution.completed_at = clock.now()
            proposal.status = ProposalStatus.EXECUTED
        savepoint.commit()
    except Exception as exc:
        savepoint.rollback()
        execution.status = ExecutionStatus.FAILED
        execution.error = f"{type(exc).__name__}: {exc}"
        execution.completed_at = clock.now()
        proposal.status = ProposalStatus.FAILED
        logger.warning(
            "action_execution_failed", proposal=proposal.code, error=execution.error
        )

    record_audit(
        session,
        action="action.executed",
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        summary=(
            f"{proposal.code} ({proposal.action_type.value}) → {execution.status.value}."
        ),
        actor_type="user" if user_id else "system",
        actor_user_id=user_id,
        action_proposal_id=proposal.id,
        exception_id=proposal.exception_id,
        after=execution.result or {"error": execution.error},
    )
    record_metric(
        session,
        event_type=BusinessEventType.ACTION_EXECUTED,
        entity_type=EntityType.ACTION_PROPOSAL,
        entity_id=proposal.id,
        user_id=user_id,
        payload={
            "action_type": proposal.action_type.value,
            "mode": proposal.execution_mode.value,
            "status": execution.status.value,
        },
    )
    session.flush()
    return execution


# --- Internal executors -------------------------------------------------------


def _execute_replacement_batch(
    session: Session, proposal: ActionProposal, payload: BaseModel
) -> dict[str, Any]:
    assert isinstance(payload, ReplacementBatchPayload)
    original = session.get(ProductionBatch, payload.production_batch_id)
    if original is None:
        raise NotFoundError(f"Production batch {payload.production_batch_id} not found.")
    batch = production.create_rework_batch(
        session,
        original,
        quantity=quantize(payload.quantity),
        code=f"{original.code.split('-R')[0]}-R{_rework_index(session, original.code)}",
        days=payload.duration_days,
    )
    return {
        "created_batch_code": batch.code,
        "planned_start": batch.planned_start.isoformat(),
        "planned_completion": batch.planned_completion.isoformat(),
        "quantity": str(batch.planned_quantity),
        "unit": batch.unit.value,
    }


def _rework_index(session: Session, code: str) -> int:
    stem = code.split("-R")[0]
    count = session.scalar(
        select(func.count(ProductionBatch.id)).where(ProductionBatch.code.like(f"{stem}-R%"))
    )
    return int(count or 0) + 1


def _execute_reinspection(
    session: Session, proposal: ActionProposal, payload: BaseModel
) -> dict[str, Any]:
    assert isinstance(payload, ReinspectionPayload)
    original = session.get(QCInspection, payload.qc_inspection_id)
    if original is None:
        raise NotFoundError(f"QC inspection {payload.qc_inspection_id} not found.")
    code = f"{original.code}-RE{_reinspection_index(session, original.id)}"
    inspection = QCInspection(
        code=code,
        production_batch_id=original.production_batch_id,
        inventory_lot_id=original.inventory_lot_id,
        inspected_at=clock.now(),
        outcome=QCOutcome.PENDING,
        inspected_quantity=original.inspected_quantity,
        accepted_quantity=ZERO,
        rejected_quantity=ZERO,
        unit=original.unit,
        reinspection_of_id=original.id,
        notes=payload.note or f"Re-inspection requested for {original.code}.",
    )
    session.add(inspection)
    session.flush()
    return {
        "created_inspection_code": inspection.code,
        "status": "pending",
        "note": "Re-inspection raised; a QC operator must record the result.",
    }


def _reinspection_index(session: Session, inspection_id: uuid.UUID) -> int:
    count = session.scalar(
        select(func.count(QCInspection.id)).where(
            QCInspection.reinspection_of_id == inspection_id
        )
    )
    return int(count or 0) + 1


def _execute_priority_change(
    session: Session, proposal: ActionProposal, payload: BaseModel
) -> dict[str, Any]:
    assert isinstance(payload, PriorityPayload)
    batch = session.get(ProductionBatch, payload.production_batch_id)
    if batch is None:
        raise NotFoundError(f"Production batch {payload.production_batch_id} not found.")
    before = batch.priority
    batch.priority = payload.priority
    production.add_event(
        session,
        batch,
        event_type=_production_note_event(),
        note=f"Priority changed from {before} to {payload.priority} via {proposal.code}.",
    )
    return {"batch_code": batch.code, "priority_before": before, "priority_after": batch.priority}


def _production_note_event():
    from textileops.models.enums import ProductionEventType

    return ProductionEventType.NOTE


def _execute_reallocation(
    session: Session, proposal: ActionProposal, payload: BaseModel
) -> dict[str, Any]:
    assert isinstance(payload, ReallocatePayload)
    reservation = session.get(InventoryReservation, payload.reservation_id)
    if reservation is None:
        raise NotFoundError(f"Reservation {payload.reservation_id} not found.")
    if payload.to_sales_order_line_id is None and payload.to_production_batch_id is None:
        raise ValidationError("Reallocation must name a new order line or production batch.")
    before = {
        "sales_order_line_id": str(reservation.sales_order_line_id)
        if reservation.sales_order_line_id
        else None,
        "production_batch_id": str(reservation.production_batch_id)
        if reservation.production_batch_id
        else None,
    }
    reservation.sales_order_line_id = payload.to_sales_order_line_id
    reservation.production_batch_id = payload.to_production_batch_id
    reservation.note = f"Reallocated by {proposal.code}."
    return {
        "reservation_id": str(reservation.id),
        "quantity": str(reservation.quantity),
        "unit": reservation.unit.value,
        "from": before,
        "to": {
            "sales_order_line_id": str(payload.to_sales_order_line_id)
            if payload.to_sales_order_line_id
            else None,
            "production_batch_id": str(payload.to_production_batch_id)
            if payload.to_production_batch_id
            else None,
        },
    }


def _execute_raise_po(
    session: Session, proposal: ActionProposal, payload: BaseModel
) -> dict[str, Any]:
    """Creates a **draft** purchase order. Sending it to the supplier remains a
    human step — TextileOps has no supplier channel."""
    assert isinstance(payload, RaisePurchaseOrderPayload)
    from textileops.models.enums import PurchaseOrderStatus
    from textileops.models.org import Supplier

    supplier = session.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise NotFoundError(f"Supplier {payload.supplier_id} not found.")
    number = _next_po_number(session)
    po = PurchaseOrder(
        number=number,
        supplier_id=supplier.id,
        order_date=clock.today(),
        expected_date=payload.needed_by,
        status=PurchaseOrderStatus.DRAFT,
        currency=supplier.currency,
        notes=f"Raised from {proposal.code}.",
    )
    session.add(po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            line_no=1,
            material_id=payload.material_id,
            ordered_quantity=quantize(payload.quantity),
            unit=parse_unit(payload.unit),
            expected_date=payload.needed_by,
        )
    )
    session.flush()
    return {
        "purchase_order_number": po.number,
        "status": po.status.value,
        "note": "Draft created. Send it to the supplier from your own email/WhatsApp.",
    }


def _next_po_number(session: Session) -> str:
    count = session.scalar(select(func.count(PurchaseOrder.id))) or 0
    candidate = count + 1
    while session.scalar(
        select(PurchaseOrder.id).where(PurchaseOrder.number == f"PO-{candidate:05d}")
    ):
        candidate += 1
    return f"PO-{candidate:05d}"


def _execute_acknowledge(
    session: Session, proposal: ActionProposal, payload: BaseModel
) -> dict[str, Any]:
    assert isinstance(payload, AcknowledgePayload)
    return {"acknowledged": True, "note": payload.note}


INTERNAL_EXECUTORS: dict[ActionType, Executor] = {
    ActionType.SCHEDULE_REPLACEMENT_BATCH: _execute_replacement_batch,
    ActionType.REQUEST_QC_REINSPECTION: _execute_reinspection,
    ActionType.CHANGE_PRODUCTION_PRIORITY: _execute_priority_change,
    ActionType.REALLOCATE_INVENTORY: _execute_reallocation,
    ActionType.RAISE_PURCHASE_ORDER: _execute_raise_po,
    ActionType.ACKNOWLEDGE_ONLY: _execute_acknowledge,
}

assert set(INTERNAL_EXECUTORS) == {
    action for action, mode in EXECUTION_MODES.items() if mode == ExecutionMode.INTERNAL
}, "Every INTERNAL action must have an executor."


def _next_code(session: Session) -> str:
    count = session.scalar(select(func.count(ActionProposal.id))) or 0
    candidate = count + 1
    while session.scalar(
        select(ActionProposal.id).where(ActionProposal.code == f"AP-{candidate:05d}")
    ):
        candidate += 1
    return f"AP-{candidate:05d}"


def _jsonable(value: Any) -> Any:
    from textileops.services.audit import _jsonable as base

    return base(value)


def expire_stale_proposals(session: Session) -> int:
    """Proposals nobody acted on stop being actionable rather than lingering."""
    now = clock.now()
    count = 0
    for proposal in session.scalars(
        select(ActionProposal).where(
            ActionProposal.status == ProposalStatus.PENDING_APPROVAL,
            ActionProposal.expires_at.is_not(None),
        )
    ).all():
        if proposal.expires_at and now > clock.ensure_utc(proposal.expires_at):
            proposal.status = ProposalStatus.EXPIRED
            count += 1
    return count
