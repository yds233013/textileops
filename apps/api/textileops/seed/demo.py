"""Seed a realistic textile business, with six operational scenarios.

The point of this data is not volume — it is that the moment you open
TextileOps you can see *why it is useful*. Each scenario is a situation this
business really has, and each one exercises a different part of the engine:

===========  ==========================================================
Scenario A   A supplier delay threatens production (SO-1003 / Meridian).
Scenario B   A QC shade rejection delays a customer order (SO-1002).
Scenario C   One material shortage hits several orders (30s yarn).
Scenario D   A partial PO receipt leaves a shortfall (PO-00005).
Scenario E   A healthy order with nothing wrong (SO-1006).
Scenario F   A late batch that the order's buffer absorbs (SO-1007).
===========  ==========================================================

Everything is dated relative to today, so the demo always looks live.
Seeding refuses to run against a production environment.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.errors import ConflictError
from textileops.core.security import hash_password
from textileops.core.units import UnitOfMeasure
from textileops.ingestion import pipeline
from textileops.models import Base
from textileops.models.catalog import FabricSpec, FabricSpecComponent, Material
from textileops.models.enums import (
    Currency,
    MovementType,
    ProductionStage,
    ProductionStatus,
    PurchaseOrderStatus,
    QCMeasurementKind,
    QCOutcome,
    SalesOrderStatus,
    ShipmentStatus,
    SourceChannel,
)
from textileops.models.inventory import InventoryLot
from textileops.models.org import Customer, Supplier, User
from textileops.models.procurement import PurchaseOrder, PurchaseOrderLine
from textileops.models.production import ProductionBatch
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.seed import catalogue
from textileops.services import (
    clock,
    exception_engine,
    inventory,
    procurement,
    production,
    quality,
    shipments,
)
from textileops.services.quality import MeasurementInput

D = Decimal


def _day(offset: int) -> dt.date:
    return clock.today() + dt.timedelta(days=offset)


def _moment(offset_days: int, hour: int = 10) -> dt.datetime:
    return dt.datetime.combine(
        _day(offset_days), dt.time(hour, 0, tzinfo=dt.UTC)
    )


def seed_demo_business(session: Session, *, reset: bool = False) -> dict[str, Any]:
    if settings.is_production:
        raise ConflictError("Seed data must never be loaded into production.")

    if reset:
        _wipe(session)
    elif session.scalar(select(SalesOrder.id).limit(1)) is not None:
        raise ConflictError(
            "The database already contains orders. Re-run with --reset to replace them."
        )

    users = _seed_users(session)
    customers = _seed_customers(session)
    suppliers = _seed_suppliers(session)
    materials = _seed_materials(session, suppliers)
    specs = _seed_fabric_specs(session, materials)
    session.flush()

    _seed_supplier_history(session, suppliers, materials)
    _seed_opening_stock(session, materials, specs, suppliers)
    orders = _seed_sales_orders(session, customers, specs)
    pos = _seed_purchase_orders(session, suppliers, materials)
    batches = _seed_production(session, orders, specs)
    session.flush()

    _scenario_a_supplier_delay(session, pos, suppliers)
    _scenario_b_qc_rejection(session, batches, users)
    _scenario_d_partial_receipt(session, pos)
    _seed_shipments(session, orders, customers)
    session.flush()

    production.refresh_all_estimates(session)
    session.flush()
    engine = exception_engine.run(session)
    session.flush()

    return {
        "users": len(users),
        "customers": len(customers),
        "suppliers": len(suppliers),
        "materials": len(materials),
        "fabric_specs": len(specs),
        "sales_orders": len(orders),
        "purchase_orders": len(pos),
        "production_batches": len(batches),
        "exceptions": engine.summary(),
        "demo_login": {
            "email": "owner@kaveriknits.example",
            "password": settings.demo_password,
            "note": "Every seeded account uses this password. Development only.",
        },
    }


def _wipe(session: Session) -> None:
    """Truncate every table. Only reachable outside production."""
    table_names = ", ".join(
        f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables)
    )
    session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    session.flush()


# --- Reference data -----------------------------------------------------------


def _seed_users(session: Session) -> dict[str, User]:
    password_hash = hash_password(settings.demo_password)
    users: dict[str, User] = {}
    for email, name, role in catalogue.USERS:
        user = User(
            email=email, full_name=name, role=role, password_hash=password_hash, is_active=True
        )
        session.add(user)
        users[role.value] = user
    session.flush()
    return users


def _seed_customers(session: Session) -> dict[str, Customer]:
    out: dict[str, Customer] = {}
    for code, name, country, contact, email, currency, terms, tier in catalogue.CUSTOMERS:
        customer = Customer(
            code=code,
            name=name,
            country=country,
            contact_name=contact,
            contact_email=email,
            currency=currency,
            payment_terms_days=terms,
            priority_tier=tier,
        )
        session.add(customer)
        out[code] = customer
    session.flush()
    return out


def _seed_suppliers(session: Session) -> dict[str, Supplier]:
    out: dict[str, Supplier] = {}
    for code, name, contact, email, phone, lead in catalogue.SUPPLIERS:
        supplier = Supplier(
            code=code,
            name=name,
            contact_name=contact,
            contact_email=email,
            contact_phone=phone,
            default_lead_time_days=lead,
            # Left unset: it is measured from the delivery history below.
            on_time_rate=None,
        )
        session.add(supplier)
        out[code] = supplier
    session.flush()
    return out


def _seed_materials(session: Session, suppliers: dict[str, Supplier]) -> dict[str, Material]:
    default_supplier = {
        "MAT-YRN-40S": "SUP-001",
        "MAT-YRN-30S": "SUP-001",
        "MAT-YRN-PC20": "SUP-002",
        "MAT-GRG-SJ": "SUP-004",
        "MAT-DYE-RB": "SUP-003",
        "MAT-DYE-BLK": "SUP-003",
        "MAT-CHM-SOFT": "SUP-003",
        "MAT-PKG-POLY": "SUP-005",
        "MAT-PKG-CTN": "SUP-005",
    }
    out: dict[str, Material] = {}
    for (
        code, name, category, unit, composition, yarn_count, colour, shade, cost, reorder
    ) in catalogue.MATERIALS:
        material = Material(
            code=code,
            name=name,
            category=category,
            base_unit=unit,
            composition=composition,
            yarn_count_text=yarn_count,
            yarn_count_ne=D(yarn_count[:-1]) if yarn_count else None,
            colour=colour,
            shade_code=shade,
            standard_cost=cost,
            currency=Currency.INR if cost else None,
            reorder_point=reorder,
            default_supplier_id=suppliers[default_supplier[code]].id,
        )
        session.add(material)
        out[code] = material
    session.flush()
    return out


def _seed_fabric_specs(
    session: Session, materials: dict[str, Material]
) -> dict[str, FabricSpec]:
    out: dict[str, FabricSpec] = {}
    for (
        code, name, composition, construction, gsm, width, colour, shade, finish,
        sale_unit, cost, lead_days,
    ) in catalogue.FABRIC_SPECS:
        spec = FabricSpec(
            code=code,
            name=name,
            composition=composition,
            construction=construction,
            gsm=gsm,
            width_cm=width,
            colour=colour,
            shade_code=shade,
            finish=finish,
            sale_unit=sale_unit,
            standard_cost=cost,
            currency=Currency.INR,
            standard_lead_time_days=lead_days,
        )
        session.add(spec)
        out[code] = spec
    session.flush()

    for fabric_code, material_code, quantity, unit, wastage in catalogue.BOM:
        session.add(
            FabricSpecComponent(
                fabric_spec_id=out[fabric_code].id,
                material_id=materials[material_code].id,
                quantity_per_unit=quantity,
                unit=unit,
                wastage_pct=wastage,
            )
        )
    session.flush()
    return out


# --- Opening stock ------------------------------------------------------------

#: Deliberately tuned so the scenarios are real rather than decorative:
#: 40s yarn covers today's batches but not the Meridian navy run, which is why
#: the supplier delay in scenario A actually bites; 30s yarn is short outright
#: (scenario C); everything else is comfortable.
OPENING_STOCK = [
    # material_code, quantity, unit, days_ago, supplier_code
    ("MAT-YRN-40S", D("2400"), UnitOfMeasure.KG, 26, "SUP-001"),
    ("MAT-YRN-40S", D("1000"), UnitOfMeasure.KG, 12, "SUP-002"),
    ("MAT-YRN-30S", D("900"), UnitOfMeasure.KG, 20, "SUP-001"),
    ("MAT-YRN-PC20", D("2600"), UnitOfMeasure.KG, 18, "SUP-002"),
    ("MAT-GRG-SJ", D("1400"), UnitOfMeasure.KG, 15, "SUP-004"),
    ("MAT-DYE-RB", D("260"), UnitOfMeasure.KG, 30, "SUP-003"),
    ("MAT-DYE-BLK", D("210"), UnitOfMeasure.KG, 22, "SUP-003"),
    ("MAT-CHM-SOFT", D("320"), UnitOfMeasure.LITRE, 19, "SUP-003"),
    ("MAT-PKG-POLY", D("24000"), UnitOfMeasure.PIECE, 40, "SUP-005"),
    ("MAT-PKG-CTN", D("1800"), UnitOfMeasure.PIECE, 40, "SUP-005"),
]

#: Finished fabric already in the warehouse — this is what makes SO-1006 healthy.
OPENING_FABRIC_STOCK = [
    ("FS-SJ180-WHT", D("6200"), UnitOfMeasure.METRE, 9),
    ("FS-RIB240-WHT", D("2400"), UnitOfMeasure.METRE, 7),
]


def _seed_supplier_history(
    session: Session,
    suppliers: dict[str, Supplier],
    materials: dict[str, Material],
) -> None:
    """Completed purchase orders from the past few months.

    Their receipt dates are what give each supplier a *measured* on-time rate.
    Without them the supplier page would be asserting reliability it had never
    observed.
    """
    for index, (
        supplier_code, material_code, quantity, unit, ordered_ago, promised_in, received_ago
    ) in enumerate(catalogue.SUPPLIER_HISTORY, 1):
        po = PurchaseOrder(
            number=f"PO-H{index:04d}",
            supplier_id=suppliers[supplier_code].id,
            order_date=_day(-ordered_ago),
            expected_date=_day(promised_in),
            status=PurchaseOrderStatus.CLOSED,
            currency=Currency.INR,
            sent_at=_moment(-ordered_ago, hour=11),
            closed_at=_moment(-received_ago, hour=17),
            notes="Historical order, closed.",
        )
        session.add(po)
        session.flush()
        line = PurchaseOrderLine(
            purchase_order_id=po.id,
            line_no=1,
            material_id=materials[material_code].id,
            ordered_quantity=quantity,
            unit=unit,
            unit_price=materials[material_code].standard_cost,
            expected_date=_day(promised_in),
        )
        session.add(line)
        session.flush()
        procurement.receive(
            session,
            line,
            accepted_quantity=quantity,
            received_at=_moment(-received_ago, hour=12),
            supplier_document_ref=f"{supplier_code}/DC/{index:04d}",
            note="Historical receipt.",
        )
        # The stock from these historical orders was consumed long ago; opening
        # balances below are the real starting position.
        for lot in session.scalars(
            select(InventoryLot).where(InventoryLot.purchase_order_line_id == line.id)
        ).all():
            inventory.post_movement(
                session,
                lot=lot,
                movement_type=MovementType.ISSUE,
                quantity=lot.quantity_on_hand,
                occurred_at=_moment(-received_ago + 1, hour=9),
                note="Consumed by earlier production.",
            )
    session.flush()


def _seed_opening_stock(
    session: Session,
    materials: dict[str, Material],
    specs: dict[str, FabricSpec],
    suppliers: dict[str, Supplier],
) -> None:
    for index, (code, quantity, unit, days_ago, supplier_code) in enumerate(OPENING_STOCK, 1):
        inventory.create_lot(
            session,
            lot_code=f"LOT-OPEN-{index:03d}",
            material_id=materials[code].id,
            quantity=quantity,
            unit=unit,
            received_at=_moment(-days_ago, hour=9),
            supplier_id=suppliers[supplier_code].id,
            unit_cost=materials[code].standard_cost,
            currency=Currency.INR if materials[code].standard_cost else None,
            notes="Opening balance.",
        )
    for index, (spec_code, quantity, unit, days_ago) in enumerate(OPENING_FABRIC_STOCK, 1):
        inventory.create_lot(
            session,
            lot_code=f"LOT-FG-{index:03d}",
            fabric_spec_id=specs[spec_code].id,
            quantity=quantity,
            unit=unit,
            received_at=_moment(-days_ago, hour=9),
            gsm_actual=specs[spec_code].gsm,
            width_cm_actual=specs[spec_code].width_cm,
            shade_code_actual=specs[spec_code].shade_code,
            notes="Finished stock from an earlier run.",
        )
    session.flush()


# --- Sales orders -------------------------------------------------------------

SALES_ORDERS = [
    # number, customer, ordered_days_ago, promised_in_days, status, priority, ref, lines
    # Already late: promised three days ago, still not shipped.
    (
        "SO-1000", "CUST-001", 41, -3, SalesOrderStatus.IN_PRODUCTION, 1, "MER-2026-0808",
        [("FS-SJ180-NVY", D("3200"), UnitOfMeasure.METRE, D("1.31"))],
    ),
    (
        "SO-1001", "CUST-003", 30, 4, SalesOrderStatus.IN_PRODUCTION, 4, "AG/PO/8841",
        [("FS-SJ180-WHT", D("4000"), UnitOfMeasure.METRE, D("132.00"))],
    ),
    # Scenario B: QC shade rejection hits this one.
    (
        "SO-1002", "CUST-002", 34, 11, SalesOrderStatus.IN_PRODUCTION, 2, "NW-44120",
        [("FS-INT200-RB", D("9000"), UnitOfMeasure.YARD, D("1.92"))],
    ),
    # Scenario A: supplier delay threatens this one.
    (
        "SO-1003", "CUST-001", 24, 16, SalesOrderStatus.IN_PRODUCTION, 1, "MER-2026-0912",
        [
            ("FS-SJ180-NVY", D("7500"), UnitOfMeasure.METRE, D("1.34")),
            ("FS-SJ180-WHT", D("2500"), UnitOfMeasure.METRE, D("1.18")),
        ],
    ),
    # Scenario C: both of these need 30s yarn.
    (
        "SO-1004", "CUST-004", 19, 21, SalesOrderStatus.CONFIRMED, 4, "LFH/2026/331",
        [("FS-PIQ220-BLK", D("2200"), UnitOfMeasure.KG, D("412.00"))],
    ),
    (
        "SO-1005", "CUST-005", 14, 26, SalesOrderStatus.CONFIRMED, 5, "BC-9987",
        [("FS-PIQ220-BLK", D("1500"), UnitOfMeasure.KG, D("405.00"))],
    ),
    # Scenario E: healthy — covered by finished stock.
    (
        "SO-1006", "CUST-003", 11, 18, SalesOrderStatus.CONFIRMED, 5, "AG/PO/8902",
        [("FS-RIB240-WHT", D("1800"), UnitOfMeasure.METRE, D("181.00"))],
    ),
    # Scenario F: batch runs late, order has plenty of buffer.
    (
        "SO-1007", "CUST-004", 9, 32, SalesOrderStatus.CONFIRMED, 6, "LFH/2026/347",
        [("FS-SJ160-PC", D("1900"), UnitOfMeasure.KG, D("231.00"))],
    ),
    # Delivered history, so the on-time percentage has something honest to report.
    (
        "SO-0998", "CUST-003", 62, -21, SalesOrderStatus.DELIVERED, 5, "AG/PO/8790",
        [("FS-SJ180-WHT", D("3000"), UnitOfMeasure.METRE, D("129.00"))],
    ),
    (
        "SO-0999", "CUST-005", 55, -12, SalesOrderStatus.DELIVERED, 5, "BC-9912",
        [("FS-RIB240-WHT", D("1200"), UnitOfMeasure.METRE, D("178.00"))],
    ),
]


def _seed_sales_orders(
    session: Session, customers: dict[str, Customer], specs: dict[str, FabricSpec]
) -> dict[str, SalesOrder]:
    out: dict[str, SalesOrder] = {}
    for number, customer_code, ordered_ago, promised_in, status, priority, ref, lines in (
        SALES_ORDERS
    ):
        customer = customers[customer_code]
        order = SalesOrder(
            number=number,
            customer_id=customer.id,
            order_date=_day(-ordered_ago),
            promised_date=_day(promised_in),
            requested_date=_day(promised_in - 2),
            status=status,
            currency=customer.currency,
            priority=priority,
            customer_reference=ref,
            confirmed_at=_moment(-ordered_ago + 1),
            incoterms="FOB Chennai" if customer.country != "India" else "Ex-works",
        )
        session.add(order)
        session.flush()
        for line_no, (spec_code, quantity, unit, price) in enumerate(lines, 1):
            session.add(
                SalesOrderLine(
                    sales_order_id=order.id,
                    line_no=line_no,
                    fabric_spec_id=specs[spec_code].id,
                    quantity=quantity,
                    unit=unit,
                    unit_price=price,
                    description=specs[spec_code].name,
                )
            )
        out[number] = order
    session.flush()

    # Historic orders are fully shipped and closed out.
    for number in ("SO-0998", "SO-0999"):
        order = out[number]
        for line in order.lines:
            line.shipped_quantity = line.quantity
            line.produced_quantity = line.quantity
        order.closed_at = dt.datetime.combine(
            order.promised_date - dt.timedelta(days=2), dt.time(16, 0, tzinfo=dt.UTC)
        )
    session.flush()
    return out


# --- Purchase orders ----------------------------------------------------------

PURCHASE_ORDERS = [
    # number, supplier, ordered_days_ago, expected_in_days, status, lines
    (
        "PO-00001", "SUP-003", 20, -4, PurchaseOrderStatus.RECEIVED,
        [("MAT-DYE-RB", D("120"), UnitOfMeasure.KG, D("1150.00"))],
    ),
    # Scenario A subject: 40s yarn for the Meridian navy order.
    (
        "PO-00002", "SUP-001", 16, 3, PurchaseOrderStatus.ACKNOWLEDGED,
        [("MAT-YRN-40S", D("2600"), UnitOfMeasure.KG, D("287.50"))],
    ),
    # Scenario C supply: 30s yarn, arriving too late and too little.
    (
        "PO-00003", "SUP-001", 12, 14, PurchaseOrderStatus.ACKNOWLEDGED,
        [("MAT-YRN-30S", D("3000"), UnitOfMeasure.KG, D("244.00"))],
    ),
    (
        "PO-00004", "SUP-005", 9, 6, PurchaseOrderStatus.SENT,
        [
            ("MAT-PKG-POLY", D("30000"), UnitOfMeasure.PIECE, D("1.38")),
            ("MAT-PKG-CTN", D("900"), UnitOfMeasure.PIECE, D("61.00")),
        ],
    ),
    # Scenario D: ordered 10,000 kg, only 6,000 kg arrived, and it is now overdue.
    (
        "PO-00005", "SUP-002", 22, -3, PurchaseOrderStatus.PARTIALLY_RECEIVED,
        [("MAT-YRN-PC20", D("10000"), UnitOfMeasure.KG, D("198.00"))],
    ),
    (
        "PO-00006", "SUP-003", 6, 9, PurchaseOrderStatus.ACKNOWLEDGED,
        [
            ("MAT-DYE-BLK", D("150"), UnitOfMeasure.KG, D("975.00")),
            ("MAT-CHM-SOFT", D("400"), UnitOfMeasure.LITRE, D("208.00")),
        ],
    ),
]


def _seed_purchase_orders(
    session: Session, suppliers: dict[str, Supplier], materials: dict[str, Material]
) -> dict[str, PurchaseOrder]:
    out: dict[str, PurchaseOrder] = {}
    for number, supplier_code, ordered_ago, expected_in, status, lines in PURCHASE_ORDERS:
        po = PurchaseOrder(
            number=number,
            supplier_id=suppliers[supplier_code].id,
            order_date=_day(-ordered_ago),
            expected_date=_day(expected_in),
            status=status,
            currency=Currency.INR,
            supplier_reference=f"{supplier_code}/ACK/{number[-3:]}",
            sent_at=_moment(-ordered_ago, hour=11),
        )
        session.add(po)
        session.flush()
        for line_no, (material_code, quantity, unit, price) in enumerate(lines, 1):
            session.add(
                PurchaseOrderLine(
                    purchase_order_id=po.id,
                    line_no=line_no,
                    material_id=materials[material_code].id,
                    ordered_quantity=quantity,
                    unit=unit,
                    unit_price=price,
                    expected_date=_day(expected_in),
                )
            )
        out[number] = po
    session.flush()

    # PO-00001 was received in full, on time.
    completed = out["PO-00001"]
    procurement.receive(
        session,
        completed.lines[0],
        accepted_quantity=D("120"),
        received_at=_moment(-5, hour=14),
        supplier_document_ref="VDC/DC/4471",
        note="Received in full.",
    )
    session.flush()
    return out


# --- Production ---------------------------------------------------------------

BATCHES = [
    # code, order, line index, spec, quantity, unit, stage, start_offset, days,
    # status, note
    ("B-1024", "SO-1000", 0, "FS-SJ180-NVY", D("3200"), UnitOfMeasure.METRE,
     ProductionStage.FINISHING, -12, 9, ProductionStatus.IN_PROGRESS,
     "Held two days for a shade re-match, then re-queued behind SO-1002."),
    ("B-1031", "SO-1001", 0, "FS-SJ180-WHT", D("4000"), UnitOfMeasure.METRE,
     ProductionStage.DYEING, -6, 8, ProductionStatus.IN_PROGRESS, None),
    # Scenario B: this batch fails QC on shade.
    ("B-1035", "SO-1002", 0, "FS-INT200-RB", D("9000"), UnitOfMeasure.YARD,
     ProductionStage.DYEING, -5, 9, ProductionStatus.IN_PROGRESS, None),
    # Scenario A: needs the 40s yarn that is about to be delayed.
    ("B-1042", "SO-1003", 0, "FS-SJ180-NVY", D("7500"), UnitOfMeasure.METRE,
     ProductionStage.KNITTING, 2, 9, ProductionStatus.SCHEDULED, None),
    ("B-1043", "SO-1003", 1, "FS-SJ180-WHT", D("2500"), UnitOfMeasure.METRE,
     ProductionStage.FINISHING, 5, 5, ProductionStatus.PLANNED, None),
    # Scenario C: both of these compete for the same 30s yarn.
    ("B-1047", "SO-1004", 0, "FS-PIQ220-BLK", D("2200"), UnitOfMeasure.KG,
     ProductionStage.KNITTING, 3, 11, ProductionStatus.PLANNED, None),
    ("B-1048", "SO-1005", 0, "FS-PIQ220-BLK", D("1500"), UnitOfMeasure.KG,
     ProductionStage.KNITTING, 8, 10, ProductionStatus.PLANNED, None),
    # Scenario F: started late, but SO-1007 is promised far enough out to absorb it.
    ("B-1050", "SO-1007", 0, "FS-SJ160-PC", D("1900"), UnitOfMeasure.KG,
     ProductionStage.KNITTING, -4, 10, ProductionStatus.IN_PROGRESS,
     "Started four days behind plan after a machine changeover."),
]


def _seed_production(
    session: Session, orders: dict[str, SalesOrder], specs: dict[str, FabricSpec]
) -> dict[str, ProductionBatch]:
    out: dict[str, ProductionBatch] = {}
    for (
        code, order_number, line_index, spec_code, quantity, unit, stage,
        start_offset, days, status, note,
    ) in BATCHES:
        order = orders[order_number]
        line = sorted(order.lines, key=lambda line_: line_.line_no)[line_index]
        batch = production.create_batch(
            session,
            code=code,
            fabric_spec_id=specs[spec_code].id,
            planned_quantity=quantity,
            unit=unit,
            planned_start=_day(start_offset),
            planned_completion=_day(start_offset + days),
            stage=stage,
            sales_order_line_id=line.id,
            priority=order.priority,
            notes=note,
        )
        if status in (ProductionStatus.SCHEDULED, ProductionStatus.IN_PROGRESS):
            production.schedule_batch(session, batch)
        if status == ProductionStatus.IN_PROGRESS:
            # Scenario F starts late on purpose; the others start on plan.
            actual_start = _moment(start_offset + (4 if code == "B-1050" else 0), hour=8)
            production.start_batch(session, batch, at=actual_start)
        out[code] = batch
    session.flush()
    return out


# --- Scenarios ----------------------------------------------------------------


def _scenario_a_supplier_delay(
    session: Session, pos: dict[str, PurchaseOrder], suppliers: dict[str, Supplier]
) -> None:
    """A: Sri Balaji writes in to say the 40s yarn will be six days late.

    Ingested as a real message through the real pipeline, so the resulting ETA
    change carries provenance back to the sender's own words.
    """
    po = pos["PO-00002"]
    supplier = suppliers["SUP-001"]
    body = (
        "Dear Sir,\n\n"
        f"With reference to {po.number} for 40s combed cotton, the balance 2,600 kg "
        "dispatch will be delayed by 6 days. Our ring frame section had a breakdown "
        "and the spares arrive only next week.\n\n"
        "We are arranging the material on priority and will confirm the vehicle number "
        "once loaded.\n\n"
        "Regards,\n"
        f"{supplier.contact_name}\n{supplier.name}"
    )
    message = pipeline.receive_message(
        session,
        body=body,
        sender=supplier.contact_email or "dispatch@sribalajispinning.example",
        subject=f"Delay in dispatch — {po.number}",
        channel=SourceChannel.EMAIL,
        supplier_id=supplier.id,
        received_at=_moment(-1, hour=17),
    )
    pipeline.process_message(session, message)

    # The same message forwarded again the next morning: it must be recognised as
    # a duplicate and must not move the date a second time.
    duplicate = pipeline.receive_message(
        session,
        body=body,
        sender="ops@kaveriknits.example",
        subject=f"Fwd: Delay in dispatch — {po.number}",
        channel=SourceChannel.EMAIL,
        supplier_id=supplier.id,
        received_at=_moment(0, hour=8),
    )
    pipeline.process_message(session, duplicate)
    session.flush()


def _scenario_b_qc_rejection(
    session: Session, batches: dict[str, ProductionBatch], users: dict[str, User]
) -> None:
    """B: the Northwind interlock fails its shade check and must be re-run."""
    batch = batches["B-1035"]
    produced = D("9000")
    production.record_output(
        session,
        batch,
        good_quantity=produced,
        wastage_quantity=D("180"),
        at=_moment(-1, hour=15),
        lot_code="LOT-B1035-01",
        idempotency_key="seed-output-B-1035",
    )
    inspection = quality.record_inspection(
        session,
        code="QC-2026-0311",
        outcome=QCOutcome.REJECT,
        inspected_quantity=produced,
        accepted_quantity=D("4200"),
        rejected_quantity=D("4800"),
        unit=UnitOfMeasure.YARD,
        production_batch_id=batch.id,
        inspected_at=_moment(-1, hour=16),
        inspector_user_id=users["quality"].id,
        notes=(
            "Rolls 7-18 are off-shade against the buyer's approved swatch — visibly "
            "greyer. Rolls 1-6 are within the band."
        ),
        measurements=[
            MeasurementInput(
                kind=QCMeasurementKind.SHADE,
                observed_text="Off-shade vs approved swatch (greyer, ~1.6 DE)",
                unit_text="visual",
                note="Assessed under D65 in the light box.",
            ),
            MeasurementInput(
                kind=QCMeasurementKind.GSM,
                observed_value=D("198"),
                target_value=D("200"),
                tolerance_low=D("190"),
                tolerance_high=D("210"),
                unit_text="gsm",
            ),
        ],
    )
    quality.propagate(session, inspection, user_id=users["quality"].id)
    session.flush()


def _scenario_d_partial_receipt(session: Session, pos: dict[str, PurchaseOrder]) -> None:
    """D: 6,000 kg of the 10,000 kg poly-cotton yarn arrived, and it is now overdue."""
    line = pos["PO-00005"].lines[0]
    procurement.receive(
        session,
        line,
        accepted_quantity=D("6000"),
        received_at=_moment(-4, hour=11),
        supplier_document_ref="CCT/DC/22187",
        note="Part consignment — supplier confirmed balance would follow.",
    )
    session.flush()


def _seed_shipments(
    session: Session, orders: dict[str, SalesOrder], customers: dict[str, Customer]
) -> None:
    """One delivered on time, one overdue in transit, one packed and waiting."""
    delivered = orders["SO-0998"]
    shipment = shipments.create_shipment(
        session,
        number="SHP-2201",
        customer_id=delivered.customer_id,
        lines=[(delivered.lines[0].id, D("3000"), UnitOfMeasure.METRE)],
        carrier="Sundaram Roadlines",
        expected_delivery_date=_day(-24),
        notes="Delivered without incident.",
    )
    shipment.status = ShipmentStatus.DELIVERED
    shipment.dispatch_date = _day(-28)
    shipment.dispatched_at = _moment(-28, hour=18)
    shipment.actual_delivery_date = _day(-25)
    shipment.tracking_reference = "LR-884201"

    overdue = orders["SO-0999"]
    late_shipment = shipments.create_shipment(
        session,
        number="SHP-2208",
        customer_id=overdue.customer_id,
        lines=[(overdue.lines[0].id, D("1200"), UnitOfMeasure.METRE)],
        carrier="Sundaram Roadlines",
        expected_delivery_date=_day(-5),
        notes="No delivery confirmation received from the transporter.",
    )
    late_shipment.status = ShipmentStatus.IN_TRANSIT
    late_shipment.dispatch_date = _day(-9)
    late_shipment.dispatched_at = _moment(-9, hour=19)
    late_shipment.tracking_reference = "LR-884288"

    ready = orders["SO-1001"]
    shipments.create_shipment(
        session,
        number="SHP-2212",
        customer_id=ready.customer_id,
        lines=[(ready.lines[0].id, D("4000"), UnitOfMeasure.METRE)],
        carrier="Sundaram Roadlines",
        expected_delivery_date=_day(7),
        notes="Packed, awaiting the vehicle.",
    )
    session.flush()
