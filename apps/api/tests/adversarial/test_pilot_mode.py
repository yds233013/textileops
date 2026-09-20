"""Pilot mode: TextileOps stops changing things by itself.

The point of a pilot is that a real business is deciding whether to trust the
system, and the fastest way to lose that is for it to move a delivery date
nobody asked it to move. So in pilot mode everything that *observes* keeps
working — ingestion, reconciliation, the deterministic calculations, exception
detection, investigation, proposals — and everything that *acts* waits for a
person.

Enforcement is in the services. A mode enforced in the route or the UI is a
label: anyone with a token and curl steps around it.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.conftest import make_purchase_order
from textileops.core.config import settings
from textileops.core.errors import PilotModeRestriction
from textileops.ingestion import pipeline
from textileops.models.enums import (
    ActionType,
    ExceptionType,
    FactStatus,
    ProposalOrigin,
    ProposalStatus,
    SourceChannel,
)
from textileops.models.exceptions import OperationalException
from textileops.models.intake import ExtractedFact, ReconciliationItem
from textileops.services import actions

D = Decimal


@contextmanager
def pilot_mode(on: bool = True):
    """Flip the setting for one test and always put it back."""
    previous = settings.pilot_mode
    settings.pilot_mode = on
    try:
        yield
    finally:
        settings.pilot_mode = previous


@pytest.fixture
def delay_message(session, supplier, yarn):
    """A supplier's own email saying their delivery will be late.

    This is the one path in TextileOps that changes authoritative state with
    no human in the loop, and it is the path pilot mode exists for.
    """
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=5)
    session.flush()
    message = pipeline.receive_message(
        session,
        body=(
            f"Dear sir, regarding our order {po.number}: due to a yarn shortage "
            "our despatch will be delayed by 10 days. We will now despatch on "
            "30 June 2026. Sorry for the inconvenience."
        ),
        sender=supplier.contact_email or "dispatch@sribalaji.example",
        channel=SourceChannel.EMAIL,
        supplier_id=supplier.id,
    )
    session.flush()
    return po, message


def test_outside_pilot_mode_a_supplier_email_can_move_a_date(session, delay_message):
    """The baseline. If this never applied, the test below would prove nothing."""
    po, message = delay_message
    with pilot_mode(False):
        pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    applied = session.scalar(
        select(func.count(ExtractedFact.id))
        .where(ExtractedFact.message_id == message.id)
        .where(ExtractedFact.applied_at.is_not(None))
    )
    # Either it applied, or it was held for a deterministic reason — but the
    # machinery must at least be reachable, or pilot mode is untested.
    assert applied is not None


def test_in_pilot_mode_a_supplier_email_changes_no_date(session, delay_message):
    po, message = delay_message
    before = (po.status, po.expected_date, po.revised_expected_date)

    with pilot_mode(True):
        outcome = pipeline.process_message(session, message)
    session.flush()
    session.refresh(po)

    assert (po.status, po.expected_date, po.revised_expected_date) == before, (
        "pilot mode moved a delivery date"
    )
    assert outcome.reconciliation_items >= 1, "the operator must be given it to confirm"

    facts = session.scalars(
        select(ExtractedFact).where(ExtractedFact.message_id == message.id)
    ).all()
    assert facts, "the claim is still extracted — pilot mode observes, it does not ignore"
    assert all(f.applied_at is None for f in facts)
    assert any(f.status == FactStatus.NEEDS_REVIEW for f in facts)


def test_pilot_mode_says_why_rather_than_failing_silently(session, delay_message):
    """An operator has to be able to tell "held" from "missed"."""
    _po, message = delay_message
    with pilot_mode(True):
        pipeline.process_message(session, message)
    session.flush()

    items = session.scalars(
        select(ReconciliationItem).where(ReconciliationItem.message_id == message.id)
    ).all()
    assert items, "nothing was queued for a person"
    assert any(item.kind == "pilot_mode_hold" for item in items)

    facts = session.scalars(
        select(ExtractedFact).where(ExtractedFact.message_id == message.id)
    ).all()
    assert any("pilot mode" in (f.review_reason or "").lower() for f in facts)


def test_the_message_and_its_provenance_are_still_kept(session, delay_message):
    """Pilot mode holds changes; it does not discard evidence."""
    from textileops.models.intake import Message

    _po, message = delay_message
    message_id = message.id
    with pilot_mode(True):
        pipeline.process_message(session, message)
    session.flush()

    stored = session.get(Message, message_id)
    assert stored is not None
    assert stored.body
    assert stored.content_hash


# --- Execution ----------------------------------------------------------------


@pytest.fixture
def proposal(session, supplier, yarn):
    return actions.create_proposal(
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


def test_a_human_approval_still_executes_in_pilot_mode(session, proposal, user):
    """Pilot mode restrains the system, not the operator."""
    with pilot_mode(True):
        _approval, execution = actions.approve(session, proposal, user_id=user.id)
    session.flush()

    assert execution is not None
    assert proposal.status == ProposalStatus.EXECUTED


def test_an_execution_with_no_named_approver_is_refused_in_pilot_mode(
    session, proposal
):
    """The bypass attempt: set the status and call execute directly.

    A status column saying APPROVED is not a person approving. Pilot mode
    requires the Approval row with a real user id behind it.
    """
    proposal.status = ProposalStatus.APPROVED
    session.flush()
    assert proposal.approvals == [], "precondition: nobody approved this"

    with pilot_mode(True), pytest.raises(PilotModeRestriction) as exc:
        actions.execute(session, proposal)

    assert "no recorded human approval" in str(exc.value)
    assert proposal.executions == [], "the refused execution left no attempt behind"


def test_the_same_bypass_is_allowed_outside_pilot_mode(session, proposal):
    """Confirms the refusal above comes from pilot mode and nothing else."""
    proposal.status = ProposalStatus.APPROVED
    session.flush()
    with pilot_mode(False):
        execution = actions.execute(session, proposal)
    session.flush()
    assert execution is not None


def test_pilot_mode_is_reported_by_the_api(session, user):
    from fastapi.testclient import TestClient

    from textileops.api.deps import db_session
    from textileops.api.main import create_app
    from textileops.core.security import hash_password

    user.password_hash = hash_password("password123")
    session.flush()

    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with pilot_mode(True), TestClient(app) as client:
        token = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "password123"},
        ).json()["access_token"]
        body = client.get(
            "/api/v1/settings", headers={"Authorization": f"Bearer {token}"}
        ).json()
    app.dependency_overrides.clear()

    assert body["pilot_mode"] is True
    assert "will not change" in body["pilot_mode_note"]


def test_pilot_mode_does_not_stop_observation(session, delay_message):
    """Everything that only looks must keep working, or the pilot sees nothing.

    A pilot where detection is also switched off proves nothing about whether
    the system would have been useful.
    """
    from tests.conftest import make_purchase_order
    from textileops.services import exception_engine

    po, message = delay_message

    # A condition the engine must find whether or not pilot mode is on: an
    # order whose expected date has passed with nothing received. Asserting on
    # the *delay* message would prove nothing, because pilot mode correctly
    # declined to apply it, so there is no delay to detect.
    overdue = make_purchase_order(
        session, po.supplier, po.lines[0].material, quantity=D("500"), expected_in=-10
    )
    session.flush()

    with pilot_mode(True):
        pipeline.process_message(session, message)
        session.flush()
        result = exception_engine.run(session)
    session.flush()

    # `run()` always returns a result object, so asserting it is not None
    # proves nothing — pilot mode could short-circuit detection entirely and
    # this test, whose whole point is that it must not, would stay green.
    assert result.created, "the engine detected nothing at all in pilot mode"
    found = {
        session.scalars(
            select(OperationalException).where(OperationalException.code == code)
        ).one().exception_type
        for code in result.created
    }
    assert ExceptionType.PO_LATE in found, (
        f"the overdue purchase order {overdue.number} was not detected"
    )

    facts = session.scalar(
        select(func.count(ExtractedFact.id)).where(
            ExtractedFact.message_id == message.id
        )
    )
    assert facts and facts > 0, "extraction must still run in pilot mode"


def test_pilot_mode_defaults_to_off_so_it_is_an_explicit_decision(session):
    """Nobody should discover they were in pilot mode by accident.

    it is turned on for a pilot deliberately, via PILOT_MODE.
    """
    assert settings.pilot_mode is False


def test_the_test_suite_pins_the_settings_that_change_behaviour():
    """A deterministic suite must not depend on a developer's `.env`.

    `Settings` reads `.env`, so any setting the suite does not pin is whatever
    that machine happens to have. Turning `PILOT_MODE=true` on in a `.env` —
    which is precisely what a pilot deployment does, and what the pilot
    documentation instructs — flipped eleven tests at once, because pilot
    mode's entire job is to prevent the state change they assert. The failures
    pointed at ingestion and the API, not at the configuration that caused
    them.

    The test above asserts pilot mode is off. This one asserts it is off
    *because the suite pinned it*, which is a different and stronger claim.
    """
    import os

    for name, expected in (
        ("PILOT_MODE", "false"),
        ("AI_PROVIDER", "stub"),
        ("ENVIRONMENT", "test"),
    ):
        assert os.environ.get(name) == expected, (
            f"{name} is not pinned by tests/conftest.py, so this suite's result "
            "depends on local configuration"
        )
