"""Test fixtures.

Tests run against a real PostgreSQL database, never SQLite: the schema relies
on native enums, JSONB, partial-unique behaviour and ``FOR UPDATE SKIP
LOCKED``, none of which SQLite reproduces. Testing against a different engine
than production would make the test suite a source of false confidence.

Each test runs inside a transaction that is rolled back, so tests are isolated
and the suite stays fast.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AI_PROVIDER", "stub")

from textileops.core.config import settings
from textileops.core.security import hash_password
from textileops.core.units import UnitOfMeasure
from textileops.models import Base
from textileops.models.catalog import FabricSpec, FabricSpecComponent, Material
from textileops.models.enums import (
    Currency,
    FabricFinish,
    MaterialCategory,
    ProductionStage,
    PurchaseOrderStatus,
    SalesOrderStatus,
    UserRole,
)
from textileops.models.org import Customer, Supplier, User
from textileops.models.procurement import PurchaseOrder, PurchaseOrderLine
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import clock, production

D = Decimal

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    settings.database_url.rsplit("/", 1)[0] + "/textileops_test",
)

#: A fixed "today" so date arithmetic in tests is stable regardless of when
#: they run.
FROZEN_NOW = dt.datetime(2026, 6, 15, 9, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    Base.metadata.drop_all(engine)
    # Native enum types survive drop_all; remove them so create_all can rebuild.
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "select t.typname from pg_type t "
                "join pg_namespace n on n.oid = t.typnamespace "
                "where n.nspname = 'public' and t.typtype = 'e'"
            )
        ).all()
        for (name,) in rows:
            connection.execute(text(f'drop type if exists "{name}" cascade'))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[dt.datetime]:
    with clock.frozen(FROZEN_NOW) as now:
        yield now


def day(offset: int) -> dt.date:
    return FROZEN_NOW.date() + dt.timedelta(days=offset)


def moment(offset: int, hour: int = 9) -> dt.datetime:
    return dt.datetime.combine(day(offset), dt.time(hour, 0, tzinfo=dt.UTC))


# --- Small builders -----------------------------------------------------------


@pytest.fixture
def user(session: Session) -> User:
    record = User(
        email=f"tester-{uuid.uuid4().hex[:6]}@example.com",
        full_name="Test Operator",
        role=UserRole.OPERATIONS,
        password_hash=hash_password("password123"),
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def customer(session: Session) -> Customer:
    record = Customer(
        code=f"C-{uuid.uuid4().hex[:6].upper()}",
        name="Meridian Apparel Ltd",
        currency=Currency.GBP,
        priority_tier=2,
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def supplier(session: Session) -> Supplier:
    record = Supplier(
        code=f"S-{uuid.uuid4().hex[:6].upper()}",
        name="Sri Balaji Spinning Mills",
        contact_email="dispatch@sribalaji.example",
        default_lead_time_days=14,
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def yarn(session: Session) -> Material:
    record = Material(
        code=f"M-{uuid.uuid4().hex[:6].upper()}",
        name="40s Combed Cotton Yarn",
        category=MaterialCategory.YARN,
        base_unit=UnitOfMeasure.KG,
        composition="100% Cotton",
        yarn_count_text="40s",
        yarn_count_ne=D("40"),
        standard_cost=D("285.00"),
        currency=Currency.INR,
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def fabric(session: Session, yarn: Material) -> FabricSpec:
    """Single jersey, 180 GSM, 165 cm, sold by the metre.

    Consumption of 0.297 kg/m is the real relationship
    (1.65 m × 180 g/m² ÷ 1000), which keeps the coverage tests honest.
    """
    spec = FabricSpec(
        code=f"F-{uuid.uuid4().hex[:6].upper()}",
        name="Single Jersey 180 GSM White",
        composition="100% Cotton",
        construction="40s / 24G",
        gsm=D("180"),
        width_cm=D("165"),
        finish=FabricFinish.MERCERISED,
        sale_unit=UnitOfMeasure.METRE,
        standard_cost=D("128.00"),
        currency=Currency.INR,
        standard_lead_time_days=10,
    )
    session.add(spec)
    session.flush()
    session.add(
        FabricSpecComponent(
            fabric_spec_id=spec.id,
            material_id=yarn.id,
            quantity_per_unit=D("0.297"),
            unit=UnitOfMeasure.KG,
            wastage_pct=D("0.05"),
        )
    )
    session.flush()
    session.refresh(spec)
    return spec


def make_sales_order(
    session: Session,
    customer: Customer,
    fabric: FabricSpec,
    *,
    number: str | None = None,
    quantity: Decimal = D("5000"),
    promised_in: int = 20,
    unit: UnitOfMeasure | None = None,
    unit_price: Decimal | None = D("1.30"),
    status: SalesOrderStatus = SalesOrderStatus.CONFIRMED,
) -> SalesOrder:
    order = SalesOrder(
        number=number or f"SO-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer.id,
        order_date=day(-10),
        promised_date=day(promised_in),
        status=status,
        currency=customer.currency,
        priority=3,
    )
    session.add(order)
    session.flush()
    session.add(
        SalesOrderLine(
            sales_order_id=order.id,
            line_no=1,
            fabric_spec_id=fabric.id,
            quantity=quantity,
            unit=unit or fabric.sale_unit,
            unit_price=unit_price,
        )
    )
    session.flush()
    session.refresh(order)
    return order


def make_purchase_order(
    session: Session,
    supplier: Supplier,
    material: Material,
    *,
    quantity: Decimal = D("3000"),
    expected_in: int = 5,
    number: str | None = None,
    status: PurchaseOrderStatus = PurchaseOrderStatus.ACKNOWLEDGED,
    unit: UnitOfMeasure | None = None,
    unit_price: Decimal | None = D("285.00"),
) -> PurchaseOrder:
    po = PurchaseOrder(
        number=number or f"PO-{uuid.uuid4().hex[:6].upper()}",
        supplier_id=supplier.id,
        order_date=day(-12),
        expected_date=day(expected_in),
        status=status,
        currency=Currency.INR,
    )
    session.add(po)
    session.flush()
    session.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            line_no=1,
            material_id=material.id,
            ordered_quantity=quantity,
            unit=unit or material.base_unit,
            unit_price=unit_price,
        )
    )
    session.flush()
    session.refresh(po)
    return po


def make_batch(
    session: Session,
    fabric: FabricSpec,
    order: SalesOrder | None = None,
    *,
    code: str | None = None,
    quantity: Decimal = D("5000"),
    start_in: int = 1,
    days: int = 8,
    stage: ProductionStage = ProductionStage.KNITTING,
    reserve_materials: bool = True,
):
    return production.create_batch(
        session,
        code=code or f"B-{uuid.uuid4().hex[:6].upper()}",
        fabric_spec_id=fabric.id,
        planned_quantity=quantity,
        planned_start=day(start_in),
        planned_completion=day(start_in + days),
        stage=stage,
        sales_order_line_id=order.lines[0].id if order else None,
        reserve_materials=reserve_materials,
    )
