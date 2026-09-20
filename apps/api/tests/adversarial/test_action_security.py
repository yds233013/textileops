"""Attempts to get an action executed without a legitimate approval.

Invariant 3 says every consequential external action passes through
``ActionProposal → Approval → Execution``. That is only worth anything if
there is no way round it, so this file tries to find one: executing without
approving, approving twice, approving something already run, re-pointing a
payload at a different customer after approval, replaying an execution,
approving an expired proposal, and approving without the role to do it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from textileops.api.deps import db_session
from textileops.api.main import create_app
from textileops.core.errors import ConflictError, IllegalStateTransition, ValidationError
from textileops.core.security import hash_password
from textileops.models.actions import Approval, Execution
from textileops.models.enums import (
    ActionType,
    ApprovalDecision,
    ExecutionStatus,
    ProposalOrigin,
    ProposalStatus,
    UserRole,
)
from textileops.models.org import User
from textileops.models.procurement import PurchaseOrder
from textileops.services import actions, clock

D = Decimal
PREFIX = "/api/v1"


@pytest.fixture
def proposal(session, supplier, yarn):
    return actions.create_proposal(
        session,
        action_type=ActionType.RAISE_PURCHASE_ORDER,
        title="Cover the shortfall on 40s cotton",
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


def _user(session, role: UserRole) -> User:
    record = User(
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@example.com",
        full_name=f"Test {role.value}",
        role=role,
        password_hash=hash_password("password123"),
    )
    session.add(record)
    session.flush()
    return record


# --- The service boundary -----------------------------------------------------


def test_an_unapproved_proposal_cannot_be_executed(session, proposal):
    """The obvious attack, and the one the whole design exists to stop."""
    with pytest.raises(IllegalStateTransition):
        actions.execute(session, proposal)

    assert session.scalars(
        select_executions(proposal)
    ).all() == [], "an execution record was created for an unapproved proposal"
    assert proposal.status == ProposalStatus.PENDING_APPROVAL


def select_executions(proposal):
    from sqlalchemy import select

    return select(Execution).where(Execution.action_proposal_id == proposal.id)


def test_a_rejected_proposal_cannot_then_be_approved(session, proposal, user):
    actions.reject(session, proposal, user_id=user.id, note="Not needed.")
    session.flush()

    with pytest.raises(IllegalStateTransition):
        actions.approve(session, proposal, user_id=user.id)

    approvals = session.scalars(
        __import__("sqlalchemy").select(Approval).where(
            Approval.action_proposal_id == proposal.id
        )
    ).all()
    assert len(approvals) == 1
    assert approvals[0].decision == ApprovalDecision.REJECTED


def test_an_executed_proposal_cannot_be_approved_again(session, proposal, user):
    actions.approve(session, proposal, user_id=user.id)
    session.flush()
    assert proposal.status == ProposalStatus.EXECUTED

    with pytest.raises(IllegalStateTransition):
        actions.approve(session, proposal, user_id=user.id)


def test_executing_twice_returns_the_first_execution_and_acts_once(
    session, proposal, user, supplier
):
    """At-least-once delivery means execute() really is called again."""
    from sqlalchemy import func, select

    actions.approve(session, proposal, user_id=user.id, execute_now=False)
    session.flush()

    first = actions.execute(session, proposal, user_id=user.id)
    session.flush()
    second = actions.execute(session, proposal, user_id=user.id)
    session.flush()

    assert first.id == second.id, "a replay produced a second execution"
    assert first.status == ExecutionStatus.SUCCEEDED
    raised = session.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.supplier_id == supplier.id)
    )
    assert raised == 1, "the replay raised a second purchase order at the supplier"


def test_an_expired_proposal_is_refused_rather_than_quietly_honoured(
    session, proposal, user
):
    proposal.expires_at = clock.now() - __import__("datetime").timedelta(days=1)
    session.flush()

    with pytest.raises(ConflictError):
        actions.approve(session, proposal, user_id=user.id)

    assert proposal.status == ProposalStatus.EXPIRED


def test_the_payload_cannot_be_swapped_for_something_unvalidatable_at_approval(
    session, proposal, user, supplier
):
    """``modified_payload`` is an operator edit, and it is validated as one."""
    with pytest.raises(ValidationError):
        actions.approve(
            session,
            proposal,
            user_id=user.id,
            modified_payload={"supplier_id": str(supplier.id), "quantity": "-5"},
        )
    assert proposal.status == ProposalStatus.PENDING_APPROVAL


def test_an_approved_proposal_executes_the_payload_that_was_approved(
    session, proposal, user, supplier, yarn
):
    """Editing the row after approval must not change what already ran."""
    actions.approve(session, proposal, user_id=user.id)
    session.flush()
    execution = proposal.executions[-1]

    # Someone tampers with the stored payload afterwards.
    proposal.payload = {**proposal.payload, "quantity": "999999.000"}
    session.flush()

    from sqlalchemy import select

    raised = session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.number == execution.result["purchase_order_number"]
        )
    )
    assert raised is not None
    assert raised.lines[0].ordered_quantity == D("500.000"), (
        "the executed order reflects a payload nobody approved"
    )


# --- The HTTP boundary --------------------------------------------------------


@pytest.fixture
def client(session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client, email: str) -> dict[str, str]:
    response = client.post(
        f"{PREFIX}/auth/login", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_a_viewer_cannot_approve(client, session, proposal):
    viewer = _user(session, UserRole.VIEWER)
    headers = _login(client, viewer.email)

    response = client.post(
        f"{PREFIX}/proposals/{proposal.id}/approve", json={}, headers=headers
    )

    assert response.status_code == 403, response.text
    session.refresh(proposal)
    assert proposal.status == ProposalStatus.PENDING_APPROVAL
    assert proposal.executions == []


def test_an_anonymous_caller_cannot_approve(client, proposal):
    response = client.post(f"{PREFIX}/proposals/{proposal.id}/approve", json={})
    assert response.status_code == 401


def test_there_is_no_route_that_executes_without_approving():
    """A direct execute endpoint would be a hole straight through invariant 3."""
    from textileops.api.routes import proposals as proposal_routes

    paths = {
        (route.path, tuple(sorted(route.methods)))
        for route in proposal_routes.router.routes
        if hasattr(route, "methods")
    }
    execute_routes = [p for p, _ in paths if p.endswith("/execute")]
    assert execute_routes == [], (
        f"an execution endpoint bypasses the approval gate: {execute_routes}"
    )


def test_every_state_changing_proposal_route_requires_an_approver_role():
    """A POST that changes a proposal must not be reachable by a viewer."""
    from textileops.api.routes import proposals as proposal_routes

    for route in proposal_routes.router.routes:
        methods = getattr(route, "methods", set())
        if not methods & {"POST", "PATCH", "PUT", "DELETE"}:
            continue
        dependencies = str(getattr(route, "dependant", ""))
        signature = str(route.endpoint.__annotations__)
        assert "ApproverUser" in signature or "ApproverUser" in dependencies, (
            f"{route.path} changes state but does not require an approver role"
        )
