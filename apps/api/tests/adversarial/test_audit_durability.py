"""The approval record must survive attempts to delete it out from under itself.

An approval is the evidence that a person took responsibility for an action.
The schema audit found a single ``DELETE FROM production_batches`` that
cascaded through eight tables and removed the exception, its evidence, the
proposal, the approval and the execution — leaving audit rows saying somebody
approved something, with no way to recover what.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import make_batch, make_sales_order
from textileops.models.actions import Approval, Execution
from textileops.models.enums import (
    ActionType,
    ApprovalDecision,
    EntityType,
    ExceptionStatus,
    ExceptionType,
    ProposalOrigin,
    Severity,
)
from textileops.models.exceptions import OperationalException
from textileops.models.production import ProductionBatch
from textileops.services import actions

D = Decimal


def _refused(session, statement: str, **params) -> None:
    """Run a DELETE inside a savepoint and require the database to refuse it.

    The savepoint matters: the test's own fixture data lives in the enclosing
    transaction, and rolling that back would leave nothing to assert against.
    """
    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            session.execute(text(statement), params)
            session.flush()
    finally:
        savepoint.rollback()


@pytest.fixture
def approved_proposal(session, supplier, yarn, user):
    proposal = actions.create_proposal(
        session,
        action_type=ActionType.RAISE_PURCHASE_ORDER,
        title="Cover the shortfall",
        rationale="Coverage runs out before the promised date.",
        payload={
            "supplier_id": str(supplier.id),
            "material_id": str(yarn.id),
            "quantity": "500.000",
            "unit": "kg",
            "needed_by": "2026-07-15",
        },
        origin=ProposalOrigin.RULE_ENGINE,
    )
    actions.approve(session, proposal, user_id=user.id)
    session.flush()
    return proposal


def test_a_proposal_carrying_an_approval_cannot_be_deleted(session, approved_proposal):
    """Deleting the proposal would take the approval with it."""
    _refused(
        session,
        "delete from action_proposals where id = :id",
        id=approved_proposal.id,
    )


def test_deleting_a_production_batch_cannot_erase_an_approval(
    session, fabric, yarn, customer, user, supplier
):
    """The original cascade path, end to end.

    production_batches -> operational_exceptions -> action_proposals ->
    approvals. One DELETE at the top used to clear the lot.
    """
    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()

    exception_row = OperationalException(
        code=f"EXC-{uuid.uuid4().hex[:5].upper()}",
        exception_type=ExceptionType.PRODUCTION_DELAY,
        severity=Severity.HIGH,
        status=ExceptionStatus.OPEN,
        title="Batch blocked",
        summary="No yarn.",
        dedupe_key=f"test:{uuid.uuid4().hex}",
        detected_at=dt.datetime(2026, 6, 15, tzinfo=dt.UTC),
        first_detected_at=dt.datetime(2026, 6, 15, tzinfo=dt.UTC),
        last_evaluated_at=dt.datetime(2026, 6, 15, tzinfo=dt.UTC),
        entity_type=EntityType.PRODUCTION_BATCH,
        entity_id=batch.id,
        production_batch_id=batch.id,
        priority_score=50,
    )
    session.add(exception_row)
    session.flush()

    proposal = actions.create_proposal(
        session,
        action_type=ActionType.RAISE_PURCHASE_ORDER,
        title="Buy yarn",
        rationale="The batch cannot start.",
        payload={
            "supplier_id": str(supplier.id),
            "material_id": str(yarn.id),
            "quantity": "500.000",
            "unit": "kg",
            "needed_by": "2026-07-15",
        },
        origin=ProposalOrigin.RULE_ENGINE,
        exception_id=exception_row.id,
    )
    actions.approve(session, proposal, user_id=user.id)
    session.flush()

    approvals_before = session.scalar(select(func.count(Approval.id)))
    assert approvals_before >= 1

    _refused(session, "delete from production_batches where id = :id", id=batch.id)

    # Everything is still there.
    assert session.get(ProductionBatch, batch.id) is not None
    assert session.scalar(select(func.count(Approval.id))) == approvals_before


def test_one_proposal_cannot_hold_two_approval_rows(session, approved_proposal, user):
    """The database backstop behind the row lock in actions.approve."""
    savepoint = session.begin_nested()
    try:
        session.add(
            Approval(
                action_proposal_id=approved_proposal.id,
                decision=ApprovalDecision.APPROVED,
                decided_by_user_id=user.id,
                decided_at=dt.datetime(2026, 6, 15, tzinfo=dt.UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        savepoint.rollback()


def test_the_execution_record_outlives_its_proposal_row(session, approved_proposal):
    """An execution is the evidence that something actually happened."""
    executions = session.scalars(
        select(Execution).where(Execution.action_proposal_id == approved_proposal.id)
    ).all()
    assert len(executions) == 1

    _refused(
        session,
        "delete from action_proposals where id = :id",
        id=approved_proposal.id,
    )
