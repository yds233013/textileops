"""Deterministic inventory.

Authoritative stock arithmetic lives here and nowhere else. No language model
ever computes a quantity in TextileOps.

Definitions used consistently across the product:

===============  =========================================================
on_hand          Physical stock present in lots that are AVAILABLE.
quarantined      Physical stock held in QUARANTINE (present, not usable).
reserved         Sum of ACTIVE reservations against that stock.
available        ``on_hand − reserved``. What you can actually commit.
incoming         Outstanding quantity on open purchase-order lines.
required         Outstanding demand from production requirements.
projected        ``available + incoming(by date) − required(by date)``.
===============  =========================================================

Every quantity is converted into the material's ``base_unit`` (or the fabric
spec's ``sale_unit``) before being combined. Mixing dimensions raises.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.errors import ConflictError, NotFoundError, ValidationError
from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.catalog import FabricSpec, Material
from textileops.models.enums import (
    OPEN_PO_STATUSES,
    EntityType,
    LotStatus,
    MovementType,
    ProductionStatus,
    ReservationStatus,
)
from textileops.models.inventory import InventoryLot, InventoryMovement, InventoryReservation
from textileops.models.procurement import PurchaseOrder, PurchaseOrderLine
from textileops.models.production import ProductionBatch, ProductionMaterialRequirement
from textileops.services import clock

ZERO = Decimal("0")

#: Movement types that increase stock. Everything else decreases it.
INBOUND_MOVEMENTS = {
    MovementType.RECEIPT,
    MovementType.RETURN,
    MovementType.PRODUCTION_OUTPUT,
}


@dataclass(frozen=True)
class IncomingLine:
    purchase_order_id: uuid.UUID
    purchase_order_number: str
    purchase_order_line_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str
    quantity: Decimal
    unit: UnitOfMeasure
    expected_date: dt.date
    is_revised: bool


@dataclass(frozen=True)
class RequirementLine:
    production_batch_id: uuid.UUID
    production_batch_code: str
    sales_order_line_id: uuid.UUID | None
    quantity: Decimal
    unit: UnitOfMeasure
    required_by: dt.date
    status: ProductionStatus


@dataclass
class MaterialPosition:
    """A complete, explainable stock position for one material."""

    material_id: uuid.UUID
    material_code: str
    material_name: str
    unit: UnitOfMeasure
    on_hand: Decimal
    quarantined: Decimal
    reserved: Decimal
    available: Decimal
    incoming: Decimal
    required: Decimal
    #: Reservations that are *not* mirrored by an open batch requirement (for
    #: example stock set aside directly against a customer order). Coverage
    #: subtracts only these, because batch reservations and batch requirements
    #: are two records of the same demand — netting both would count it twice.
    reserved_outside_open_batches: Decimal = ZERO
    incoming_lines: list[IncomingLine] = field(default_factory=list)
    requirement_lines: list[RequirementLine] = field(default_factory=list)

    @property
    def projected(self) -> Decimal:
        """Where this material lands once every open batch has taken its share.

        Built from :attr:`supply_for_coverage`, not from ``available``:
        ``available`` has already netted off the reservations that *mirror*
        those same requirements, so subtracting the requirements again would
        count the demand twice.
        """
        return quantize(self.supply_for_coverage + self.incoming - self.required)

    @property
    def over_committed_by(self) -> Decimal:
        """How far reservations exceed the stock on the floor, if they do."""
        return max(ZERO, quantize(self.reserved - self.on_hand))

    @property
    def supply_for_coverage(self) -> Decimal:
        """Stock the open batches can actually draw on.

        Clamped at zero: physical stock cannot be negative. Reservations that
        exceed what is on the floor are a data problem, surfaced by the
        inventory-anomaly detector rather than smuggled into a coverage figure.
        """
        return max(ZERO, quantize(self.on_hand - self.reserved_outside_open_batches))


# --- Lot & movement posting ---------------------------------------------------


def create_lot(
    session: Session,
    *,
    lot_code: str,
    unit: UnitOfMeasure,
    quantity: Decimal,
    received_at: dt.datetime | None = None,
    material_id: uuid.UUID | None = None,
    fabric_spec_id: uuid.UUID | None = None,
    status: LotStatus = LotStatus.AVAILABLE,
    movement_type: MovementType = MovementType.RECEIPT,
    reference_type: EntityType | None = None,
    reference_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    source_document_id: uuid.UUID | None = None,
    movement_note: str = "Opening receipt",
    **kwargs: object,
) -> InventoryLot:
    """Create a lot together with its opening movement.

    The opening movement's type and references are supplied here rather than
    patched afterwards: a caller that had to reach back into ``lot.movements``
    would depend on a lazy relationship being loaded, and would silently do
    nothing when it was not.
    """
    if (material_id is None) == (fabric_spec_id is None):
        raise ValidationError("A lot must reference exactly one material or one fabric spec.")
    if quantity <= 0:
        raise ValidationError("A new lot must have a positive quantity.")

    lot = InventoryLot(
        lot_code=lot_code,
        material_id=material_id,
        fabric_spec_id=fabric_spec_id,
        quantity_received=quantize(quantity),
        quantity_on_hand=quantize(quantity),
        unit=unit,
        status=status,
        received_at=received_at or clock.now(),
        **kwargs,  # type: ignore[arg-type]
    )
    session.add(lot)
    session.flush()
    movement = InventoryMovement(
        lot_id=lot.id,
        movement_type=movement_type,
        quantity_delta=quantize(quantity),
        unit=unit,
        occurred_at=lot.received_at,
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        source_document_id=source_document_id,
        note=movement_note,
    )
    session.add(movement)
    lot.movements.append(movement)
    session.flush()
    return lot


def post_movement(
    session: Session,
    *,
    lot: InventoryLot,
    movement_type: MovementType,
    quantity: Decimal,
    unit: UnitOfMeasure | None = None,
    occurred_at: dt.datetime | None = None,
    reference_type: EntityType | None = None,
    reference_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    note: str | None = None,
    source_document_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
) -> InventoryMovement | None:
    """Apply a stock movement to a lot.

    ``quantity`` is always supplied as a positive magnitude; the sign is
    derived from ``movement_type`` so callers cannot accidentally invert it.
    Returns ``None`` when ``idempotency_key`` has already been posted — replayed
    jobs must never double-count stock.
    """
    quantity = Decimal(str(quantity))
    if quantity <= 0:
        raise ValidationError("Movement quantity must be a positive magnitude.")

    if idempotency_key:
        existing = session.scalar(
            select(InventoryMovement).where(
                InventoryMovement.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return None

    movement_unit = unit or lot.unit
    delta = convert(quantity, movement_unit, lot.unit)
    if movement_type not in INBOUND_MOVEMENTS:
        delta = -delta

    new_on_hand = quantize(lot.quantity_on_hand + delta)
    if new_on_hand < ZERO:
        raise ConflictError(
            f"Lot {lot.lot_code} holds {lot.quantity_on_hand} {lot.unit.value}; "
            f"cannot issue {quantity} {movement_unit.value}.",
            details={
                "lot_code": lot.lot_code,
                "on_hand": str(lot.quantity_on_hand),
                "requested": str(quantity),
            },
        )

    movement = InventoryMovement(
        lot_id=lot.id,
        movement_type=movement_type,
        quantity_delta=delta,
        unit=lot.unit,
        occurred_at=occurred_at or clock.now(),
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        note=note,
        source_document_id=source_document_id,
        created_by_user_id=created_by_user_id,
    )
    session.add(movement)
    lot.quantity_on_hand = new_on_hand
    if new_on_hand == ZERO and lot.status == LotStatus.AVAILABLE:
        lot.status = LotStatus.CONSUMED
    return movement


def recompute_lot_on_hand(session: Session, lot: InventoryLot) -> Decimal:
    """Rebuild on-hand from the movement ledger. Used by integrity checks."""
    movements = session.scalars(
        select(InventoryMovement.quantity_delta).where(InventoryMovement.lot_id == lot.id)
    ).all()
    total = sum(movements, ZERO)
    return quantize(total)


def ledger_discrepancies(session: Session) -> list[dict[str, object]]:
    """Lots whose stored on-hand disagrees with their movement ledger."""
    out: list[dict[str, object]] = []
    for lot in session.scalars(select(InventoryLot)).all():
        ledger = recompute_lot_on_hand(session, lot)
        if ledger != quantize(lot.quantity_on_hand):
            out.append(
                {
                    "lot_id": lot.id,
                    "lot_code": lot.lot_code,
                    "stored_on_hand": lot.quantity_on_hand,
                    "ledger_on_hand": ledger,
                    "difference": quantize(lot.quantity_on_hand - ledger),
                    "unit": lot.unit.value,
                }
            )
    return out


# --- Reservations -------------------------------------------------------------


def reserve(
    session: Session,
    *,
    quantity: Decimal,
    unit: UnitOfMeasure,
    material_id: uuid.UUID | None = None,
    fabric_spec_id: uuid.UUID | None = None,
    sales_order_line_id: uuid.UUID | None = None,
    production_batch_id: uuid.UUID | None = None,
    required_by: dt.date | None = None,
    note: str | None = None,
) -> InventoryReservation:
    """Reserve stock against a demand.

    Reservations may exceed available stock: that is precisely the condition
    the shortage detector looks for. Refusing to record demand would hide it.
    """
    if (material_id is None) == (fabric_spec_id is None):
        raise ValidationError("A reservation must target exactly one material or fabric spec.")
    reservation = InventoryReservation(
        material_id=material_id,
        fabric_spec_id=fabric_spec_id,
        quantity=quantize(quantity),
        unit=unit,
        status=ReservationStatus.ACTIVE,
        sales_order_line_id=sales_order_line_id,
        production_batch_id=production_batch_id,
        required_by=required_by,
        note=note,
    )
    session.add(reservation)
    return reservation


def release_reservations(
    session: Session,
    *,
    production_batch_id: uuid.UUID | None = None,
    sales_order_line_id: uuid.UUID | None = None,
    status: ReservationStatus = ReservationStatus.RELEASED,
) -> int:
    stmt = select(InventoryReservation).where(
        InventoryReservation.status == ReservationStatus.ACTIVE
    )
    if production_batch_id:
        stmt = stmt.where(InventoryReservation.production_batch_id == production_batch_id)
    if sales_order_line_id:
        stmt = stmt.where(InventoryReservation.sales_order_line_id == sales_order_line_id)
    count = 0
    for reservation in session.scalars(stmt).all():
        reservation.status = status
        reservation.released_at = clock.now()
        count += 1
    return count


# --- Position queries ---------------------------------------------------------


def _sum_lots(
    session: Session,
    *,
    material: Material | None = None,
    fabric_spec: FabricSpec | None = None,
    statuses: tuple[LotStatus, ...],
    target_unit: UnitOfMeasure,
) -> Decimal:
    stmt = select(InventoryLot).where(InventoryLot.status.in_(statuses))
    if material is not None:
        stmt = stmt.where(InventoryLot.material_id == material.id)
    else:
        assert fabric_spec is not None
        stmt = stmt.where(InventoryLot.fabric_spec_id == fabric_spec.id)
    total = ZERO
    for lot in session.scalars(stmt).all():
        total += convert(lot.quantity_on_hand, lot.unit, target_unit)
    return quantize(total)


def _sum_reservations(
    session: Session,
    *,
    material_id: uuid.UUID | None = None,
    fabric_spec_id: uuid.UUID | None = None,
    target_unit: UnitOfMeasure,
    by_date: dt.date | None = None,
    exclude_production_batch_ids: set[uuid.UUID] | None = None,
) -> Decimal:
    stmt = select(InventoryReservation).where(
        InventoryReservation.status == ReservationStatus.ACTIVE
    )
    if exclude_production_batch_ids:
        stmt = stmt.where(
            (InventoryReservation.production_batch_id.is_(None))
            | (InventoryReservation.production_batch_id.notin_(exclude_production_batch_ids))
        )
    if material_id is not None:
        stmt = stmt.where(InventoryReservation.material_id == material_id)
    else:
        stmt = stmt.where(InventoryReservation.fabric_spec_id == fabric_spec_id)
    if by_date is not None:
        stmt = stmt.where(
            (InventoryReservation.required_by.is_(None))
            | (InventoryReservation.required_by <= by_date)
        )
    total = ZERO
    for reservation in session.scalars(stmt).all():
        total += convert(reservation.quantity, reservation.unit, target_unit)
    return quantize(total)


def incoming_lines(
    session: Session, material: Material, *, by_date: dt.date | None = None
) -> list[IncomingLine]:
    """Confirmed inbound supply: outstanding quantity on open PO lines."""
    stmt = (
        select(PurchaseOrderLine, PurchaseOrder)
        .join(PurchaseOrder, PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
        .where(
            PurchaseOrderLine.material_id == material.id,
            PurchaseOrder.status.in_(OPEN_PO_STATUSES),
        )
    )
    out: list[IncomingLine] = []
    for line, po in session.execute(stmt).all():
        outstanding = line.outstanding_quantity
        if outstanding <= 0:
            continue
        # A revision at order level supersedes the line's original planned date:
        # the supplier told us about the shipment, not about one line of it.
        # Without this, a stale line date silently hides a known delay.
        expected = po.revised_expected_date or line.expected_date or po.expected_date
        if by_date is not None and expected > by_date:
            continue
        out.append(
            IncomingLine(
                purchase_order_id=po.id,
                purchase_order_number=po.number,
                purchase_order_line_id=line.id,
                supplier_id=po.supplier_id,
                supplier_name=po.supplier.name,
                quantity=convert(outstanding, line.unit, material.base_unit),
                unit=material.base_unit,
                expected_date=expected,
                is_revised=po.revised_expected_date is not None,
            )
        )
    return sorted(out, key=lambda line: line.expected_date)


def requirement_lines(
    session: Session, material: Material, *, by_date: dt.date | None = None
) -> list[RequirementLine]:
    """Outstanding material demand from batches that are not yet finished."""
    open_statuses = (
        ProductionStatus.PLANNED,
        ProductionStatus.SCHEDULED,
        ProductionStatus.IN_PROGRESS,
        ProductionStatus.BLOCKED,
        ProductionStatus.REWORK,
    )
    stmt = (
        select(ProductionMaterialRequirement, ProductionBatch)
        .join(
            ProductionBatch,
            ProductionMaterialRequirement.production_batch_id == ProductionBatch.id,
        )
        .where(
            ProductionMaterialRequirement.material_id == material.id,
            ProductionBatch.status.in_(open_statuses),
        )
    )
    out: list[RequirementLine] = []
    for requirement, batch in session.execute(stmt).all():
        outstanding = requirement.outstanding_quantity
        if outstanding <= 0:
            continue
        if by_date is not None and requirement.required_by > by_date:
            continue
        out.append(
            RequirementLine(
                production_batch_id=batch.id,
                production_batch_code=batch.code,
                sales_order_line_id=batch.sales_order_line_id,
                quantity=convert(outstanding, requirement.unit, material.base_unit),
                unit=material.base_unit,
                required_by=requirement.required_by,
                status=batch.status,
            )
        )
    return sorted(out, key=lambda line: line.required_by)


def material_position(
    session: Session, material_id: uuid.UUID, *, by_date: dt.date | None = None
) -> MaterialPosition:
    material = session.get(Material, material_id)
    if material is None:
        raise NotFoundError(f"Material {material_id} not found.")

    unit = material.base_unit
    on_hand = _sum_lots(
        session, material=material, statuses=(LotStatus.AVAILABLE,), target_unit=unit
    )
    quarantined = _sum_lots(
        session, material=material, statuses=(LotStatus.QUARANTINE,), target_unit=unit
    )
    reserved = _sum_reservations(session, material_id=material.id, target_unit=unit)
    incoming = incoming_lines(session, material, by_date=by_date)
    requirements = requirement_lines(session, material, by_date=by_date)
    open_batch_ids = {line.production_batch_id for line in requirements}
    reserved_outside = _sum_reservations(
        session,
        material_id=material.id,
        target_unit=unit,
        exclude_production_batch_ids=open_batch_ids,
    )

    return MaterialPosition(
        material_id=material.id,
        material_code=material.code,
        material_name=material.name,
        unit=unit,
        on_hand=on_hand,
        quarantined=quarantined,
        reserved=reserved,
        available=quantize(on_hand - reserved),
        reserved_outside_open_batches=reserved_outside,
        incoming=quantize(sum((line.quantity for line in incoming), ZERO)),
        required=quantize(sum((line.quantity for line in requirements), ZERO)),
        incoming_lines=incoming,
        requirement_lines=requirements,
    )


def fabric_available(session: Session, fabric_spec_id: uuid.UUID) -> tuple[Decimal, UnitOfMeasure]:
    """Finished-goods availability for a fabric spec."""
    spec = session.get(FabricSpec, fabric_spec_id)
    if spec is None:
        raise NotFoundError(f"Fabric spec {fabric_spec_id} not found.")
    unit = spec.sale_unit
    on_hand = _sum_lots(
        session, fabric_spec=spec, statuses=(LotStatus.AVAILABLE,), target_unit=unit
    )
    reserved = _sum_reservations(session, fabric_spec_id=spec.id, target_unit=unit)
    return quantize(on_hand - reserved), unit
