"""Inventory, materials and coverage."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from textileops.api.deps import CurrentUser, DbSession
from textileops.core.errors import NotFoundError
from textileops.models.catalog import FabricSpec, Material
from textileops.models.inventory import InventoryLot, InventoryMovement
from textileops.services import coverage as coverage_service
from textileops.services import inventory as inventory_service

router = APIRouter(tags=["inventory"])


class MaterialOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    category: str
    base_unit: str
    composition: str | None
    yarn_count_text: str | None
    colour: str | None
    shade_code: str | None
    standard_cost: Decimal | None
    currency: str | None
    reorder_point: Decimal | None
    is_active: bool


class FabricSpecOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    composition: str
    construction: str | None
    gsm: Decimal
    width_cm: Decimal
    colour: str | None
    shade_code: str | None
    finish: str
    sale_unit: str
    standard_lead_time_days: int


class PositionOut(BaseModel):
    material_id: uuid.UUID
    material_code: str
    material_name: str
    category: str
    unit: str
    on_hand: Decimal
    quarantined: Decimal
    reserved: Decimal
    available: Decimal
    incoming: Decimal
    required: Decimal
    projected: Decimal
    over_committed_by: Decimal
    shortage: Decimal
    first_shortfall_date: dt.date | None
    reorder_point: Decimal | None


class AllocationOut(BaseModel):
    production_batch_id: uuid.UUID
    production_batch_code: str
    required_by: dt.date
    quantity: Decimal
    covered_quantity: Decimal
    shortfall_quantity: Decimal
    covered_by_date: dt.date | None
    #: "stock" | "incoming" | "uncovered" — disambiguates a null
    #: covered_by_date, which otherwise reads as "from stock".
    coverage_source: str
    is_short: bool
    is_late: bool
    sales_order_id: uuid.UUID | None
    sales_order_number: str | None
    customer_name: str | None
    promised_date: dt.date | None


class IncomingOut(BaseModel):
    purchase_order_id: uuid.UUID
    purchase_order_number: str
    supplier_name: str
    quantity: Decimal
    unit: str
    expected_date: dt.date
    is_revised: bool


class CoverageOut(BaseModel):
    position: PositionOut
    horizon: dt.date
    allocations: list[AllocationOut]
    incoming: list[IncomingOut]
    explanation: str


class LotOut(BaseModel):
    id: uuid.UUID
    lot_code: str
    material_name: str | None
    fabric_name: str | None
    quantity_on_hand: Decimal
    quantity_received: Decimal
    unit: str
    status: str
    location: str
    received_at: dt.datetime
    supplier_name: str | None
    gsm_actual: Decimal | None
    width_cm_actual: Decimal | None
    shade_code_actual: str | None


class MovementOut(BaseModel):
    id: uuid.UUID
    occurred_at: dt.datetime
    movement_type: str
    quantity_delta: Decimal
    unit: str
    note: str | None


def _position(
    session: DbSession, material: Material
) -> tuple[PositionOut, coverage_service.CoverageResult]:
    result = coverage_service.analyse_material(session, material.id)
    position = inventory_service.material_position(session, material.id)
    return (
        PositionOut(
            material_id=material.id,
            material_code=material.code,
            material_name=material.name,
            category=material.category.value,
            unit=position.unit.value,
            on_hand=position.on_hand,
            quarantined=position.quarantined,
            reserved=position.reserved,
            available=position.available,
            incoming=position.incoming,
            required=position.required,
            projected=position.projected,
            over_committed_by=position.over_committed_by,
            shortage=result.shortage,
            first_shortfall_date=result.first_shortfall_date,
            reorder_point=material.reorder_point,
        ),
        result,
    )


@router.get("/materials", response_model=list[MaterialOut])
def list_materials(
    session: DbSession, _user: CurrentUser, category: str | None = None
) -> list[MaterialOut]:
    stmt = select(Material).order_by(Material.code)
    if category:
        stmt = stmt.where(Material.category == category)
    return [
        MaterialOut(
            id=m.id,
            code=m.code,
            name=m.name,
            category=m.category.value,
            base_unit=m.base_unit.value,
            composition=m.composition,
            yarn_count_text=m.yarn_count_text,
            colour=m.colour,
            shade_code=m.shade_code,
            standard_cost=m.standard_cost,
            currency=m.currency.value if m.currency else None,
            reorder_point=m.reorder_point,
            is_active=m.is_active,
        )
        for m in session.scalars(stmt).all()
    ]


@router.get("/fabric-specs", response_model=list[FabricSpecOut])
def list_fabric_specs(session: DbSession, _user: CurrentUser) -> list[FabricSpecOut]:
    return [
        FabricSpecOut(
            id=spec.id,
            code=spec.code,
            name=spec.name,
            composition=spec.composition,
            construction=spec.construction,
            gsm=spec.gsm,
            width_cm=spec.width_cm,
            colour=spec.colour,
            shade_code=spec.shade_code,
            finish=spec.finish.value,
            sale_unit=spec.sale_unit.value,
            standard_lead_time_days=spec.standard_lead_time_days,
        )
        for spec in session.scalars(select(FabricSpec).order_by(FabricSpec.code)).all()
    ]


@router.get("/inventory/positions", response_model=list[PositionOut])
def list_positions(
    session: DbSession, _user: CurrentUser, shortages_only: bool = False
) -> list[PositionOut]:
    out: list[PositionOut] = []
    for material in session.scalars(
        select(Material).where(Material.is_active).order_by(Material.code)
    ).all():
        position, _ = _position(session, material)
        if shortages_only and position.shortage <= 0:
            continue
        out.append(position)
    return out


@router.get("/inventory/coverage/{material_id}", response_model=CoverageOut)
def material_coverage(
    material_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> CoverageOut:
    material = session.get(Material, material_id)
    if material is None:
        raise NotFoundError(f"Material {material_id} not found.")
    position, result = _position(session, material)
    explanation = (
        f"{result.available} {result.unit.value} is on site and drawable by these "
        f"batches, plus {result.incoming} confirmed incoming, against "
        f"{result.required} required before {result.horizon.isoformat()}. Demand is "
        f"allocated to supply in required-by date order. 'Free to promise' "
        f"({result.free_to_promise} {result.unit.value}) is what remains after every "
        f"existing reservation, and is the figure to use before committing new work."
    )
    return CoverageOut(
        position=position,
        horizon=result.horizon,
        explanation=explanation,
        allocations=[
            AllocationOut(
                production_batch_id=a.requirement.production_batch_id,
                production_batch_code=a.requirement.production_batch_code,
                required_by=a.requirement.required_by,
                quantity=a.requirement.quantity,
                covered_quantity=a.covered_quantity,
                shortfall_quantity=a.shortfall_quantity,
                covered_by_date=a.covered_by_date,
                coverage_source=a.coverage_source,
                is_short=a.is_short,
                is_late=a.is_late,
                sales_order_id=a.sales_order_id,
                sales_order_number=a.sales_order_number,
                customer_name=a.customer_name,
                promised_date=a.promised_date,
            )
            for a in result.allocations
        ],
        incoming=[
            IncomingOut(
                purchase_order_id=line.purchase_order_id,
                purchase_order_number=line.purchase_order_number,
                supplier_name=line.supplier_name,
                quantity=line.quantity,
                unit=line.unit.value,
                expected_date=line.expected_date,
                is_revised=line.is_revised,
            )
            for line in result.incoming_lines
        ],
    )


@router.get("/inventory/lots", response_model=list[LotOut])
def list_lots(
    session: DbSession,
    _user: CurrentUser,
    material_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[LotOut]:
    stmt = select(InventoryLot).order_by(InventoryLot.received_at.desc()).limit(limit)
    if material_id:
        stmt = stmt.where(InventoryLot.material_id == material_id)
    if status:
        stmt = stmt.where(InventoryLot.status == status)
    return [
        LotOut(
            id=lot.id,
            lot_code=lot.lot_code,
            material_name=lot.material.name if lot.material else None,
            fabric_name=lot.fabric_spec.name if lot.fabric_spec else None,
            quantity_on_hand=lot.quantity_on_hand,
            quantity_received=lot.quantity_received,
            unit=lot.unit.value,
            status=lot.status.value,
            location=lot.location,
            received_at=lot.received_at,
            supplier_name=None,
            gsm_actual=lot.gsm_actual,
            width_cm_actual=lot.width_cm_actual,
            shade_code_actual=lot.shade_code_actual,
        )
        for lot in session.scalars(stmt).all()
    ]


@router.get("/inventory/lots/{lot_id}/movements", response_model=list[MovementOut])
def lot_movements(
    lot_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> list[MovementOut]:
    movements = session.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.lot_id == lot_id)
        .order_by(InventoryMovement.occurred_at)
    ).all()
    return [
        MovementOut(
            id=m.id,
            occurred_at=m.occurred_at,
            movement_type=m.movement_type.value,
            quantity_delta=m.quantity_delta,
            unit=m.unit.value,
            note=m.note,
        )
        for m in movements
    ]
