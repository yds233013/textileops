"""Shared helpers for the adversarial suite.

These tests exist to break TextileOps, not to confirm it works. Each one
encodes a defect that was found by tracing the implementation rather than by
reading its documentation — so when one fails, the implementation is wrong, not
the test.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.enums import LotStatus, ReservationStatus
from textileops.models.inventory import InventoryLot, InventoryMovement, InventoryReservation
from textileops.services import inventory

D = Decimal
ZERO = D("0")


def ledger_total(session: Session, lot: InventoryLot) -> Decimal:
    """Sum of a lot's movements, independent of the stored balance."""
    deltas = session.scalars(
        select(InventoryMovement.quantity_delta).where(InventoryMovement.lot_id == lot.id)
    ).all()
    return quantize(sum(deltas, ZERO))


def assert_ledger_consistent(session: Session) -> None:
    """Every lot's stored balance equals the sum of its movements."""
    session.flush()
    broken = inventory.ledger_discrepancies(session)
    assert broken == [], f"ledger drift: {broken}"


def physical_total(
    session: Session, *, material_id=None, fabric_spec_id=None, unit: UnitOfMeasure
) -> Decimal:
    """Everything physically present, whatever its lot status.

    Deliberately not filtered by status: quarantined and rejected stock is
    still in the building, and an accounting identity that ignores it is not an
    identity.
    """
    stmt = select(InventoryLot)
    if material_id is not None:
        stmt = stmt.where(InventoryLot.material_id == material_id)
    else:
        stmt = stmt.where(InventoryLot.fabric_spec_id == fabric_spec_id)
    total = ZERO
    for lot in session.scalars(stmt).all():
        total += convert(lot.quantity_on_hand, lot.unit, unit)
    return quantize(total)


def active_reservations(
    session: Session, material_id, unit: UnitOfMeasure
) -> Decimal:
    total = ZERO
    for reservation in session.scalars(
        select(InventoryReservation).where(
            InventoryReservation.material_id == material_id,
            InventoryReservation.status == ReservationStatus.ACTIVE,
        )
    ).all():
        total += convert(reservation.quantity, reservation.unit, unit)
    return quantize(total)


def lot_statuses(session: Session, material_id) -> dict[str, LotStatus]:
    return {
        lot.lot_code: lot.status
        for lot in session.scalars(
            select(InventoryLot).where(InventoryLot.material_id == material_id)
        ).all()
    }
