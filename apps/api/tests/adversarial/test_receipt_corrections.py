"""Goods receipt corrections.

A receipt is a statement about what physically arrived. When it turns out to
be wrong, the statement does not stop having been made — so nothing here edits
or deletes one. Every test below checks two things at once: that the numbers
end up right, and that the history of how they got there is still readable.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.conftest import make_batch, make_purchase_order, make_sales_order, moment
from textileops.core.errors import ConflictError, ValidationError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import MovementType, PurchaseOrderStatus
from textileops.models.inventory import InventoryLot, InventoryMovement
from textileops.models.platform import AuditEvent
from textileops.models.procurement import (
    PurchaseOrderReceipt,
    PurchaseOrderReceiptCorrection,
)
from textileops.services import inventory, procurement, production

D = Decimal
ZERO = D("0.000")


@pytest.fixture
def received(session, supplier, yarn, user):
    """1,000 kg ordered, 1,000 kg keyed in as received."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"))
    session.flush()
    line = po.lines[0]
    outcome = procurement.receive(
        session, line, accepted_quantity=D("1000"), user_id=user.id
    )
    session.flush()
    return po, line, outcome.receipt


def _lot_of(session, receipt) -> InventoryLot:
    lot = session.get(InventoryLot, receipt.inventory_lot_id)
    assert lot is not None
    return lot


def _ledger(session, lot_id) -> Decimal:
    return session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
            InventoryMovement.lot_id == lot_id
        )
    )


# --- The ordinary case --------------------------------------------------------


def test_a_partial_correction_leaves_both_the_receipt_and_the_correction_readable(
    session, received, user
):
    """1,000 keyed, 900 actually arrived.

    Afterwards the books must say 900 — and must still say that somebody once
    claimed 1,000, when, and why that changed.
    """
    _po, line, receipt = received
    lot = _lot_of(session, receipt)

    outcome = procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("100"),
        reason="Weighbridge ticket says 900 kg; 1,000 was keyed from the challan.",
        user_id=user.id,
    )
    session.flush()

    # The original statement is untouched.
    assert receipt.accepted_quantity == D("1000.000")
    # The corrected figure is derived, not stored over the top of it.
    assert receipt.corrected_accepted_quantity == D("900.000")
    assert receipt.is_corrected

    assert outcome.stock_removed == D("100.000")
    assert line.received_quantity == D("900.000")
    assert line.outstanding_quantity == D("100.000")
    assert lot.quantity_on_hand == D("900.000")
    assert _ledger(session, lot.id) == D("900.000"), "the ledger must still balance"

    movements = session.scalars(
        select(InventoryMovement).where(InventoryMovement.lot_id == lot.id)
    ).all()
    kinds = [m.movement_type for m in movements]
    assert MovementType.RECEIPT in kinds
    assert MovementType.RECEIPT_CORRECTION in kinds, (
        "the stock left through the ledger, not by editing a number"
    )

    correction = outcome.correction
    assert correction.corrected_by_user_id == user.id
    assert "weighbridge" in correction.reason.lower()
    assert correction.corrected_at is not None
    assert correction.inventory_movement_id is not None


def test_the_correction_is_on_the_audit_trail_with_its_reason(session, received, user):
    _po, _line, receipt = received
    procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("100"),
        reason="Short delivery confirmed with the transporter.",
        user_id=user.id,
    )
    session.flush()

    events = session.scalars(
        select(AuditEvent).where(AuditEvent.action == "purchase_order.receipt_corrected")
    ).all()
    assert len(events) == 1
    assert events[0].actor_user_id == user.id
    assert "transporter" in events[0].summary


def test_a_full_reversal_empties_the_lot_and_reopens_the_line(session, received, user):
    """The whole delivery turned out to be somebody else's."""
    po, line, receipt = received
    lot = _lot_of(session, receipt)

    procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("1000"),
        reason="Delivery belonged to another mill; returned to the transporter.",
        user_id=user.id,
    )
    session.flush()

    assert receipt.corrected_accepted_quantity == ZERO
    assert line.received_quantity == ZERO
    assert line.outstanding_quantity == D("1000.000")
    assert lot.quantity_on_hand == ZERO
    assert _ledger(session, lot.id) == ZERO
    assert po.status != PurchaseOrderStatus.RECEIVED, (
        "a fully reversed receipt cannot leave the order looking delivered"
    )


def test_a_correction_followed_by_a_replacement_receipt_lands_on_the_right_total(
    session, received, user
):
    """The realistic repair: reverse the wrong figure, key the right one."""
    _po, line, receipt = received

    procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("1000"),
        reason="Keyed against the wrong line.",
        user_id=user.id,
    )
    session.flush()
    procurement.receive(session, line, accepted_quantity=D("850"), user_id=user.id)
    session.flush()

    assert line.received_quantity == D("850.000")
    assert line.outstanding_quantity == D("150.000")
    lots = session.scalars(
        select(InventoryLot).where(InventoryLot.purchase_order_line_id == line.id)
    ).all()
    assert sum((lot.quantity_on_hand for lot in lots), ZERO) == D("850.000")
    for lot in lots:
        assert lot.quantity_on_hand == _ledger(session, lot.id)


def test_several_corrections_against_one_receipt_accumulate(session, received, user):
    _po, line, receipt = received

    procurement.correct_receipt(
        session, receipt, accepted_delta=D("60"), reason="First recount.", user_id=user.id
    )
    session.flush()
    procurement.correct_receipt(
        session, receipt, accepted_delta=D("40"), reason="Second recount.", user_id=user.id
    )
    session.flush()

    assert receipt.corrected_accepted_quantity == D("900.000")
    assert line.received_quantity == D("900.000")
    assert len(receipt.corrections) == 2
    assert _lot_of(session, receipt).quantity_on_hand == D("900.000")


# --- Refusals -----------------------------------------------------------------


def test_a_correction_cannot_take_a_receipt_below_zero(session, received, user):
    _po, line, receipt = received
    procurement.correct_receipt(
        session, receipt, accepted_delta=D("900"), reason="Recount.", user_id=user.id
    )
    session.flush()

    with pytest.raises(ConflictError) as exc:
        procurement.correct_receipt(
            session,
            receipt,
            accepted_delta=D("200"),
            reason="Recount again.",
            user_id=user.id,
        )
    assert exc.value.details["already_corrected"] == "900.000"
    assert line.received_quantity == D("100.000"), "the refused correction changed nothing"


def test_a_correction_is_refused_when_the_stock_has_already_been_used(
    session, received, fabric, customer, user
):
    """The case that must never be quietly forced through.

    1,000 kg was received and 950 consumed by production. Correcting to 900
    would drive the lot to −50 — which would mean 50 kg of the *consumption*
    did not happen either. Only a person can say which record is wrong, so
    this refuses and says exactly what is in the way.
    """
    _po, line, receipt = received
    lot = _lot_of(session, receipt)

    order = make_sales_order(session, customer, fabric, quantity=D("3000"))
    batch = make_batch(session, fabric, order, quantity=D("3000"))
    session.flush()
    production.start_batch(session, batch)
    production.issue_materials(session, batch)
    session.flush()

    drawn = D("1000.000") - lot.quantity_on_hand
    assert drawn > ZERO, "precondition: production consumed some of this lot"
    remaining = lot.quantity_on_hand

    with pytest.raises(ConflictError) as exc:
        procurement.correct_receipt(
            session,
            receipt,
            accepted_delta=D("1000"),
            reason="Whole delivery was wrong.",
            user_id=user.id,
        )

    assert exc.value.details["lot_code"] == lot.lot_code
    assert Decimal(exc.value.details["on_hand"]) == remaining
    assert Decimal(exc.value.details["short_by"]) == D("1000.000") - remaining
    session.refresh(lot)
    assert lot.quantity_on_hand == remaining, "the refusal left the lot alone"
    assert line.received_quantity == D("1000.000")
    assert _ledger(session, lot.id) == lot.quantity_on_hand


def test_a_correction_within_what_remains_is_still_allowed_after_consumption(
    session, received, fabric, customer, user
):
    """Refusing everything after any consumption would be too blunt."""
    _po, line, receipt = received
    lot = _lot_of(session, receipt)

    order = make_sales_order(session, customer, fabric, quantity=D("1000"))
    batch = make_batch(session, fabric, order, quantity=D("1000"))
    session.flush()
    production.start_batch(session, batch)
    production.issue_materials(session, batch)
    session.flush()

    remaining = lot.quantity_on_hand
    assert remaining > D("50"), "precondition: enough left to correct against"

    procurement.correct_receipt(
        session, receipt, accepted_delta=D("50"), reason="Recount.", user_id=user.id
    )
    session.flush()

    assert lot.quantity_on_hand == remaining - D("50.000")
    assert _ledger(session, lot.id) == lot.quantity_on_hand
    assert line.received_quantity == D("950.000")


def test_a_correction_needs_a_reason(session, received, user):
    _po, _line, receipt = received
    for blank in ("", "   ", "\n\t "):
        with pytest.raises(ValidationError):
            procurement.correct_receipt(
                session, receipt, accepted_delta=D("10"), reason=blank, user_id=user.id
            )


def test_a_correction_cannot_be_used_to_add_stock(session, received, user):
    """A negative correction would be stock arriving without a delivery."""
    _po, _line, receipt = received
    with pytest.raises(ValidationError) as exc:
        procurement.correct_receipt(
            session,
            receipt,
            accepted_delta=D("-100"),
            reason="More arrived than keyed.",
            user_id=user.id,
        )
    assert "post another receipt" in str(exc.value)


def test_a_correction_of_nothing_is_refused(session, received, user):
    _po, _line, receipt = received
    with pytest.raises(ValidationError):
        procurement.correct_receipt(
            session, receipt, accepted_delta=ZERO, reason="Nothing.", user_id=user.id
        )


# --- Replay and units ---------------------------------------------------------


def test_a_replayed_correction_is_a_no_op(session, received, user):
    """At-least-once delivery applies here too."""
    _po, line, receipt = received
    key = "correction:challan-8841"

    first = procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("100"),
        reason="Recount.",
        user_id=user.id,
        idempotency_key=key,
    )
    session.flush()
    second = procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("100"),
        reason="Recount.",
        user_id=user.id,
        idempotency_key=key,
    )
    session.flush()

    assert second.was_replay
    assert second.correction.id == first.correction.id
    assert line.received_quantity == D("900.000")
    assert _lot_of(session, receipt).quantity_on_hand == D("900.000")
    assert session.scalar(
        select(func.count(PurchaseOrderReceiptCorrection.id)).where(
            PurchaseOrderReceiptCorrection.receipt_id == receipt.id
        )
    ) == 1


def test_a_correction_keyed_in_another_unit_converts(session, supplier, yarn, user):
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"))
    session.flush()
    line = po.lines[0]
    receipt = procurement.receive(
        session, line, accepted_quantity=D("1000"), user_id=user.id
    ).receipt
    session.flush()

    procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("100000"),
        unit=UnitOfMeasure.GRAM,
        reason="Recount in grams.",
        user_id=user.id,
    )
    session.flush()

    assert line.received_quantity == D("900.000"), "100,000 g is 100 kg"


def test_a_correction_moves_the_supplier_score(session, supplier, yarn, user):
    """On-time is measured from what the supplier actually delivered."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=-5)
    session.flush()
    line = po.lines[0]
    receipt = procurement.receive(
        session,
        line,
        accepted_quantity=D("1000"),
        received_at=moment(-6),
        user_id=user.id,
    ).receipt
    session.flush()
    assert supplier.on_time_rate == D("1.0000"), "delivered in full, early"

    procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("400"),
        reason="Only 600 kg actually arrived.",
        user_id=user.id,
    )
    session.flush()

    assert line.received_quantity == D("600.000")
    assert supplier.on_time_rate != D("1.0000"), (
        "the line is no longer complete, so the supplier no longer scores for it"
    )


def test_a_correction_does_not_delete_or_edit_the_original_receipt(
    session, received, user
):
    """Invariant 11, applied to receipts: supersede, never erase."""
    _po, _line, receipt = received
    receipt_id = receipt.id
    before = (receipt.accepted_quantity, receipt.rejected_quantity, receipt.received_at)

    procurement.correct_receipt(
        session, receipt, accepted_delta=D("250"), reason="Recount.", user_id=user.id
    )
    session.flush()
    session.expire_all()

    stored = session.get(PurchaseOrderReceipt, receipt_id)
    assert stored is not None, "the receipt was deleted"
    assert (stored.accepted_quantity, stored.rejected_quantity, stored.received_at) == before


def test_correcting_a_receipt_that_brought_in_no_stock_is_refused(
    session, supplier, yarn, user
):
    """A rejected-only receipt has no lot to take stock out of."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"))
    session.flush()
    line = po.lines[0]
    receipt = procurement.receive(
        session,
        line,
        accepted_quantity=ZERO,
        rejected_quantity=D("100"),
        user_id=user.id,
    ).receipt
    session.flush()
    assert receipt.inventory_lot_id is None

    # Correcting the rejected figure needs no stock movement and is fine.
    procurement.correct_receipt(
        session,
        receipt,
        rejected_delta=D("40"),
        reason="Only 60 kg was actually rejected.",
        user_id=user.id,
    )
    session.flush()
    assert receipt.corrected_rejected_quantity == D("60.000")
    assert line.rejected_quantity == D("60.000")

    # Correcting accepted stock that never existed is not.
    with pytest.raises(ConflictError):
        procurement.correct_receipt(
            session,
            receipt,
            accepted_delta=D("10"),
            reason="No.",
            user_id=user.id,
        )


def test_a_correction_after_reservation_surfaces_the_shortage_rather_than_hiding_it(
    session, received, fabric, customer, user
):
    """Correcting below a reservation is allowed, and coverage must show it.

    The stock genuinely is not there, so the reservation was always a promise
    that could not be kept. Blocking the correction would keep the books
    agreeing with a promise instead of with the warehouse.
    """
    from textileops.services import coverage

    _po, _line, receipt = received
    order = make_sales_order(session, customer, fabric, quantity=D("3000"))
    make_batch(session, fabric, order, quantity=D("3000"))
    session.flush()

    material_id = receipt.purchase_order_line.material_id
    before = coverage.analyse_material(session, material_id)
    assert before.on_hand == D("1000.000")
    assert before.allocations[0].coverage_source == "stock", (
        "precondition: the demand is met from stock in the building"
    )

    procurement.correct_receipt(
        session,
        receipt,
        accepted_delta=D("800"),
        reason="Only 200 kg arrived.",
        user_id=user.id,
    )
    session.flush()

    after = coverage.analyse_material(session, material_id)
    assert after.on_hand == D("200.000"), "the stock is gone from the building"
    # The aggregate does not fall: 800 kg goes back onto the purchase order as
    # outstanding, because the supplier still owes it. What changes is *when*
    # it can be had — and that is the part a promised date depends on.
    assert after.incoming == D("800.000")
    assert after.allocations[0].coverage_source == "incoming", (
        "demand that was covered from stock is now waiting on a delivery, and "
        "the coverage screen has to say so"
    )
    assert after.allocations[0].covered_by_date is not None
    assert inventory.ledger_discrepancies(session) == []


# --- Through the HTTP boundary ------------------------------------------------


def test_the_api_refuses_a_correction_without_a_reason(client_with_auth, received):
    client, headers = client_with_auth
    _po, _line, receipt = received

    response = client.post(
        "/api/v1/purchase-orders/receipts/corrections",
        json={"receipt_id": str(receipt.id), "accepted_delta": "100", "reason": ""},
        headers=headers,
    )
    assert response.status_code == 422, response.text


def test_the_api_refuses_a_correction_from_a_viewer(client_with_auth, session, received):
    """Removing 100 kg of stock is not a read."""
    from textileops.core.security import hash_password
    from textileops.models.enums import UserRole
    from textileops.models.org import User

    client, _ = client_with_auth
    _po, line, receipt = received
    viewer = User(
        email="viewer-correction@example.com",
        full_name="Viewer",
        role=UserRole.VIEWER,
        password_hash=hash_password("password123"),
    )
    session.add(viewer)
    session.flush()
    token = client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "password123"},
    ).json()["access_token"]

    response = client.post(
        "/api/v1/purchase-orders/receipts/corrections",
        json={
            "receipt_id": str(receipt.id),
            "accepted_delta": "100",
            "reason": "Recount.",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403, response.text
    session.refresh(line)
    assert line.received_quantity == D("1000.000")


def test_the_api_reports_the_refusal_when_the_stock_is_gone(
    client_with_auth, session, received, fabric, customer
):
    """The operator has to be told what is in the way, not just "no"."""
    client, headers = client_with_auth
    _po, _line, receipt = received
    order = make_sales_order(session, customer, fabric, quantity=D("3000"))
    batch = make_batch(session, fabric, order, quantity=D("3000"))
    session.flush()
    production.start_batch(session, batch)
    production.issue_materials(session, batch)
    session.flush()

    response = client.post(
        "/api/v1/purchase-orders/receipts/corrections",
        json={
            "receipt_id": str(receipt.id),
            "accepted_delta": "1000",
            "reason": "Whole delivery was wrong.",
        },
        headers=headers,
    )
    assert response.status_code == 409, response.text
    body = response.json()
    detail = body.get("detail", body)
    text = str(detail)
    assert "already been used" in text or "less than" in text
