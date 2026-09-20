"""Who did it must outlive the person's account.

"A quantity changed" is half a record. The other half is who changed it, and
that half is the one a dispute turns on. A user leaving the company is an
ordinary event; it must not be able to quietly rewrite months of history into
"somebody".

The rule this file enforces: a column that records **an act a person
performed** is RESTRICT, so deleting the account fails loudly and the
operator is pushed towards deactivation instead. A column that records an
**assignment** — who happens to own an open exception — may be nulled, because
unassigning on departure is exactly right.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import make_purchase_order
from textileops.core.security import hash_password
from textileops.models.enums import UserRole
from textileops.models.org import User
from textileops.models.platform import AuditEvent
from textileops.services import procurement

D = Decimal

#: Columns that record something a person *did*. Deleting the account must not
#: be able to erase it.
ACTS: dict[str, str] = {
    "action_proposals.created_by_user_id": "who proposed the action",
    "approvals.decided_by_user_id": "who approved or rejected it",
    "audit_events.actor_user_id": "who the audit trail says acted",
    "executions.executed_by_user_id": "who carried the action out",
    "inventory_movements.created_by_user_id": "who moved the stock",
    "investigations.requested_by_user_id": "who asked for the investigation",
    "production_events.created_by_user_id": "who recorded the production event",
    "purchase_order_receipt_corrections.corrected_by_user_id": (
        "who corrected the receipt"
    ),
    "qc_inspections.inspector_user_id": "who inspected the cloth",
    "reconciliation_items.resolved_by_user_id": "who reconciled the discrepancy",
    "source_documents.uploaded_by_user_id": "who supplied the document",
    "operational_exceptions.resolved_by_user_id": "who resolved or dismissed it",
}

#: Columns that record an assignment or an instrumentation event rather than an
#: act. Nulling these on departure is correct.
ASSIGNMENTS = {
    "operational_exceptions.owner_user_id",
    "business_metric_events.user_id",
}


def _user_foreign_keys(session) -> dict[str, str]:
    rows = session.execute(
        text(
            """
            select c.conrelid::regclass::text as table_name,
                   a.attname as column_name,
                   c.confdeltype as on_delete
            from pg_constraint c
            join unnest(c.conkey) with ordinality as k(attnum, ord) on true
            join pg_attribute a
              on a.attrelid = c.conrelid and a.attnum = k.attnum
            where c.contype = 'f' and c.confrelid = 'users'::regclass
            """
        )
    ).all()
    return {f"{t}.{col}": behaviour for t, col, behaviour in rows}


def test_every_column_that_records_an_act_survives_deleting_the_user(session):
    """A structural test, so a new actor column cannot quietly arrive as SET NULL."""
    found = _user_foreign_keys(session)
    wrong = {
        name: found[name]
        for name in ACTS
        if name in found and found[name] != "r"  # 'r' is RESTRICT
    }
    assert wrong == {}, (
        "these columns record what a person did but would be nulled by deleting "
        f"the account: {wrong}"
    )


def test_the_act_columns_all_actually_exist(session):
    """Guards the test above: a renamed column must not make it vacuous."""
    found = _user_foreign_keys(session)
    missing = sorted(set(ACTS) - set(found))
    assert missing == [], f"these user foreign keys no longer exist: {missing}"


def test_no_user_foreign_key_is_unclassified(session):
    """Every user reference is deliberately either an act or an assignment."""
    found = set(_user_foreign_keys(session))
    unclassified = sorted(found - set(ACTS) - ASSIGNMENTS)
    assert unclassified == [], (
        "new user foreign keys need a decision: is this an act (RESTRICT) or an "
        f"assignment (SET NULL)? {unclassified}"
    )


def test_an_assignment_is_still_nullable_on_delete(session):
    """Unassigning on departure is correct and must stay possible."""
    found = _user_foreign_keys(session)
    for name in ASSIGNMENTS:
        if name in found:
            assert found[name] == "n", f"{name} should be SET NULL, is {found[name]}"


def test_deleting_a_user_who_moved_stock_is_refused(session, supplier, yarn):
    """The end-to-end version of the structural test."""
    actor = User(
        email=f"leaver-{uuid.uuid4().hex[:6]}@example.com",
        full_name="Departing Operator",
        role=UserRole.PROCUREMENT,
        password_hash=hash_password("password123"),
    )
    session.add(actor)
    session.flush()

    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"))
    session.flush()
    procurement.receive(
        session, po.lines[0], accepted_quantity=D("1000"), user_id=actor.id
    )
    session.flush()

    savepoint = session.begin_nested()
    try:
        with pytest.raises(IntegrityError):
            session.execute(
                text("delete from users where id = :id"), {"id": actor.id}
            )
            session.flush()
    finally:
        savepoint.rollback()

    events = session.scalars(
        select(AuditEvent).where(AuditEvent.actor_user_id == actor.id)
    ).all()
    assert events, "the audit trail still names the actor"


def test_deactivating_a_user_keeps_their_history_and_stops_their_access(
    session, supplier, yarn
):
    """Deactivation is the supported way to remove someone.

    It keeps every record they created intact, which is the whole point, and
    the account stops working immediately.
    """
    actor = User(
        email=f"leaver-{uuid.uuid4().hex[:6]}@example.com",
        full_name="Departing Operator",
        role=UserRole.PROCUREMENT,
        password_hash=hash_password("password123"),
    )
    session.add(actor)
    session.flush()
    po = make_purchase_order(session, supplier, yarn, quantity=D("500"))
    session.flush()
    procurement.receive(
        session, po.lines[0], accepted_quantity=D("500"), user_id=actor.id
    )
    session.flush()

    actor.is_active = False
    session.flush()

    events = session.scalars(
        select(AuditEvent).where(AuditEvent.actor_user_id == actor.id)
    ).all()
    assert events, "deactivation must not touch the history"
    assert all(e.actor_user_id == actor.id for e in events)


def test_a_deactivated_user_cannot_log_in(session, user):
    from fastapi.testclient import TestClient

    from textileops.api.deps import db_session
    from textileops.api.main import create_app

    user.password_hash = hash_password("password123")
    user.is_active = False
    session.flush()

    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "password123"},
        )
    app.dependency_overrides.clear()
    assert response.status_code in (401, 403), response.text


def test_a_token_issued_before_deactivation_stops_working(session, user):
    """Deactivation has to bite immediately, not at the next token expiry."""
    from fastapi.testclient import TestClient

    from textileops.api.deps import db_session
    from textileops.api.main import create_app

    user.password_hash = hash_password("password123")
    session.flush()

    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as client:
        token = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "password123"},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/dashboard", headers=headers).status_code == 200

        user.is_active = False
        session.flush()

        after = client.get("/api/v1/dashboard", headers=headers)
    app.dependency_overrides.clear()
    assert after.status_code in (401, 403), (
        "a deactivated account kept working until its token expired"
    )
