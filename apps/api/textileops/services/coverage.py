"""Material coverage: can we make what we promised, in time?

The question this module answers is the one an owner actually asks:

    Material M is required by orders A, B and C.
    Available today is X, confirmed incoming before date D is Y,
    required before D is Z.
    Is there a shortage, and *which orders* does it hit first?

Demand is allocated to supply in **required-by date order** (earliest demand
consumes stock first), which mirrors how a factory really draws material and
makes the "which order is starved" answer stable and explainable.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.units import UnitOfMeasure, quantize
from textileops.models.catalog import Material
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock
from textileops.services.inventory import (
    IncomingLine,
    RequirementLine,
    material_position,
)

ZERO = Decimal("0")


@dataclass
class DemandAllocation:
    """One demand line and whether supply reaches it in time."""

    requirement: RequirementLine
    covered_quantity: Decimal
    shortfall_quantity: Decimal
    #: Earliest date by which the covering supply is actually on site.
    covered_by_date: dt.date | None
    sales_order_id: uuid.UUID | None = None
    sales_order_number: str | None = None
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    promised_date: dt.date | None = None

    @property
    def is_short(self) -> bool:
        return self.shortfall_quantity > ZERO

    @property
    def coverage_source(self) -> str:
        """Where the covered portion actually comes from.

        ``covered_by_date is None`` means two opposite things: the demand is
        met entirely out of stock already in the building (stock has no arrival
        date), or nothing covers it at all. Reading the date alone, a wholly
        uncovered line looks exactly like a comfortably stocked one — so the
        screen reported "from stock" for material we do not have.
        """
        if self.covered_quantity <= ZERO:
            return "uncovered"
        if self.covered_by_date is None:
            return "stock"
        return "incoming"

    @property
    def is_late(self) -> bool:
        """Covered, but only by stock that lands after it is needed."""
        return (
            not self.is_short
            and self.covered_by_date is not None
            and self.covered_by_date > self.requirement.required_by
        )


@dataclass
class CoverageResult:
    material_id: uuid.UUID
    material_code: str
    material_name: str
    unit: UnitOfMeasure
    horizon: dt.date
    #: Stock the open batches can draw on: on-hand less any reservation that is
    #: not already represented by one of the demand lines below.
    available: Decimal
    on_hand: Decimal
    free_to_promise: Decimal
    incoming: Decimal
    required: Decimal
    shortage: Decimal
    allocations: list[DemandAllocation] = field(default_factory=list)
    incoming_lines: list[IncomingLine] = field(default_factory=list)

    @property
    def has_shortage(self) -> bool:
        return self.shortage > ZERO

    @property
    def affected_sales_order_ids(self) -> list[uuid.UUID]:
        seen: list[uuid.UUID] = []
        for allocation in self.allocations:
            if (
                (allocation.is_short or allocation.is_late)
                and allocation.sales_order_id
                and allocation.sales_order_id not in seen
            ):
                seen.append(allocation.sales_order_id)
        return seen

    @property
    def first_shortfall_date(self) -> dt.date | None:
        dates = [a.requirement.required_by for a in self.allocations if a.is_short or a.is_late]
        return min(dates) if dates else None


def analyse_material(
    session: Session,
    material_id: uuid.UUID,
    *,
    horizon: dt.date | None = None,
) -> CoverageResult:
    """Allocate available + incoming supply against demand, in date order."""
    horizon = horizon or (clock.today() + dt.timedelta(days=90))
    position = material_position(session, material_id, by_date=horizon)

    # Supply pool: stock on site now, then each inbound receipt on its date.
    supply: list[tuple[dt.date | None, Decimal]] = [(None, position.supply_for_coverage)]
    supply += [(line.expected_date, line.quantity) for line in position.incoming_lines]
    supply_index = 0
    remaining = supply[0][1] if supply else ZERO

    allocations: list[DemandAllocation] = []
    order_context = _sales_order_context(
        session, [r.sales_order_line_id for r in position.requirement_lines]
    )

    for requirement in position.requirement_lines:
        needed = requirement.quantity
        covered = ZERO
        covered_by: dt.date | None = None

        while needed > ZERO and supply_index < len(supply):
            supply_date, _ = supply[supply_index]
            take = min(remaining, needed)
            if take > ZERO:
                covered += take
                needed -= take
                remaining -= take
                if supply_date is not None and (covered_by is None or supply_date > covered_by):
                    covered_by = supply_date
            if remaining <= ZERO:
                supply_index += 1
                if supply_index < len(supply):
                    remaining = supply[supply_index][1]
            if take <= ZERO and remaining <= ZERO and supply_index >= len(supply):
                break

        context = (
            order_context.get(requirement.sales_order_line_id)
            if requirement.sales_order_line_id
            else None
        )
        allocations.append(
            DemandAllocation(
                requirement=requirement,
                covered_quantity=quantize(covered),
                shortfall_quantity=quantize(max(ZERO, needed)),
                covered_by_date=covered_by,
                sales_order_id=context[0] if context else None,
                sales_order_number=context[1] if context else None,
                customer_id=context[2] if context else None,
                customer_name=context[3] if context else None,
                promised_date=context[4] if context else None,
            )
        )

    shortage = quantize(sum((a.shortfall_quantity for a in allocations), ZERO))
    return CoverageResult(
        material_id=position.material_id,
        material_code=position.material_code,
        material_name=position.material_name,
        unit=position.unit,
        horizon=horizon,
        available=position.supply_for_coverage,
        on_hand=position.on_hand,
        free_to_promise=position.available,
        incoming=position.incoming,
        required=position.required,
        shortage=shortage,
        allocations=allocations,
        incoming_lines=position.incoming_lines,
    )


def _sales_order_context(
    session: Session, line_ids: list[uuid.UUID | None]
) -> dict[uuid.UUID, tuple[uuid.UUID, str, uuid.UUID, str, dt.date]]:
    ids = [i for i in line_ids if i is not None]
    if not ids:
        return {}
    rows = session.execute(
        select(SalesOrderLine.id, SalesOrder, SalesOrderLine.promised_date)
        .join(SalesOrder, SalesOrderLine.sales_order_id == SalesOrder.id)
        .where(SalesOrderLine.id.in_(ids))
    ).all()
    return {
        line_id: (
            order.id,
            order.number,
            order.customer_id,
            order.customer.name,
            line_promised or order.promised_date,
        )
        for line_id, order, line_promised in rows
    }


def analyse_all_materials(
    session: Session, *, horizon: dt.date | None = None
) -> list[CoverageResult]:
    """Coverage for every material that has open demand or stock."""
    results = []
    for material_id in session.scalars(select(Material.id).where(Material.is_active)).all():
        result = analyse_material(session, material_id, horizon=horizon)
        if result.required > ZERO or result.on_hand != ZERO or result.incoming > ZERO:
            results.append(result)
    return results
