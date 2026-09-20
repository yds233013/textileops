"""Customer order control: readiness, risk and timeline.

Order risk is a *derived*, deterministic assessment. It is recomputed from
current state on demand — never stored as a stale column, never produced by a
language model.

Risk ladder
-----------
``LATE``      promised date has passed and quantity is still outstanding.
``AT_RISK``   the earliest date we can be ready is after the promised date.
``WATCH``     we can be ready, but with less than the configured buffer.
``ON_TRACK``  comfortable.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.errors import NotFoundError
from textileops.core.units import UnitOfMeasure, convert, quantize
from textileops.models.enums import (
    OPEN_SALES_ORDER_STATUSES,
    ProductionStatus,
    QCOutcome,
    RiskLevel,
    SalesOrderStatus,
    ShipmentStatus,
)
from textileops.models.logistics import Shipment, ShipmentLine
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock
from textileops.services.inventory import fabric_available

ZERO = Decimal("0")

OPEN_BATCH_STATUSES = (
    ProductionStatus.PLANNED,
    ProductionStatus.SCHEDULED,
    ProductionStatus.IN_PROGRESS,
    ProductionStatus.BLOCKED,
    ProductionStatus.REWORK,
)


class MaterialReadiness:
    READY = "ready"
    PARTIAL = "partial"
    SHORT = "short"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class LineAssessment:
    line_id: uuid.UUID
    line_no: int
    fabric_spec_id: uuid.UUID
    fabric_code: str
    fabric_name: str
    quantity: Decimal
    unit: UnitOfMeasure
    shipped_quantity: Decimal
    produced_quantity: Decimal
    outstanding_quantity: Decimal
    stock_available: Decimal
    #: Quantity still to be made after finished stock is taken into account.
    to_produce: Decimal
    estimated_ready_date: dt.date | None
    promised_date: dt.date
    batch_ids: list[uuid.UUID] = field(default_factory=list)
    blocked_batch_codes: list[str] = field(default_factory=list)
    unit_price: Decimal | None = None

    @property
    def outstanding_value(self) -> Decimal | None:
        if self.unit_price is None:
            return None
        return (self.outstanding_quantity * self.unit_price).quantize(Decimal("0.01"))


@dataclass
class OrderAssessment:
    """Everything an operator needs to understand one order at a glance."""

    order_id: uuid.UUID
    number: str
    customer_id: uuid.UUID
    customer_name: str
    status: SalesOrderStatus
    order_date: dt.date
    promised_date: dt.date
    currency: str
    risk: RiskLevel
    estimated_completion: dt.date | None
    #: Why there is no estimated completion, when there is none. ``None`` means
    #: the order simply has nothing outstanding — it is finished, not stuck.
    #: The three cases used to share one message, which asserted a cause the
    #: system had not determined.
    completion_unknown_reason: str | None
    days_ahead: int | None
    material_readiness: str
    production_status: str
    qc_status: str
    shipment_status: str
    lines: list[LineAssessment] = field(default_factory=list)
    open_exception_ids: list[uuid.UUID] = field(default_factory=list)
    #: Value of quantity not yet shipped. ``None`` when prices are unavailable.
    outstanding_value: Decimal | None = None
    value_basis: str = "unavailable"
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_SALES_ORDER_STATUSES


def allocate_finished_goods(session: Session) -> dict[uuid.UUID, Decimal]:
    """Share the finished-goods pool out across open order lines, once.

    Available stock of a fabric is a single pool. Letting every order line
    compare itself against the whole pool independently promises the same
    rolls to several customers at once — each order looks comfortable, and the
    shortfall is discovered on the last promised date.

    Lines are served in promised-date order (then by order priority), which is
    how a dispatch clerk would actually do it. The result maps each line to the
    quantity of finished stock it may count on, in that line's own unit.
    """
    lines = session.scalars(
        select(SalesOrderLine)
        .join(SalesOrder, SalesOrderLine.sales_order_id == SalesOrder.id)
        .where(SalesOrder.status.in_(OPEN_SALES_ORDER_STATUSES))
    ).all()

    ordered = sorted(
        lines,
        key=lambda line: (
            line.promised_date or line.sales_order.promised_date,
            line.sales_order.priority,
            str(line.id),
        ),
    )

    pools: dict[uuid.UUID, tuple[Decimal, UnitOfMeasure]] = {}
    allocation: dict[uuid.UUID, Decimal] = {}

    for line in ordered:
        outstanding = line.outstanding_quantity
        if line.fabric_spec_id not in pools:
            pools[line.fabric_spec_id] = fabric_available(session, line.fabric_spec_id)
        pool, pool_unit = pools[line.fabric_spec_id]
        if pool <= ZERO or outstanding <= ZERO:
            allocation[line.id] = ZERO
            continue

        wanted = convert(outstanding, line.unit, pool_unit)
        taken = min(pool, wanted)
        pools[line.fabric_spec_id] = (quantize(pool - taken), pool_unit)
        allocation[line.id] = convert(taken, pool_unit, line.unit)

    return allocation


def assess_order(
    session: Session,
    order: SalesOrder | uuid.UUID,
    *,
    finished_goods: dict[uuid.UUID, Decimal] | None = None,
) -> OrderAssessment:
    if not isinstance(order, SalesOrder):
        found = session.get(SalesOrder, order)
        if found is None:
            raise NotFoundError(f"Sales order {order} not found.")
        order = found

    # Computed across every open line so two orders cannot claim the same rolls.
    if finished_goods is None:
        finished_goods = allocate_finished_goods(session)

    today = clock.today()
    lines: list[LineAssessment] = []
    blocked_reasons: list[str] = []
    batch_statuses: list[ProductionStatus] = []
    qc_outcomes: list[QCOutcome] = []
    #: Batches that have produced something, so could have been inspected.
    inspectable_batches = 0

    for line in sorted(order.lines, key=lambda line_: line_.line_no):
        outstanding = line.outstanding_quantity
        stock_in_line_unit = finished_goods.get(line.id, ZERO)
        to_produce = quantize(max(ZERO, outstanding - stock_in_line_unit))

        batches = list(
            session.scalars(
                select(ProductionBatch).where(ProductionBatch.sales_order_line_id == line.id)
            ).all()
        )
        open_batches = [b for b in batches if b.status in OPEN_BATCH_STATUSES]
        batch_statuses.extend(b.status for b in batches)

        for batch in batches:
            if batch.output_quantity > ZERO:
                inspectable_batches += 1
            for inspection in session.scalars(
                select(QCInspection).where(QCInspection.production_batch_id == batch.id)
            ).all():
                qc_outcomes.append(inspection.outcome)

        if to_produce <= ZERO:
            ready_date: dt.date | None = today
        elif open_batches:
            # A batch whose materials are not covered has no honest completion
            # date, and neither does the order that depends on it.
            if any(
                b.actual_completion is None and b.estimated_completion is None
                for b in open_batches
            ):
                ready_date = None
            else:
                ready_date = max(b.effective_completion for b in open_batches)
        else:
            # Nothing in stock and nothing planned: we cannot promise a date.
            ready_date = None

        blocked = [b.code for b in open_batches if b.status == ProductionStatus.BLOCKED]
        blocked_reasons.extend(
            f"{b.code}: {b.blocked_reason}"
            for b in open_batches
            if b.status == ProductionStatus.BLOCKED and b.blocked_reason
        )

        lines.append(
            LineAssessment(
                line_id=line.id,
                line_no=line.line_no,
                fabric_spec_id=line.fabric_spec_id,
                fabric_code=line.fabric_spec.code,
                fabric_name=line.fabric_spec.name,
                quantity=line.quantity,
                unit=line.unit,
                shipped_quantity=line.shipped_quantity,
                produced_quantity=line.produced_quantity,
                outstanding_quantity=outstanding,
                stock_available=stock_in_line_unit,
                to_produce=to_produce,
                estimated_ready_date=ready_date,
                promised_date=line.promised_date or order.promised_date,
                batch_ids=[b.id for b in batches],
                blocked_batch_codes=blocked,
                unit_price=line.unit_price,
            )
        )

    estimated_completion = _combine_ready_dates(lines)
    completion_unknown_reason = _completion_unknown_reason(session, lines)
    risk = _risk_level(order, lines, estimated_completion, today)
    days_ahead = (
        (order.promised_date - estimated_completion).days if estimated_completion else None
    )

    outstanding_value, value_basis = _outstanding_value(lines, order)

    return OrderAssessment(
        order_id=order.id,
        number=order.number,
        customer_id=order.customer_id,
        customer_name=order.customer.name,
        status=order.status,
        order_date=order.order_date,
        promised_date=order.promised_date,
        currency=order.currency.value,
        risk=risk,
        estimated_completion=estimated_completion,
        completion_unknown_reason=completion_unknown_reason,
        days_ahead=days_ahead,
        material_readiness=_material_readiness(session, lines),
        production_status=_production_status(batch_statuses),
        qc_status=_qc_status(
            qc_outcomes,
            batches_with_output=inspectable_batches,
            open_batches=sum(1 for s in batch_statuses if s in OPEN_BATCH_STATUSES),
        ),
        shipment_status=_shipment_status(session, order),
        lines=lines,
        outstanding_value=outstanding_value,
        value_basis=value_basis,
        blocked_reasons=blocked_reasons,
    )


def _completion_unknown_reason(
    session: Session, lines: list[LineAssessment]
) -> str | None:
    """Explain a missing completion date, or return ``None`` if none is missing.

    Three different conditions used to render as one sentence that asserted a
    cause the system had never determined: an order with nothing left to do, an
    order with no production planned, and an order whose batches cannot be
    scheduled because their materials are not covered.
    """
    outstanding = [line for line in lines if line.outstanding_quantity > ZERO]
    if not outstanding:
        return None  # finished: there is no date to be missing
    if all(line.estimated_ready_date is not None for line in outstanding):
        return None

    unknown = [line for line in outstanding if line.estimated_ready_date is None]
    if any(line.batch_ids for line in unknown):
        return "materials_not_covered"
    return "nothing_planned"


def _combine_ready_dates(lines: list[LineAssessment]) -> dt.date | None:
    """An order is ready when its *last* line is ready. Unknown beats optimistic."""
    outstanding_lines = [line for line in lines if line.outstanding_quantity > ZERO]
    if not outstanding_lines:
        return None
    if any(line.estimated_ready_date is None for line in outstanding_lines):
        return None
    return max(line.estimated_ready_date for line in outstanding_lines)  # type: ignore[type-var]


def _risk_level(
    order: SalesOrder,
    lines: list[LineAssessment],
    estimated_completion: dt.date | None,
    today: dt.date,
) -> RiskLevel:
    if order.status in (
        SalesOrderStatus.SHIPPED,
        SalesOrderStatus.DELIVERED,
        SalesOrderStatus.CLOSED,
        SalesOrderStatus.CANCELLED,
    ):
        return RiskLevel.ON_TRACK
    outstanding = sum((line.outstanding_quantity for line in lines), ZERO)
    if outstanding <= ZERO:
        return RiskLevel.ON_TRACK
    if today > order.promised_date:
        return RiskLevel.LATE
    if estimated_completion is None:
        # Outstanding quantity with no stock and no plan: it cannot be on track.
        return RiskLevel.AT_RISK
    if estimated_completion > order.promised_date:
        return RiskLevel.AT_RISK
    buffer_days = (order.promised_date - estimated_completion).days
    if buffer_days < settings.order_at_risk_buffer_days:
        return RiskLevel.WATCH
    return RiskLevel.ON_TRACK


def _material_readiness(session: Session, lines: list[LineAssessment]) -> str:
    """Are the materials for this order's open batches covered?"""
    from textileops.services.coverage import analyse_material

    batch_ids = [bid for line in lines for bid in line.batch_ids]
    if not batch_ids:
        return MaterialReadiness.NOT_APPLICABLE
    batches = list(
        session.scalars(
            select(ProductionBatch).where(
                ProductionBatch.id.in_(batch_ids),
                ProductionBatch.status.in_(OPEN_BATCH_STATUSES),
            )
        ).all()
    )
    if not batches:
        return MaterialReadiness.NOT_APPLICABLE

    material_ids = {req.material_id for batch in batches for req in batch.requirements}
    if not material_ids:
        return MaterialReadiness.NOT_APPLICABLE

    batch_id_set = {b.id for b in batches}
    short = False
    partial = False
    for material_id in material_ids:
        coverage = analyse_material(session, material_id)
        for allocation in coverage.allocations:
            if allocation.requirement.production_batch_id not in batch_id_set:
                continue
            if allocation.is_short:
                short = True
            elif allocation.is_late:
                partial = True
    if short:
        return MaterialReadiness.SHORT
    if partial:
        return MaterialReadiness.PARTIAL
    return MaterialReadiness.READY


def _production_status(statuses: list[ProductionStatus]) -> str:
    """Summarise a set of batch statuses for an operator.

    "Completed" means cloth exists. A batch that was cancelled produced
    nothing, so an order whose batches were all cancelled is *abandoned*, not
    complete — reporting it green is the most dangerous kind of wrong, because
    a green word stops the reader looking any further.
    """
    if not statuses:
        return "not_started"
    if ProductionStatus.BLOCKED in statuses:
        return "blocked"
    if ProductionStatus.REWORK in statuses:
        return "rework"
    if ProductionStatus.IN_PROGRESS in statuses:
        return "in_progress"
    live = [s for s in statuses if s != ProductionStatus.CANCELLED]
    if not live:
        return "cancelled"
    if any(s == ProductionStatus.CANCELLED for s in statuses) and all(
        s == ProductionStatus.COMPLETED for s in live
    ):
        return "partially_cancelled"
    if all(s == ProductionStatus.COMPLETED for s in live):
        return "completed"
    if ProductionStatus.SCHEDULED in statuses:
        return "scheduled"
    return "planned"


def _qc_status(
    outcomes: list[QCOutcome], *, batches_with_output: int, open_batches: int
) -> str:
    """Summarise quality for an order.

    "Passed" claims the whole order is quality-clear, so it is only honest when
    every batch has run *and* every batch that produced something has been
    inspected. One passed batch out of three — with two still to make, or made
    and never looked at — is *partially inspected*. Calling that "Passed"
    invites the reader to stop checking, which is the entire cost of the word.
    """
    if not outcomes:
        return "not_inspected"
    if QCOutcome.REJECT in outcomes:
        return "rejected"
    if QCOutcome.REWORK in outcomes:
        return "rework"
    if QCOutcome.PENDING in outcomes:
        return "pending"
    if QCOutcome.CONDITIONAL_PASS in outcomes:
        return "conditional_pass"
    if open_batches > 0 or batches_with_output > len(outcomes):
        return "partially_inspected"
    return "passed"


def _shipment_status(session: Session, order: SalesOrder) -> str:
    line_ids = [line.id for line in order.lines]
    if not line_ids:
        return "nothing_to_ship"
    shipments = list(
        session.scalars(
            select(Shipment)
            .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.id)
            .where(ShipmentLine.sales_order_line_id.in_(line_ids))
            .distinct()
        ).all()
    )
    if not shipments:
        return "not_shipped"
    statuses = {s.status for s in shipments}
    fully_shipped = all(line.outstanding_quantity <= ZERO for line in order.lines)
    if ShipmentStatus.DELAYED in statuses:
        return "delayed"
    if all(s == ShipmentStatus.DELIVERED for s in statuses) and fully_shipped:
        return "delivered"
    if statuses & {ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT}:
        return "in_transit" if fully_shipped else "partially_shipped"
    if not fully_shipped:
        return "partially_shipped"
    return "packed"


def _outstanding_value(
    lines: list[LineAssessment], order: SalesOrder
) -> tuple[Decimal | None, str]:
    """Value at stake. Honest about missing prices rather than assuming zero."""
    priced = [line for line in lines if line.unit_price is not None]
    unpriced = [line for line in lines if line.unit_price is None]
    if not priced:
        return None, "unavailable"
    total = sum((line.outstanding_value or ZERO for line in priced), ZERO)
    basis = "complete" if not unpriced else "partial"
    return total.quantize(Decimal("0.01")), basis


def assess_open_orders(session: Session) -> list[OrderAssessment]:
    orders = session.scalars(
        select(SalesOrder)
        .where(SalesOrder.status.in_(OPEN_SALES_ORDER_STATUSES))
        .order_by(SalesOrder.promised_date)
    ).all()
    # One allocation for the whole set, so the answers are mutually consistent.
    finished_goods = allocate_finished_goods(session)
    return [
        assess_order(session, order, finished_goods=finished_goods) for order in orders
    ]


# --- Timeline -----------------------------------------------------------------


@dataclass
class TimelineEvent:
    at: dt.datetime
    kind: str
    title: str
    detail: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None


def order_timeline(session: Session, order: SalesOrder) -> list[TimelineEvent]:
    """A single chronological story of what happened to this order."""
    events: list[TimelineEvent] = []
    midnight = dt.time(0, 0, tzinfo=dt.UTC)

    events.append(
        TimelineEvent(
            at=dt.datetime.combine(order.order_date, midnight),
            kind="order",
            title=f"Order {order.number} placed",
            detail=f"{order.customer.name} · promised {order.promised_date.isoformat()}",
            entity_type="sales_order",
            entity_id=order.id,
        )
    )
    if order.confirmed_at:
        events.append(
            TimelineEvent(
                at=order.confirmed_at,
                kind="order",
                title="Order confirmed",
                detail=f"Status moved to {order.status.value}.",
            )
        )

    line_ids = [line.id for line in order.lines]
    batches = list(
        session.scalars(
            select(ProductionBatch).where(ProductionBatch.sales_order_line_id.in_(line_ids))
        ).all()
    )
    for batch in batches:
        for event in sorted(batch.events, key=lambda e: e.occurred_at):
            events.append(
                TimelineEvent(
                    at=event.occurred_at,
                    kind="production",
                    title=f"{batch.code} · {event.event_type.value.replace('_', ' ')}",
                    detail=event.note or f"{batch.stage.value} batch",
                    entity_type="production_batch",
                    entity_id=batch.id,
                )
            )
        for inspection in session.scalars(
            select(QCInspection).where(QCInspection.production_batch_id == batch.id)
        ).all():
            events.append(
                TimelineEvent(
                    at=inspection.inspected_at,
                    kind="quality",
                    title=f"QC {inspection.code} · {inspection.outcome.value}",
                    detail=inspection.notes or f"Inspection of {batch.code}",
                    entity_type="qc_inspection",
                    entity_id=inspection.id,
                )
            )

    for shipment in session.scalars(
        select(Shipment)
        .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.id)
        .where(ShipmentLine.sales_order_line_id.in_(line_ids))
        .distinct()
    ).all():
        if shipment.dispatched_at:
            events.append(
                TimelineEvent(
                    at=shipment.dispatched_at,
                    kind="shipment",
                    title=f"Shipment {shipment.number} dispatched",
                    detail=f"{shipment.carrier or 'Carrier not recorded'} · "
                    f"expected {shipment.expected_delivery_date or 'unknown'}",
                    entity_type="shipment",
                    entity_id=shipment.id,
                )
            )
        if shipment.actual_delivery_date:
            events.append(
                TimelineEvent(
                    at=dt.datetime.combine(shipment.actual_delivery_date, midnight),
                    kind="shipment",
                    title=f"Shipment {shipment.number} delivered",
                    detail="Delivery confirmed.",
                    entity_type="shipment",
                    entity_id=shipment.id,
                )
            )

    return sorted(events, key=lambda e: clock.ensure_utc(e.at))


def delivery_claim_discrepancies(session: Session) -> list[dict[str, object]]:
    """Orders claiming to be delivered that no shipment says arrived.

    An order status is a claim about the physical world. "Delivered" asserts
    that the cloth reached the customer, and the only evidence for that is a
    shipment with a confirmed arrival date. When the two disagree the order
    status wins every screen it appears on — and it fed the on-time percentage
    a delivery that never happened.
    """
    problems: list[dict[str, object]] = []
    delivered_orders = session.scalars(
        select(SalesOrder).where(SalesOrder.status == SalesOrderStatus.DELIVERED)
    ).all()

    for order in delivered_orders:
        carrying = session.scalars(
            select(Shipment)
            .join(ShipmentLine, ShipmentLine.shipment_id == Shipment.id)
            .join(SalesOrderLine, SalesOrderLine.id == ShipmentLine.sales_order_line_id)
            .where(SalesOrderLine.sales_order_id == order.id)
            .distinct()
        ).all()
        live = [s for s in carrying if s.status != ShipmentStatus.CANCELLED]
        unarrived = [s for s in live if s.actual_delivery_date is None]
        if not live:
            problems.append(
                {
                    "sales_order": order.number,
                    "problem": "marked delivered but no shipment carries it",
                }
            )
        elif unarrived:
            problems.append(
                {
                    "sales_order": order.number,
                    "problem": "marked delivered while a shipment has no confirmed arrival",
                    "shipments": [s.number for s in unarrived],
                }
            )
    return problems
