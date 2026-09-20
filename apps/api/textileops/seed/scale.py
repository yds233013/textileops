"""Development-only bulk data, for measuring instead of guessing.

Separate from the demo seed on purpose. The demo is a small, hand-built
business where every figure means something and is worth reading; this is
volume, generated to find the queries that stop working at a few hundred
thousand rows. Mixing the two would spoil both.

Deterministic: seeded RNG, so a plan captured today can be compared against
the same data tomorrow. Written with bulk inserts rather than the services —
it is not trying to exercise business logic, and going through the services
would take hours for data that exists only to be queried.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.security import hash_password
from textileops.core.units import UnitOfMeasure
from textileops.models.catalog import FabricSpec, FabricSpecComponent, Material
from textileops.models.enums import (
    Currency,
    EntityType,
    FabricFinish,
    LotStatus,
    MaterialCategory,
    MovementType,
    ProductionStage,
    ProductionStatus,
    PurchaseOrderStatus,
    QCOutcome,
    SalesOrderStatus,
    ShipmentStatus,
    UserRole,
)
from textileops.models.inventory import InventoryLot, InventoryMovement
from textileops.models.logistics import Shipment, ShipmentLine
from textileops.models.org import Customer, Supplier, User
from textileops.models.platform import AuditEvent
from textileops.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
)
from textileops.models.production import ProductionBatch
from textileops.models.quality import QCInspection
from textileops.models.sales import SalesOrder, SalesOrderLine

D = Decimal
ZERO = D("0.000")

#: Fixed so two runs produce the same database and two benchmarks compare.
SEED = 20260920


@dataclass
class ScaleProfile:
    """How much of everything. Defaults are roughly a mid-sized mill's year."""

    customers: int = 120
    suppliers: int = 60
    materials: int = 500
    fabrics: int = 150
    sales_orders: int = 1200
    purchase_orders: int = 900
    production_batches: int = 600
    shipments: int = 700
    lots: int = 2500
    movements_per_lot: int = 4
    audit_events: int = 8000


def _codes(prefix: str, count: int) -> list[str]:
    width = max(4, len(str(count)))
    return [f"{prefix}-{i:0{width}d}" for i in range(1, count + 1)]


def generate(session: Session, profile: ScaleProfile | None = None) -> dict[str, int]:
    """Insert the dataset. Returns a count per table for the record."""
    profile = profile or ScaleProfile()
    rng = random.Random(SEED)
    today = dt.date(2026, 6, 15)
    counts: dict[str, int] = {}

    users = [
        User(
            id=uuid.uuid4(),
            email=f"scale-operator-{i}@example.invalid",
            full_name=f"Scale Operator {i}",
            role=rng.choice(list(UserRole)),
            password_hash=hash_password("scale-only-not-a-real-account"),
        )
        for i in range(10)
    ]
    session.add_all(users)
    session.flush()
    counts["users"] = len(users)

    customers = [
        Customer(
            id=uuid.uuid4(),
            code=code,
            name=f"Customer {code}",
            currency=rng.choice([Currency.INR, Currency.USD, Currency.GBP]),
            priority_tier=rng.randint(1, 5),
        )
        for code in _codes("SC-CUST", profile.customers)
    ]
    suppliers = [
        Supplier(
            id=uuid.uuid4(),
            code=code,
            name=f"Supplier {code}",
            contact_email=f"{code.lower()}@example.invalid",
            default_lead_time_days=rng.randint(7, 45),
        )
        for code in _codes("SC-SUPP", profile.suppliers)
    ]
    session.add_all(customers)
    session.add_all(suppliers)
    session.flush()
    counts["customers"] = len(customers)
    counts["suppliers"] = len(suppliers)

    materials = [
        Material(
            id=uuid.uuid4(),
            code=code,
            name=f"Material {code}",
            category=rng.choice(list(MaterialCategory)),
            base_unit=UnitOfMeasure.KG,
            standard_cost=D(rng.randrange(8000, 45000)) / D("100"),
            currency=Currency.INR,
        )
        for code in _codes("SC-MAT", profile.materials)
    ]
    session.add_all(materials)
    session.flush()
    counts["materials"] = len(materials)

    fabrics = []
    for code in _codes("SC-FAB", profile.fabrics):
        gsm = D(rng.randrange(120, 300))
        width = D(rng.randrange(90, 200))
        fabrics.append(
            FabricSpec(
                id=uuid.uuid4(),
                code=code,
                name=f"Fabric {code}",
                composition="100% Cotton",
                construction="30s / 24G",
                gsm=gsm,
                width_cm=width,
                finish=rng.choice(list(FabricFinish)),
                sale_unit=UnitOfMeasure.METRE,
                standard_cost=D(rng.randrange(9000, 30000)) / D("100"),
                currency=Currency.INR,
                standard_lead_time_days=rng.randint(7, 21),
            )
        )
    session.add_all(fabrics)
    session.flush()
    counts["fabric_specs"] = len(fabrics)

    components = []
    for fabric in fabrics:
        # Real relationship: kg per metre = width_m x gsm / 1000. Kept honest
        # so coverage figures computed over this data are not nonsense.
        per_metre = (fabric.width_cm / D("100")) * fabric.gsm / D("1000")
        for material in rng.sample(materials, k=rng.randint(1, 3)):
            components.append(
                FabricSpecComponent(
                    id=uuid.uuid4(),
                    fabric_spec_id=fabric.id,
                    material_id=material.id,
                    quantity_per_unit=per_metre.quantize(D("0.001")),
                    unit=UnitOfMeasure.KG,
                    wastage_pct=D("0.05"),
                )
            )
    session.add_all(components)
    session.flush()
    counts["fabric_spec_components"] = len(components)

    # --- Sales orders ---------------------------------------------------------
    orders: list[SalesOrder] = []
    order_lines: list[SalesOrderLine] = []
    for index, number in enumerate(_codes("SC-SO", profile.sales_orders)):
        customer = rng.choice(customers)
        ordered_on = today - dt.timedelta(days=rng.randint(1, 300))
        # Never DELIVERED or CLOSED here. Those are claims about the physical
        # world, and they are promoted below only for orders that end up with
        # a shipment carrying a real arrival date — otherwise the generator
        # manufactures exactly the inconsistency the integrity checker exists
        # to find, and a real finding becomes impossible to distinguish from
        # generator noise.
        status = rng.choice(
            [
                SalesOrderStatus.DRAFT,
                SalesOrderStatus.CONFIRMED,
                SalesOrderStatus.IN_PRODUCTION,
                SalesOrderStatus.READY_TO_SHIP,
                SalesOrderStatus.PARTIALLY_SHIPPED,
                SalesOrderStatus.SHIPPED,
                SalesOrderStatus.CANCELLED,
            ]
        )
        order = SalesOrder(
            id=uuid.uuid4(),
            number=number,
            customer_id=customer.id,
            status=status,
            currency=customer.currency,
            order_date=ordered_on,
            promised_date=ordered_on + dt.timedelta(days=rng.randint(15, 90)),
        )
        orders.append(order)
        for line_no in range(1, rng.randint(1, 4) + 1):
            quantity = D(rng.randrange(200, 8000))
            shipped = (
                quantity
                if status == SalesOrderStatus.SHIPPED
                else (quantity / D("2")).quantize(D("0.001"))
                if status == SalesOrderStatus.PARTIALLY_SHIPPED
                else ZERO
            )
            order_lines.append(
                SalesOrderLine(
                    id=uuid.uuid4(),
                    sales_order_id=order.id,
                    line_no=line_no,
                    fabric_spec_id=rng.choice(fabrics).id,
                    quantity=quantity,
                    unit=UnitOfMeasure.METRE,
                    unit_price=D(rng.randrange(9000, 25000)) / D("100"),
                    # Never more than ordered: the constraints are real and the
                    # generator has to respect the same invariants as the app.
                    shipped_quantity=min(shipped, quantity),
                    produced_quantity=min(shipped, quantity),
                    promised_date=order.promised_date,
                )
            )
        if index % 300 == 0:
            session.add_all(orders)
            session.add_all(order_lines)
            session.flush()
            orders, order_lines = [], []
    session.add_all(orders)
    session.add_all(order_lines)
    session.flush()
    counts["sales_orders"] = profile.sales_orders
    all_order_lines = session.query(SalesOrderLine).all()
    counts["sales_order_lines"] = len(all_order_lines)

    # --- Purchase orders ------------------------------------------------------
    pos: list[PurchaseOrder] = []
    po_lines: list[PurchaseOrderLine] = []
    for number in _codes("SC-PO", profile.purchase_orders):
        supplier = rng.choice(suppliers)
        ordered_on = today - dt.timedelta(days=rng.randint(1, 280))
        po = PurchaseOrder(
            id=uuid.uuid4(),
            number=number,
            supplier_id=supplier.id,
            status=rng.choice(
                [
                    PurchaseOrderStatus.SENT,
                    PurchaseOrderStatus.ACKNOWLEDGED,
                    PurchaseOrderStatus.PARTIALLY_RECEIVED,
                    PurchaseOrderStatus.RECEIVED,
                ]
            ),
            currency=Currency.INR,
            order_date=ordered_on,
            expected_date=ordered_on + dt.timedelta(days=supplier.default_lead_time_days),
        )
        pos.append(po)
        for line_no in range(1, rng.randint(1, 3) + 1):
            quantity = D(rng.randrange(100, 5000))
            received = (
                quantity
                if po.status == PurchaseOrderStatus.RECEIVED
                else (quantity / D("3")).quantize(D("0.001"))
                if po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED
                else ZERO
            )
            po_lines.append(
                PurchaseOrderLine(
                    id=uuid.uuid4(),
                    purchase_order_id=po.id,
                    line_no=line_no,
                    material_id=rng.choice(materials).id,
                    ordered_quantity=quantity,
                    unit=UnitOfMeasure.KG,
                    unit_price=D(rng.randrange(8000, 40000)) / D("100"),
                    received_quantity=received,
                    expected_date=po.expected_date,
                )
            )
    session.add_all(pos)
    session.add_all(po_lines)
    session.flush()
    counts["purchase_orders"] = len(pos)
    counts["purchase_order_lines"] = len(po_lines)

    # Receipts matching the received quantities, so the integrity checker has
    # something consistent to verify rather than a contradiction by construction.
    receipts = [
        PurchaseOrderReceipt(
            id=uuid.uuid4(),
            purchase_order_line_id=line.id,
            received_at=dt.datetime.combine(
                line.expected_date or today, dt.time(9, 0, tzinfo=dt.UTC)
            ),
            accepted_quantity=line.received_quantity,
            rejected_quantity=ZERO,
            unit=line.unit,
            unit_price=line.unit_price,
        )
        for line in po_lines
        if line.received_quantity > ZERO
    ]
    session.add_all(receipts)
    session.flush()
    counts["purchase_order_receipts"] = len(receipts)

    # --- Inventory ------------------------------------------------------------
    lots: list[InventoryLot] = []
    movements: list[InventoryMovement] = []
    for index, code in enumerate(_codes("SC-LOT", profile.lots)):
        material = rng.choice(materials)
        received = D(rng.randrange(100, 4000))
        received_at = dt.datetime.combine(
            today - dt.timedelta(days=rng.randint(1, 300)), dt.time(9, 0, tzinfo=dt.UTC)
        )
        lot_id = uuid.uuid4()
        # Build the movements first and derive the balance from them, so the
        # ledger identity holds by construction rather than by luck.
        deltas = [received]
        for _ in range(profile.movements_per_lot - 1):
            drawn = D(rng.randrange(1, max(2, int(sum(deltas)) or 2)))
            if sum(deltas) - drawn < ZERO:
                continue
            deltas.append(-drawn)
        balance = sum(deltas, ZERO).quantize(D("0.001"))
        lots.append(
            InventoryLot(
                id=lot_id,
                lot_code=code,
                material_id=material.id,
                quantity_received=received,
                quantity_on_hand=balance,
                unit=UnitOfMeasure.KG,
                status=LotStatus.AVAILABLE if balance > ZERO else LotStatus.CONSUMED,
                received_at=received_at,
                supplier_id=rng.choice(suppliers).id,
            )
        )
        for position, delta in enumerate(deltas):
            movements.append(
                InventoryMovement(
                    id=uuid.uuid4(),
                    lot_id=lot_id,
                    movement_type=(
                        MovementType.RECEIPT if delta > ZERO else MovementType.ISSUE
                    ),
                    quantity_delta=delta.quantize(D("0.001")),
                    unit=UnitOfMeasure.KG,
                    occurred_at=received_at + dt.timedelta(days=position),
                )
            )
        if index % 500 == 0:
            session.add_all(lots)
            session.add_all(movements)
            session.flush()
            lots, movements = [], []
    session.add_all(lots)
    session.add_all(movements)
    session.flush()
    counts["inventory_lots"] = profile.lots
    counts["inventory_movements"] = profile.lots * profile.movements_per_lot

    # --- Production and QC ----------------------------------------------------
    batches = []
    for code in _codes("SC-PB", profile.production_batches):
        line = rng.choice(all_order_lines)
        start = today - dt.timedelta(days=rng.randint(1, 200))
        planned = D(rng.randrange(200, 5000))
        batch_status = rng.choice(list(ProductionStatus))
        batches.append(
            ProductionBatch(
                id=uuid.uuid4(),
                code=code,
                fabric_spec_id=line.fabric_spec_id,
                sales_order_line_id=line.id,
                status=batch_status,
                # The schema requires a reason when a batch is blocked, and a
                # generator that bypassed that would be producing states the
                # application cannot.
                blocked_reason=(
                    "Awaiting yarn delivery."
                    if batch_status == ProductionStatus.BLOCKED
                    else None
                ),
                stage=rng.choice(list(ProductionStage)),
                planned_quantity=planned,
                output_quantity=(
                    planned if batch_status == ProductionStatus.COMPLETED else ZERO
                ),
                unit=UnitOfMeasure.METRE,
                planned_start=start,
                planned_completion=start + dt.timedelta(days=rng.randint(3, 20)),
            )
        )
    session.add_all(batches)
    session.flush()
    counts["production_batches"] = len(batches)

    inspections = [
        QCInspection(
            id=uuid.uuid4(),
            code=f"SC-QC-{index:05d}",
            production_batch_id=batch.id,
            outcome=rng.choice(list(QCOutcome)),
            inspected_quantity=batch.output_quantity or batch.planned_quantity,
            accepted_quantity=batch.output_quantity or batch.planned_quantity,
            rejected_quantity=ZERO,
            unit=UnitOfMeasure.METRE,
            inspected_at=dt.datetime.combine(
                batch.planned_completion, dt.time(14, 0, tzinfo=dt.UTC)
            ),
        )
        for index, batch in enumerate(batches)
        if batch.status == ProductionStatus.COMPLETED
    ]
    session.add_all(inspections)
    session.flush()
    counts["qc_inspections"] = len(inspections)

    # --- Shipments ------------------------------------------------------------
    shipments_rows: list[Shipment] = []
    shipment_lines: list[ShipmentLine] = []
    shipped_lines = [line for line in all_order_lines if line.shipped_quantity > ZERO]
    for index, number in enumerate(_codes("SC-SHP", profile.shipments)):
        if not shipped_lines:
            break
        line = rng.choice(shipped_lines)
        parent_order = session.get(SalesOrder, line.sales_order_id)
        if parent_order is None:
            continue
        dispatched = today - dt.timedelta(days=rng.randint(1, 120))
        shipment_id = uuid.uuid4()
        shipments_rows.append(
            Shipment(
                id=shipment_id,
                number=number,
                customer_id=parent_order.customer_id,
                status=rng.choice(
                    [ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT,
                     ShipmentStatus.DELIVERED]
                ),
                carrier="Scale Roadlines",
                dispatch_date=dispatched,
                expected_delivery_date=dispatched + dt.timedelta(days=4),
                actual_delivery_date=dispatched + dt.timedelta(days=rng.randint(2, 9)),
            )
        )
        shipment_lines.append(
            ShipmentLine(
                id=uuid.uuid4(),
                shipment_id=shipment_id,
                sales_order_line_id=line.id,
                quantity=line.shipped_quantity,
                unit=line.unit,
            )
        )
        if index % 300 == 0:
            session.add_all(shipments_rows)
            session.add_all(shipment_lines)
            session.flush()
            shipments_rows, shipment_lines = [], []
    session.add_all(shipments_rows)
    session.add_all(shipment_lines)
    session.flush()
    counts["shipments"] = profile.shipments

    # Promote to DELIVERED only the orders whose shipments actually arrived.
    # Done from the data rather than guessed, for the reason above.
    delivered_line_ids = {
        line_id
        for (line_id,) in session.execute(
            select(ShipmentLine.sales_order_line_id)
            .join(Shipment, Shipment.id == ShipmentLine.shipment_id)
            .where(
                Shipment.status == ShipmentStatus.DELIVERED,
                Shipment.actual_delivery_date.is_not(None),
            )
        ).all()
    }
    promoted = 0
    for line in all_order_lines:
        if line.id not in delivered_line_ids:
            continue
        order_row = session.get(SalesOrder, line.sales_order_id)
        if order_row is None or order_row.status != SalesOrderStatus.SHIPPED:
            continue
        # Every line of the order has to be covered, or "delivered" overstates
        # what arrived.
        siblings = [
            other for other in all_order_lines if other.sales_order_id == order_row.id
        ]
        if all(other.id in delivered_line_ids for other in siblings):
            order_row.status = SalesOrderStatus.DELIVERED
            promoted += 1
    session.flush()
    counts["orders_promoted_to_delivered"] = promoted

    # --- Audit volume ---------------------------------------------------------
    events = []
    for index in range(profile.audit_events):
        events.append(
            AuditEvent(
                id=uuid.uuid4(),
                occurred_at=dt.datetime.combine(
                    today - dt.timedelta(days=rng.randint(0, 300)),
                    dt.time(rng.randint(0, 23), rng.randint(0, 59), tzinfo=dt.UTC),
                ),
                actor_type="user",
                actor_user_id=rng.choice(users).id,
                action=rng.choice(
                    [
                        "purchase_order.received",
                        "shipment.dispatched",
                        "production.output_recorded",
                        "exception.resolved",
                        "proposal.approved",
                    ]
                ),
                entity_type=EntityType.PURCHASE_ORDER_LINE,
                entity_id=uuid.uuid4(),
                summary=f"Scale audit event {index}",
            )
        )
        if index % 2000 == 0:
            session.add_all(events)
            session.flush()
            events = []
    session.add_all(events)
    session.flush()
    counts["audit_events"] = profile.audit_events

    return counts
