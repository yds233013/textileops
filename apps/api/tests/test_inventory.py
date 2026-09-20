"""Inventory arithmetic. Every figure here must be reproducible by hand."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import moment
from textileops.core.errors import ConflictError, ValidationError
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import LotStatus, MovementType, ReservationStatus
from textileops.services import inventory

D = Decimal


def _lot(session, yarn, quantity="1000", unit=UnitOfMeasure.KG, code=None):
    return inventory.create_lot(
        session,
        lot_code=code or f"LOT-{quantity}-{unit.value}",
        material_id=yarn.id,
        quantity=D(quantity),
        unit=unit,
        received_at=moment(-3),
    )


def test_lot_creation_posts_an_opening_movement(session, yarn):
    lot = _lot(session, yarn)
    assert lot.quantity_on_hand == D("1000.000")
    assert len(lot.movements) == 1
    assert lot.movements[0].movement_type == MovementType.RECEIPT
    assert inventory.recompute_lot_on_hand(session, lot) == lot.quantity_on_hand


def test_issue_reduces_on_hand_and_ledger_agrees(session, yarn):
    lot = _lot(session, yarn)
    inventory.post_movement(
        session, lot=lot, movement_type=MovementType.ISSUE, quantity=D("250")
    )
    session.flush()
    assert lot.quantity_on_hand == D("750.000")
    assert inventory.recompute_lot_on_hand(session, lot) == D("750.000")
    assert inventory.ledger_discrepancies(session) == []


def test_cannot_issue_more_than_is_present(session, yarn):
    lot = _lot(session, yarn)
    with pytest.raises(ConflictError) as exc:
        inventory.post_movement(
            session, lot=lot, movement_type=MovementType.ISSUE, quantity=D("1500")
        )
    assert "cannot issue" in str(exc.value).lower()
    assert lot.quantity_on_hand == D("1000.000")


def test_movement_is_idempotent_under_replay(session, yarn):
    """At-least-once job delivery must never double-post stock."""
    lot = _lot(session, yarn)
    first = inventory.post_movement(
        session,
        lot=lot,
        movement_type=MovementType.ISSUE,
        quantity=D("100"),
        idempotency_key="job-42",
    )
    session.flush()
    second = inventory.post_movement(
        session,
        lot=lot,
        movement_type=MovementType.ISSUE,
        quantity=D("100"),
        idempotency_key="job-42",
    )
    assert first is not None
    assert second is None
    assert lot.quantity_on_hand == D("900.000")


def test_movement_quantity_must_be_a_positive_magnitude(session, yarn):
    lot = _lot(session, yarn)
    with pytest.raises(ValidationError):
        inventory.post_movement(
            session, lot=lot, movement_type=MovementType.ISSUE, quantity=D("-5")
        )


def test_movement_in_another_compatible_unit_converts(session, yarn):
    lot = _lot(session, yarn)
    inventory.post_movement(
        session,
        lot=lot,
        movement_type=MovementType.ISSUE,
        quantity=D("1"),
        unit=UnitOfMeasure.TONNE,
    )
    session.flush()
    assert lot.quantity_on_hand == D("0.000")
    assert lot.status == LotStatus.CONSUMED


def test_available_is_on_hand_minus_reservations(session, yarn):
    _lot(session, yarn, "1000", code="LOT-A")
    _lot(session, yarn, "500", code="LOT-B")
    inventory.reserve(
        session, quantity=D("300"), unit=UnitOfMeasure.KG, material_id=yarn.id
    )
    session.flush()

    position = inventory.material_position(session, yarn.id)
    assert position.on_hand == D("1500.000")
    assert position.reserved == D("300.000")
    assert position.available == D("1200.000")


def test_quarantined_stock_is_present_but_not_available(session, yarn):
    lot = _lot(session, yarn, "800")
    lot.status = LotStatus.QUARANTINE
    session.flush()
    position = inventory.material_position(session, yarn.id)
    assert position.on_hand == D("0.000")
    assert position.quarantined == D("800.000")


def test_reservation_must_target_exactly_one_thing(session, yarn, fabric):
    with pytest.raises(ValidationError):
        inventory.reserve(
            session,
            quantity=D("10"),
            unit=UnitOfMeasure.KG,
            material_id=yarn.id,
            fabric_spec_id=fabric.id,
        )


def test_releasing_reservations_frees_stock(session, yarn):
    _lot(session, yarn, "1000")
    reservation = inventory.reserve(
        session, quantity=D("400"), unit=UnitOfMeasure.KG, material_id=yarn.id
    )
    session.flush()
    assert inventory.material_position(session, yarn.id).available == D("600.000")

    # Released through the service rather than by assigning the column: a
    # release also has to stamp released_at, and the database now enforces
    # that, so a test that writes the status directly is testing a state the
    # application can no longer produce.
    released = inventory.release_reservations(
        session, sales_order_line_id=None, production_batch_id=None
    )
    session.flush()
    assert released == 1
    assert reservation.status == ReservationStatus.RELEASED
    assert reservation.released_at is not None
    assert inventory.material_position(session, yarn.id).available == D("1000.000")


def test_ledger_discrepancy_is_detected(session, yarn):
    """If the stored balance is edited behind the ledger's back, we must notice."""
    lot = _lot(session, yarn, "1000")
    lot.quantity_on_hand = D("1200.000")
    session.flush()
    discrepancies = inventory.ledger_discrepancies(session)
    assert len(discrepancies) == 1
    assert discrepancies[0]["difference"] == D("200.000")
