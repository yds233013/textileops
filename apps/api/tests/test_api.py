"""API integration tests: auth, the main read paths, and the approval workflow."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_purchase_order, make_sales_order, moment
from textileops.api.deps import db_session
from textileops.api.main import create_app
from textileops.core.security import hash_password
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import ActionType, ProposalOrigin, UserRole
from textileops.models.org import User
from textileops.services import actions, exception_engine, inventory

D = Decimal
PREFIX = "/api/v1"


@pytest.fixture
def client(session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[db_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth(client, session, user) -> dict[str, str]:
    from textileops.core.security import hash_password

    user.password_hash = hash_password("password123")
    session.flush()
    response = client.post(
        f"{PREFIX}/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health_needs_no_authentication(client):
    response = client.get(f"{PREFIX}/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["ai_provider"] == "stub"


def test_protected_routes_refuse_anonymous_callers(client):
    for path in ("/dashboard", "/orders", "/exceptions", "/proposals", "/audit"):
        response = client.get(f"{PREFIX}{path}")
        assert response.status_code == 401, path


def test_a_wrong_password_is_not_distinguishable_from_a_missing_account(client, user):
    missing = client.post(
        f"{PREFIX}/auth/login", json={"email": "nobody@example.com", "password": "x"}
    )
    wrong = client.post(
        f"{PREFIX}/auth/login", json={"email": user.email, "password": "wrong"}
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["message"] == wrong.json()["message"]


def test_dashboard_reports_the_attention_queue(client, auth, session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=-6)
    session.flush()
    exception_engine.run(session)
    session.flush()

    response = client.get(f"{PREFIX}/dashboard", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["greeting"].startswith("Good ")
    assert body["attention_queue"]
    card = body["attention_queue"][0]
    # Each card answers what / why / impact / recommendation.
    assert card["what"] and card["why"] and card["impact_headline"]
    assert card["recommended_action"]
    assert body["ai_mode"] == "deterministic"
    assert {tile["key"] for tile in body["metrics"]} >= {
        "open_orders", "orders_at_risk", "late_pos", "pending_approvals"
    }


def test_order_detail_and_timeline(client, auth, session, customer, fabric, yarn):
    inventory.create_lot(
        session,
        lot_code="LOT-Y",
        material_id=yarn.id,
        quantity=D("3000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    order = make_sales_order(session, customer, fabric)
    session.flush()

    detail = client.get(f"{PREFIX}/orders/{order.id}", headers=auth)
    assert detail.status_code == 200
    body = detail.json()
    assert body["number"] == order.number
    assert body["lines"][0]["unit"] == "m"
    assert body["risk"] in {"on_track", "watch", "at_risk", "late"}

    timeline = client.get(f"{PREFIX}/orders/{order.id}/timeline", headers=auth)
    assert timeline.status_code == 200
    assert timeline.json()[0]["title"].startswith(f"Order {order.number}")


def test_a_missing_record_returns_a_clean_404(client, auth):
    import uuid

    response = client.get(f"{PREFIX}/orders/{uuid.uuid4()}", headers=auth)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_purchase_order_detail_explains_its_eta(client, auth, session, supplier, yarn, user):
    """'Why do we believe this date?' must be answerable from the API alone."""
    from tests.conftest import day
    from textileops.services import procurement

    po = make_purchase_order(session, supplier, yarn, expected_in=4)
    original = po.expected_date
    session.flush()

    before = client.get(f"{PREFIX}/purchase-orders/{po.id}", headers=auth).json()
    assert before["eta_provenance"]["is_revised"] is False

    procurement.revise_eta(
        session,
        po,
        new_date=day(11),
        reason="Ring frame breakdown reported by the supplier.",
        user_id=user.id,
        actor_type="user",
    )
    session.flush()

    after = client.get(f"{PREFIX}/purchase-orders/{po.id}", headers=auth).json()
    provenance = after["eta_provenance"]
    assert provenance["original_expected_date"] == original.isoformat()
    assert provenance["current_expected_date"] == day(11).isoformat()
    assert provenance["is_revised"] is True
    assert "Ring frame breakdown" in provenance["reason"]
    assert provenance["updated_at"] is not None


def test_coverage_endpoint_explains_the_arithmetic(client, auth, session, yarn):
    inventory.create_lot(
        session,
        lot_code="LOT-Y",
        material_id=yarn.id,
        quantity=D("1000"),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )
    session.flush()
    response = client.get(f"{PREFIX}/inventory/coverage/{yarn.id}", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["position"]["on_hand"] == "1000.000"
    assert "allocated to supply in required-by date order" in body["explanation"]


def test_exception_list_and_detail_with_evidence(client, auth, session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=-6)
    session.flush()
    exception_engine.run(session)
    session.flush()

    listing = client.get(f"{PREFIX}/exceptions", headers=auth)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items

    detail = client.get(f"{PREFIX}/exceptions/{items[0]['id']}", headers=auth)
    assert detail.status_code == 200
    body = detail.json()
    assert body["evidence"], "an exception must be able to show its working"
    assert body["impact"]["metrics"] is not None


def test_investigating_an_exception_produces_a_proposal_awaiting_approval(
    client, auth, session, supplier, yarn
):
    make_purchase_order(session, supplier, yarn, expected_in=-6)
    session.flush()
    exception_engine.run(session)
    session.flush()
    exception_id = client.get(f"{PREFIX}/exceptions", headers=auth).json()["items"][0]["id"]

    response = client.post(f"{PREFIX}/exceptions/{exception_id}/investigate", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["investigation"]["findings"]["what_happened"]
    assert body["investigation"]["is_stubbed"] is True
    assert body["proposal_ids"]

    proposal = client.get(
        f"{PREFIX}/proposals/{body['proposal_ids'][0]}", headers=auth
    ).json()
    assert proposal["status"] == "pending_approval"
    assert proposal["origin"] == "ai_investigation"


def test_approving_an_external_draft_says_nothing_was_sent(client, auth, session, supplier):
    proposal = actions.create_proposal(
        session,
        action_type=ActionType.CONTACT_SUPPLIER,
        title="Chase the supplier",
        rationale="They are five days late.",
        payload={"recipient_kind": "supplier", "recipient_id": str(supplier.id)},
        origin=ProposalOrigin.AI_INVESTIGATION,
        draft_body="Dear team, please confirm the revised date.",
    )
    session.flush()

    response = client.post(
        f"{PREFIX}/proposals/{proposal.id}/approve", headers=auth, json={"note": "Go ahead."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["proposal"]["status"] == "awaiting_external"
    assert "has not sent" in body["message"]
    assert body["execution"]["status"] == "awaiting_external"


def test_editing_a_draft_then_approving_records_both(client, auth, session, supplier):
    proposal = actions.create_proposal(
        session,
        action_type=ActionType.CONTACT_SUPPLIER,
        title="Chase the supplier",
        rationale="Late.",
        payload={"recipient_kind": "supplier", "recipient_id": str(supplier.id)},
        origin=ProposalOrigin.AI_INVESTIGATION,
        draft_body="Original wording.",
    )
    session.flush()

    edited = client.patch(
        f"{PREFIX}/proposals/{proposal.id}/draft",
        headers=auth,
        json={"body": "My own wording, thanks."},
    )
    assert edited.status_code == 200
    assert edited.json()["draft_edited"] is True

    approved = client.post(f"{PREFIX}/proposals/{proposal.id}/approve", headers=auth, json={})
    assert approved.status_code == 200
    assert approved.json()["execution"]["result"]["draft_body"] == "My own wording, thanks."


def test_closing_an_exception_requires_a_note(client, auth, session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, expected_in=-6)
    session.flush()
    exception_engine.run(session)
    session.flush()
    exception_id = client.get(f"{PREFIX}/exceptions", headers=auth).json()["items"][0]["id"]

    without = client.post(
        f"{PREFIX}/exceptions/{exception_id}/status", headers=auth, json={"status": "resolved"}
    )
    assert without.status_code == 422

    with_note = client.post(
        f"{PREFIX}/exceptions/{exception_id}/status",
        headers=auth,
        json={"status": "resolved", "note": "Supplier delivered this morning."},
    )
    assert with_note.status_code == 200
    assert with_note.json()["status"] == "resolved"


def test_message_ingestion_through_the_api(client, auth, session, supplier, yarn):
    make_purchase_order(session, supplier, yarn, number="PO-00042", expected_in=5)
    session.flush()
    response = client.post(
        f"{PREFIX}/messages",
        headers=auth,
        json={
            "body": "Regarding PO-00042, dispatch is delayed by 3 days. Truck breakdown.",
            "sender": "dispatch@sribalaji.example",
            "subject": "Delay",
            "channel": "manual",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message"]["intent"] == "supplier_delay"
    assert body["facts_applied"] == 1


def test_uploading_a_csv_is_parsed_and_listed(client, auth, session):
    csv = b"material,quantity,unit\n40s Combed Cotton Yarn,1200,kg\n"
    response = client.post(
        f"{PREFIX}/documents",
        headers=auth,
        files={"file": ("stock.csv", csv, "text/csv")},
        data={"channel": "upload", "process_now": "true"},
    )
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["status"] in {"extracted", "needs_review"}

    listing = client.get(f"{PREFIX}/documents", headers=auth)
    assert any(d["id"] == document["id"] for d in listing.json())


def test_an_executable_upload_is_refused(client, auth):
    response = client.post(
        f"{PREFIX}/documents",
        headers=auth,
        files={"file": ("payload.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_search_finds_records_by_their_business_reference(
    client, auth, session, customer, fabric, supplier, yarn
):
    make_sales_order(session, customer, fabric, number="SO-4242")
    make_purchase_order(session, supplier, yarn, number="PO-00042")
    session.flush()

    hits = client.get(f"{PREFIX}/search", params={"q": "SO-4242"}, headers=auth).json()
    assert hits and hits[0]["entity_type"] == "sales_order"

    hits = client.get(f"{PREFIX}/search", params={"q": "Balaji"}, headers=auth).json()
    assert any(hit["entity_type"] == "supplier" for hit in hits)

    hits = client.get(f"{PREFIX}/search", params={"q": "40s"}, headers=auth).json()
    assert any(hit["entity_type"] == "material" for hit in hits)


def test_audit_log_records_who_did_what(client, auth, session, supplier, user):
    proposal = actions.create_proposal(
        session,
        action_type=ActionType.ACKNOWLEDGE_ONLY,
        title="Acknowledge",
        rationale="Noted.",
        payload={"note": "Seen."},
        origin=ProposalOrigin.HUMAN,
        created_by_user_id=user.id,
    )
    session.flush()
    # Approved by a colleague, not by its own author. A person approving the
    # proposal they raised is refused now — "propose, approve, execute" done
    # by one person is a log, not a control — and the audit trail is more
    # interesting when it names two people anyway.
    approver = User(
        email=f"approver-{uuid.uuid4().hex[:6]}@example.com",
        full_name="Second Pair Of Eyes",
        role=UserRole.OPERATIONS,
        password_hash=hash_password("password123"),
    )
    session.add(approver)
    session.flush()
    actions.approve(session, proposal, user_id=approver.id)
    session.flush()

    events = client.get(f"{PREFIX}/audit", headers=auth).json()
    actions_seen = {event["action"] for event in events}
    assert {"proposal.created", "proposal.approved", "action.executed"} <= actions_seen


def test_settings_are_honest_about_missing_integrations(client, auth):
    body = client.get(f"{PREFIX}/settings", headers=auth).json()
    integrations = {item["key"]: item for item in body["integrations"]}
    assert integrations["email"]["status"] == "not_implemented"
    assert integrations["whatsapp"]["status"] == "not_implemented"
    assert integrations["anthropic"]["configured"] is False


def test_product_metrics_endpoint(client, auth):
    body = client.get(f"{PREFIX}/metrics/product", headers=auth).json()
    assert "counters" in body and "durations" in body
    assert "hours saved" in body["caveat"].lower()


def test_the_order_list_shows_open_orders_unless_asked_otherwise(
    client, auth, session, customer, fabric
):
    """A cleared 'include closed and delivered' box must mean what it says."""
    from textileops.models.enums import SalesOrderStatus

    make_sales_order(session, customer, fabric, number="SO-OPEN", status=SalesOrderStatus.CONFIRMED)
    make_sales_order(
        session, customer, fabric, number="SO-DONE", status=SalesOrderStatus.DELIVERED
    )
    session.flush()

    default = client.get(f"{PREFIX}/orders", headers=auth).json()
    numbers = {item["number"] for item in default["items"]}
    assert "SO-OPEN" in numbers
    assert "SO-DONE" not in numbers

    everything = client.get(
        f"{PREFIX}/orders", params={"include_closed": "true"}, headers=auth
    ).json()
    assert "SO-DONE" in {item["number"] for item in everything["items"]}


def test_navigation_counts_agree_with_the_lists_they_summarise(client, auth, session):
    """A badge that says 3 above a list of 5 is a badge nobody trusts again."""
    counts = client.get(f"{PREFIX}/system/counts", headers=auth)
    assert counts.status_code == 200, counts.text
    body = counts.json()
    exceptions = client.get(f"{PREFIX}/exceptions", headers=auth).json()
    assert body["exceptions"] == exceptions["total"]
    assert body["critical"] == exceptions["counts_by_severity"]["critical"]
    pending = client.get(f"{PREFIX}/proposals", params={"status": "pending_approval"}, headers=auth)
    assert body["approvals"] == len(pending.json())


def test_navigation_counts_need_a_session(client):
    assert client.get(f"{PREFIX}/system/counts").status_code == 401
