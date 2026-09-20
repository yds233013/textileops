"""ActionProposal → Approval → Execution. The only path to a consequence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import make_batch, moment
from textileops.core.errors import ConflictError, IllegalStateTransition, ValidationError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import (
    ActionType,
    ExecutionMode,
    ExecutionStatus,
    ProposalOrigin,
    ProposalStatus,
)
from textileops.models.platform import AuditEvent
from textileops.services import actions, clock, inventory

D = Decimal


def _proposal(session, supplier, **overrides):
    defaults = {
        "action_type": ActionType.CONTACT_SUPPLIER,
        "title": "Ask Sri Balaji for a firm date",
        "rationale": "We cannot re-plan production without one.",
        "payload": {"recipient_kind": "supplier", "recipient_id": str(supplier.id)},
        "origin": ProposalOrigin.AI_INVESTIGATION,
        "draft_body": "Dear team, please confirm the revised dispatch date.",
    }
    defaults.update(overrides)
    return actions.create_proposal(session, **defaults)


def test_an_external_action_requires_a_draft(session, supplier):
    with pytest.raises(ValidationError):
        _proposal(session, supplier, draft_body=None)


def test_a_proposal_starts_pending_and_changes_nothing(session, supplier):
    proposal = _proposal(session, supplier)
    session.flush()
    assert proposal.status == ProposalStatus.PENDING_APPROVAL
    assert proposal.execution_mode == ExecutionMode.EXTERNAL_DRAFT
    assert proposal.executions == []


def test_approving_an_external_action_never_claims_to_have_sent_it(
    session, supplier, user
):
    proposal = _proposal(session, supplier)
    session.flush()
    _, execution = actions.approve(session, proposal, user_id=user.id)
    session.flush()

    assert execution is not None
    assert execution.status == ExecutionStatus.AWAITING_EXTERNAL
    assert proposal.status == ProposalStatus.AWAITING_EXTERNAL
    assert "not" in execution.result["message"].lower()
    assert execution.result["draft_body"] == proposal.draft_body


def test_an_internal_action_is_executed_deterministically(session, fabric, yarn, user):
    inventory.create_lot(
        session,
        lot_code="LOT-Y",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    batch = make_batch(session, fabric, quantity=D("1000"))
    session.flush()

    proposal = actions.create_proposal(
        session,
        action_type=ActionType.CHANGE_PRODUCTION_PRIORITY,
        title=f"Raise the priority of {batch.code}",
        rationale="The order behind it has no buffer left.",
        payload={"production_batch_id": str(batch.id), "priority": 2},
        origin=ProposalOrigin.AI_INVESTIGATION,
    )
    session.flush()
    _, execution = actions.approve(session, proposal, user_id=user.id)
    session.flush()

    assert execution.status == ExecutionStatus.SUCCEEDED
    assert proposal.status == ProposalStatus.EXECUTED
    assert batch.priority == 2
    assert execution.result["priority_before"] == 5


def test_execution_is_idempotent(session, fabric, yarn, user):
    inventory.create_lot(
        session,
        lot_code="LOT-Y",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    batch = make_batch(session, fabric, quantity=D("1000"))
    session.flush()
    proposal = actions.create_proposal(
        session,
        action_type=ActionType.CHANGE_PRODUCTION_PRIORITY,
        title="Raise priority",
        rationale="Needed.",
        payload={"production_batch_id": str(batch.id), "priority": 3},
        origin=ProposalOrigin.HUMAN,
    )
    session.flush()
    actions.approve(session, proposal, user_id=user.id)
    session.flush()
    first = proposal.executions[0]
    repeat = actions.execute(session, proposal, user_id=user.id)
    assert repeat.id == first.id
    assert len(proposal.executions) == 1


def test_a_rejected_proposal_is_never_executed(session, supplier, user):
    proposal = _proposal(session, supplier)
    session.flush()
    actions.reject(session, proposal, user_id=user.id, note="We already called them.")
    session.flush()
    assert proposal.status == ProposalStatus.REJECTED
    assert proposal.executions == []
    with pytest.raises(IllegalStateTransition):
        actions.execute(session, proposal, user_id=user.id)


def test_a_proposal_cannot_be_decided_twice(session, supplier, user):
    proposal = _proposal(session, supplier)
    session.flush()
    actions.approve(session, proposal, user_id=user.id)
    session.flush()
    with pytest.raises(IllegalStateTransition):
        actions.approve(session, proposal, user_id=user.id)


def test_an_expired_proposal_must_be_re_proposed(session, supplier, user):
    proposal = _proposal(session, supplier, expires_in_days=None)
    proposal.expires_at = clock.now().replace(year=2020)
    session.flush()
    with pytest.raises(ConflictError):
        actions.approve(session, proposal, user_id=user.id)
    assert proposal.status == ProposalStatus.EXPIRED


def test_editing_a_draft_is_recorded(session, supplier, user):
    proposal = _proposal(session, supplier)
    session.flush()
    original = proposal.draft_body
    actions.edit_draft(session, proposal, body="Rewritten by the operator.", user_id=user.id)
    session.flush()
    assert proposal.draft_edited is True
    assert proposal.draft_original_body == original
    assert proposal.draft_body == "Rewritten by the operator."


def test_an_invalid_payload_is_refused_at_creation(session, supplier):
    with pytest.raises(ValidationError):
        actions.create_proposal(
            session,
            action_type=ActionType.CHANGE_PRODUCTION_PRIORITY,
            title="Bad payload",
            rationale="Priority 99 is not a priority.",
            payload={"production_batch_id": str(supplier.id), "priority": 99},
            origin=ProposalOrigin.HUMAN,
        )


def test_every_execution_writes_an_audit_event(session, supplier, user):
    from sqlalchemy import select

    proposal = _proposal(session, supplier)
    session.flush()
    actions.approve(session, proposal, user_id=user.id)
    session.flush()
    actions_logged = set(
        session.scalars(
            select(AuditEvent.action).where(AuditEvent.action_proposal_id == proposal.id)
        ).all()
    )
    assert {"proposal.created", "proposal.approved", "action.executed"} <= actions_logged


def test_a_failed_execution_is_recorded_rather_than_hidden(session, user):
    import uuid

    proposal = actions.create_proposal(
        session,
        action_type=ActionType.REQUEST_QC_REINSPECTION,
        title="Re-inspect",
        rationale="Testing failure handling.",
        payload={"qc_inspection_id": str(uuid.uuid4())},  # does not exist
        origin=ProposalOrigin.HUMAN,
    )
    session.flush()
    _, execution = actions.approve(session, proposal, user_id=user.id)
    session.flush()
    assert execution.status == ExecutionStatus.FAILED
    assert proposal.status == ProposalStatus.FAILED
    assert "NotFoundError" in execution.error


def test_every_internal_action_has_an_executor():
    """A proposal type with no executor would be approvable but impossible."""
    internal = {
        action for action, mode in actions.EXECUTION_MODES.items()
        if mode == ExecutionMode.INTERNAL
    }
    assert set(actions.INTERNAL_EXECUTORS) == internal


def test_stale_proposals_expire(session, supplier):
    proposal = _proposal(session, supplier)
    proposal.expires_at = clock.now().replace(year=2020)
    session.flush()
    assert actions.expire_stale_proposals(session) == 1
    assert proposal.status == ProposalStatus.EXPIRED


def test_a_failed_executor_leaves_nothing_behind(session, fabric, yarn, user):
    """A half-finished executor must not commit its partial writes.

    Without a savepoint, a replacement-batch executor that fails after creating
    the batch leaves that batch and its reservations in place; the operator
    sees FAILED, retries, and a second set appears.
    """
    from sqlalchemy import func, select

    from textileops.models.inventory import InventoryReservation
    from textileops.models.production import ProductionBatch

    inventory.create_lot(
        session,
        lot_code="LOT-Y",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    batch = make_batch(session, fabric, quantity=D("1000"))
    session.flush()
    batches_before = session.scalar(select(func.count(ProductionBatch.id)))
    reservations_before = session.scalar(select(func.count(InventoryReservation.id)))

    proposal = actions.create_proposal(
        session,
        action_type=ActionType.SCHEDULE_REPLACEMENT_BATCH,
        title="Replace the rejected quantity",
        rationale="QC rejected it.",
        payload={
            "production_batch_id": str(batch.id),
            "quantity": "500",
            # An impossible unit for this fabric: the executor fails part way.
            "unit": "kg",
            "duration_days": 7,
        },
        origin=ProposalOrigin.HUMAN,
    )
    session.flush()
    _, execution = actions.approve(session, proposal, user_id=user.id)
    session.flush()

    if execution.status == ExecutionStatus.FAILED:
        assert session.scalar(select(func.count(ProductionBatch.id))) == batches_before
        assert (
            session.scalar(select(func.count(InventoryReservation.id)))
            == reservations_before
        )
