"""Concurrency tests that use real, simultaneous PostgreSQL sessions.

The rest of the suite runs each test inside one transaction that is rolled
back. That is the right trade for speed and isolation, but it can never
observe a lost update: a single session cannot race itself. Every defect in
this file was found by running two connections at once and was invisible to
sequential tests.

The pattern throughout is a deliberate interleave rather than a hopeful sleep:
the first writer takes its lock and only then lets the second writer start, so
the contention is guaranteed to happen on every run instead of occasionally.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from textileops.core.errors import ConflictError
from textileops.core.security import hash_password
from textileops.core.units import UnitOfMeasure, quantize
from textileops.models import Base
from textileops.models.actions import Approval, Execution
from textileops.models.catalog import Material
from textileops.models.enums import (
    ActionType,
    Currency,
    FabricFinish,
    MaterialCategory,
    MovementType,
    ProposalOrigin,
    ProposalStatus,
    PurchaseOrderStatus,
    SalesOrderStatus,
    UserRole,
)
from textileops.models.inventory import InventoryLot, InventoryMovement
from textileops.models.logistics import Shipment
from textileops.models.org import Customer, Supplier, User
from textileops.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
)
from textileops.models.sales import SalesOrder, SalesOrderLine
from textileops.services import actions, inventory, procurement, shipments

D = Decimal
ZERO = D("0.000")

#: How long a blocked statement may wait before we call the test hung. The
#: second writer is *expected* to block on a row lock; it is not expected to
#: block forever.
LOCK_TIMEOUT = 20


@pytest.fixture
def sessions(engine):
    """Independent sessions that really commit, plus a truncate on the way out.

    These tests cannot use the rolled-back ``session`` fixture: two connections
    have to see each other's committed rows, which is exactly what a shared
    outer transaction prevents.
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    opened: list[Session] = []

    def _open() -> Session:
        db = factory()
        db.execute(text(f"set local lock_timeout = '{LOCK_TIMEOUT}s'"))
        opened.append(db)
        return db

    try:
        yield _open
    finally:
        # Close every session this test opened before truncating. A session
        # left holding even a read lock will deadlock against TRUNCATE's
        # AccessExclusiveLock, and the failure surfaces in whichever test runs
        # next rather than in the one that caused it.
        for db in opened:
            try:
                db.rollback()
            finally:
                db.close()
        # Closing the sessions is not enough. A session whose thread died
        # mid-transaction can leave its connection in the pool still holding
        # row locks, and TRUNCATE needs an AccessExclusiveLock — so the two
        # deadlock, and the failure surfaces in whichever test runs next
        # rather than in the one that caused it. Disposing the pool ends
        # those transactions outright.
        engine.dispose()
        tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        with engine.begin() as connection:
            # Bounded, so a stray lock fails this teardown loudly instead of
            # hanging the whole run.
            connection.execute(text("set local lock_timeout = '30s'"))
            connection.execute(text(f"truncate table {tables} restart identity cascade"))


def _interleave(first, second) -> list[BaseException | None]:
    """Run ``first`` and ``second`` so that they genuinely overlap.

    ``first`` signals once it holds whatever lock it is going to hold; only
    then is ``second`` released, and ``first`` does not commit until ``second``
    has announced that it is about to contend. Without that handshake the two
    threads usually run one after the other and the test proves nothing.
    """
    first_has_lock = threading.Event()
    second_is_trying = threading.Event()
    results: list[BaseException | None] = [None, None]

    def run_first() -> None:
        try:
            first(first_has_lock, second_is_trying)
        except BaseException as exc:  # reported back to the test thread
            results[0] = exc
            first_has_lock.set()

    def run_second() -> None:
        try:
            second(first_has_lock, second_is_trying)
        except BaseException as exc:  # reported back to the test thread
            results[1] = exc

    threads = [threading.Thread(target=run_first), threading.Thread(target=run_second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=LOCK_TIMEOUT + 15)
        assert not thread.is_alive(), "a writer never finished — suspected deadlock"
    return results


# --- Fixture data (committed, so both connections can see it) -----------------


def _material(db: Session) -> Material:
    record = Material(
        code=f"M-{uuid.uuid4().hex[:6].upper()}",
        name="40s Combed Cotton Yarn",
        category=MaterialCategory.YARN,
        base_unit=UnitOfMeasure.KG,
        standard_cost=D("285.00"),
        currency=Currency.INR,
    )
    db.add(record)
    db.flush()
    return record


def _supplier(db: Session) -> Supplier:
    record = Supplier(
        code=f"S-{uuid.uuid4().hex[:6].upper()}",
        name="Kumaran Spinning Mills",
        contact_email="dispatch@kumaran.example",
        default_lead_time_days=21,
    )
    db.add(record)
    db.flush()
    return record


def _fabric_and_customer(db: Session):
    from textileops.models.catalog import FabricSpec

    customer = Customer(
        code=f"C-{uuid.uuid4().hex[:6].upper()}",
        name="Meridian Apparel Ltd",
        currency=Currency.INR,
        priority_tier=2,
    )
    fabric = FabricSpec(
        code=f"FS-{uuid.uuid4().hex[:6].upper()}",
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
    db.add_all([customer, fabric])
    db.flush()
    return fabric, customer


def _user(db: Session) -> User:
    record = User(
        email=f"op-{uuid.uuid4().hex[:6]}@example.com",
        full_name="Test Operator",
        role=UserRole.OPERATIONS,
        password_hash=hash_password("password123"),
    )
    db.add(record)
    db.flush()
    return record


# --- 1. Lost update on a lot balance ------------------------------------------


def test_two_issues_from_one_lot_cannot_both_succeed(sessions):
    """The demonstrated defect: 120 kg issued out of a 100 kg lot.

    Both sessions read ``on_hand = 100``, both concluded that issuing 60 was
    legal, and both stored the absolute result 40. The per-row CHECK could not
    fire — 40 is a perfectly legal balance — and the stored figure drifted
    away from the movement ledger by a full 60 kg, which is the number that
    then drove every coverage and shortage calculation in the product.
    """
    setup = sessions()
    material = _material(setup)
    lot = inventory.create_lot(
        setup,
        lot_code=f"LOT-{uuid.uuid4().hex[:8].upper()}",
        unit=UnitOfMeasure.KG,
        quantity=D("100.000"),
        material_id=material.id,
    )
    setup.commit()
    lot_id = lot.id

    def issue(db: Session) -> None:
        held = db.get(InventoryLot, lot_id)
        assert held is not None
        inventory.post_movement(
            db,
            lot=held,
            movement_type=MovementType.ISSUE,
            quantity=D("60.000"),
        )

    def first(has_lock, other_trying):
        db = sessions()
        issue(db)
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        other_trying.set()
        issue(db)  # blocks on the row lock until the first writer commits
        db.commit()

    errors = _interleave(first, second)

    assert errors[0] is None, f"the first issue should have succeeded: {errors[0]!r}"
    assert isinstance(errors[1], ConflictError), (
        "the second issue drew 60 kg from a lot holding 40 and was allowed to: "
        f"{errors[1]!r}"
    )

    check = sessions()
    stored = check.get(InventoryLot, lot_id)
    assert stored is not None
    ledger = check.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
            InventoryMovement.lot_id == lot_id
        )
    )
    assert stored.quantity_on_hand == D("40.000")
    assert ledger == stored.quantity_on_hand, (
        "the stored balance and the movement ledger disagree — stock was issued "
        "that the ledger never recorded"
    )


def test_a_replayed_movement_is_a_no_op_even_when_the_replay_is_simultaneous(sessions):
    """At-least-once delivery means the same key really does arrive twice at once.

    The old check-then-insert was a TOCTOU: the loser reached the unique index
    and got an IntegrityError, so a worker whose stock movement *had* been
    applied recorded its job as failed, retried, and could end up DEAD.
    """
    setup = sessions()
    material = _material(setup)
    lot = inventory.create_lot(
        setup,
        lot_code=f"LOT-{uuid.uuid4().hex[:8].upper()}",
        unit=UnitOfMeasure.KG,
        quantity=D("100.000"),
        material_id=material.id,
    )
    setup.commit()
    lot_id = lot.id
    key = f"issue-{uuid.uuid4().hex}"
    posted: list[bool] = []

    def issue(db: Session) -> None:
        held = db.get(InventoryLot, lot_id)
        assert held is not None
        movement = inventory.post_movement(
            db,
            lot=held,
            movement_type=MovementType.ISSUE,
            quantity=D("10.000"),
            idempotency_key=key,
        )
        posted.append(movement is not None)

    def first(has_lock, other_trying):
        db = sessions()
        issue(db)
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        other_trying.set()
        issue(db)
        db.commit()

    errors = _interleave(first, second)
    assert errors == [None, None], f"a replay raised instead of no-opping: {errors!r}"
    assert sorted(posted) == [False, True], "exactly one of the two should have posted"

    check = sessions()
    movements = check.scalar(
        select(func.count(InventoryMovement.id)).where(
            InventoryMovement.idempotency_key == key
        )
    )
    lot_now = check.get(InventoryLot, lot_id)
    assert lot_now is not None
    assert movements == 1
    assert lot_now.quantity_on_hand == D("90.000"), "the replay double-counted"


# --- 2. Two receipts against one purchase order line --------------------------


def test_two_deliveries_keyed_in_at_once_are_both_recorded(sessions):
    """Two demonstrated failures, one fix.

    Both sessions computed the same ``LOT-PO-…-1`` code, so one delivery died
    on the unique index and 500 kg of yarn sat in the warehouse with no lot,
    no movement and no receipt. When the codes happened not to collide, both
    wrote ``received_quantity = 500`` instead of 1000 — leaving 500 kg of
    phantom inbound supply on the material forever and a PO line that could
    never reach RECEIVED.
    """
    setup = sessions()
    material = _material(setup)
    supplier = _supplier(setup)
    order = PurchaseOrder(
        number=f"PO-{uuid.uuid4().hex[:6].upper()}",
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.ACKNOWLEDGED,
        currency=Currency.INR,
        order_date=dt.date(2026, 6, 1),
        expected_date=dt.date(2026, 6, 20),
    )
    setup.add(order)
    setup.flush()
    line = PurchaseOrderLine(
        purchase_order_id=order.id,
        line_no=1,
        material_id=material.id,
        ordered_quantity=D("1000.000"),
        unit=UnitOfMeasure.KG,
        unit_price=D("285.00"),
    )
    setup.add(line)
    setup.commit()
    line_id = line.id

    def first(has_lock, other_trying):
        db = sessions()
        held = db.get(PurchaseOrderLine, line_id)
        assert held is not None
        procurement.receive(db, held, accepted_quantity=D("500.000"))
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        # Load the line into this session BEFORE announcing, so the stale
        # "nothing received yet" snapshot is pinned while the first writer is
        # still uncommitted. Announcing first would let the first writer commit
        # and this one read the fresh figure, and the race would quietly not
        # happen.
        held = db.get(PurchaseOrderLine, line_id)
        assert held is not None
        assert held.received_quantity == ZERO
        other_trying.set()
        procurement.receive(db, held, accepted_quantity=D("500.000"))
        db.commit()

    errors = _interleave(first, second)
    assert errors == [None, None], f"a delivery was lost: {errors!r}"

    check = sessions()
    stored = check.get(PurchaseOrderLine, line_id)
    assert stored is not None
    lots = check.scalars(
        select(InventoryLot).where(InventoryLot.purchase_order_line_id == line_id)
    ).all()
    assert stored.received_quantity == D("1000.000"), (
        "the line lost a delivery — outstanding supply is now permanently wrong"
    )
    assert stored.outstanding_quantity == ZERO
    assert len({lot.lot_code for lot in lots}) == 2, "two deliveries, two lots"
    assert sum((lot.quantity_on_hand for lot in lots), ZERO) == D("1000.000")
    refreshed_order = check.get(PurchaseOrder, order.id)
    assert refreshed_order is not None
    assert refreshed_order.status == PurchaseOrderStatus.RECEIVED


# --- 3. Two approvals of one proposal -----------------------------------------


def test_one_proposal_cannot_be_approved_twice(sessions):
    """An approval is a claim about who authorised something.

    Concurrently, two operators each got an Approval row against the same
    proposal — so the record said two managers had each authorised the action —
    and the loser's write reset the status to APPROVED after the winner had set
    EXECUTED, presenting completed work back to the queue as still pending.
    """
    setup = sessions()
    supplier = _supplier(setup)
    material = _material(setup)
    alice = _user(setup)
    bob = _user(setup)
    proposal = actions.create_proposal(
        setup,
        action_type=ActionType.RAISE_PURCHASE_ORDER,
        title="Cover the shortfall on 40s cotton",
        rationale="Coverage runs out before the promised date.",
        payload={
            "supplier_id": str(supplier.id),
            "material_id": str(material.id),
            "quantity": "500.000",
            "unit": "kg",
            "needed_by": "2026-07-15",
        },
        origin=ProposalOrigin.RULE_ENGINE,
    )
    setup.commit()
    proposal_id = proposal.id
    alice_id, bob_id = alice.id, bob.id

    def approve(db: Session, user_id: uuid.UUID) -> None:
        held = db.get(actions.ActionProposal, proposal_id)
        assert held is not None
        actions.approve(db, held, user_id=user_id)

    def first(has_lock, other_trying):
        db = sessions()
        approve(db, alice_id)
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        other_trying.set()
        approve(db, bob_id)
        db.commit()

    errors = _interleave(first, second)
    assert errors[0] is None, f"the first approval should stand: {errors[0]!r}"
    assert isinstance(errors[1], ConflictError), (
        f"the same proposal was approved twice: {errors[1]!r}"
    )

    check = sessions()
    approvals = check.scalars(
        select(Approval).where(Approval.action_proposal_id == proposal_id)
    ).all()
    executions = check.scalars(
        select(Execution).where(Execution.action_proposal_id == proposal_id)
    ).all()
    stored = check.get(actions.ActionProposal, proposal_id)
    assert stored is not None
    assert len(approvals) == 1, "the audit trail must name exactly one approver"
    assert approvals[0].decided_by_user_id == alice_id
    assert len(executions) == 1, "the action ran twice"
    assert stored.status == ProposalStatus.EXECUTED, (
        "the proposal was reported back to the queue as still awaiting execution"
    )
    orders_raised = check.scalar(
        select(func.count(PurchaseOrder.id)).where(PurchaseOrder.supplier_id == supplier.id)
    )
    assert orders_raised == 1, "a duplicate purchase order was raised at the supplier"


# --- 4. Two corrections against one receipt -----------------------------------


def test_two_corrections_against_one_receipt_cannot_both_take_the_same_stock(sessions):
    """1,000 kg received; two operators each correct it down by 600.

    Without the line lock both read "nothing corrected yet", both conclude
    600 is within the 1,000 recorded, and between them they take 1,200 kg out
    of a 1,000 kg delivery — the receipt equivalent of issuing stock twice.
    """
    setup = sessions()
    material = _material(setup)
    supplier = _supplier(setup)
    user = _user(setup)
    order = PurchaseOrder(
        number=f"PO-{uuid.uuid4().hex[:6].upper()}",
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.ACKNOWLEDGED,
        currency=Currency.INR,
        order_date=dt.date(2026, 6, 1),
        expected_date=dt.date(2026, 6, 20),
    )
    setup.add(order)
    setup.flush()
    line = PurchaseOrderLine(
        purchase_order_id=order.id,
        line_no=1,
        material_id=material.id,
        ordered_quantity=D("1000.000"),
        unit=UnitOfMeasure.KG,
        unit_price=D("285.00"),
    )
    setup.add(line)
    setup.flush()
    receipt = procurement.receive(
        setup, line, accepted_quantity=D("1000.000"), user_id=user.id
    ).receipt
    setup.commit()
    line_id, receipt_id, user_id = line.id, receipt.id, user.id

    def first(has_lock, other_trying):
        db = sessions()
        held = db.get(PurchaseOrderReceipt, receipt_id)
        procurement.correct_receipt(
            db, held, accepted_delta=D("600"), reason="Recount A.", user_id=user_id
        )
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        held = db.get(PurchaseOrderReceipt, receipt_id)
        assert held.corrections == [], "precondition: stale view of the receipt"
        other_trying.set()
        procurement.correct_receipt(
            db, held, accepted_delta=D("600"), reason="Recount B.", user_id=user_id
        )
        db.commit()

    errors = _interleave(first, second)
    assert errors[0] is None, f"the first correction should stand: {errors[0]!r}"
    assert isinstance(errors[1], ConflictError), (
        f"1,200 kg was corrected out of a 1,000 kg delivery: {errors[1]!r}"
    )

    check = sessions()
    stored_line = check.get(PurchaseOrderLine, line_id)
    stored_receipt = check.get(PurchaseOrderReceipt, receipt_id)
    assert stored_line.received_quantity == D("400.000")
    assert len(stored_receipt.corrections) == 1
    lots = check.scalars(
        select(InventoryLot).where(InventoryLot.purchase_order_line_id == line_id)
    ).all()
    assert sum((lot.quantity_on_hand for lot in lots), ZERO) == D("400.000")
    for lot in lots:
        ledger = check.scalar(
            select(func.coalesce(func.sum(InventoryMovement.quantity_delta), ZERO)).where(
                InventoryMovement.lot_id == lot.id
            )
        )
        assert ledger == lot.quantity_on_hand


def test_a_correction_racing_a_delivery_on_one_line_does_not_deadlock(sessions):
    """Both take the PO line first, then the lot, so they queue rather than cycle."""
    setup = sessions()
    material = _material(setup)
    supplier = _supplier(setup)
    user = _user(setup)
    order = PurchaseOrder(
        number=f"PO-{uuid.uuid4().hex[:6].upper()}",
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.ACKNOWLEDGED,
        currency=Currency.INR,
        order_date=dt.date(2026, 6, 1),
        expected_date=dt.date(2026, 6, 20),
    )
    setup.add(order)
    setup.flush()
    line = PurchaseOrderLine(
        purchase_order_id=order.id,
        line_no=1,
        material_id=material.id,
        ordered_quantity=D("2000.000"),
        unit=UnitOfMeasure.KG,
        unit_price=D("285.00"),
    )
    setup.add(line)
    setup.flush()
    receipt = procurement.receive(
        setup, line, accepted_quantity=D("1000.000"), user_id=user.id
    ).receipt
    setup.commit()
    line_id, receipt_id, user_id = line.id, receipt.id, user.id

    def correcting(has_lock, other_trying):
        db = sessions()
        held = db.get(PurchaseOrderReceipt, receipt_id)
        procurement.correct_receipt(
            db, held, accepted_delta=D("100"), reason="Recount.", user_id=user_id
        )
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def delivering(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        other_trying.set()
        held_line = db.get(PurchaseOrderLine, line_id)
        procurement.receive(db, held_line, accepted_quantity=D("500.000"), user_id=user_id)
        db.commit()

    errors = _interleave(correcting, delivering)
    assert errors == [None, None], f"a deadlock or lost update: {errors!r}"

    check = sessions()
    stored = check.get(PurchaseOrderLine, line_id)
    assert stored.received_quantity == D("1400.000"), (
        "1,000 received, 100 corrected away, 500 more delivered"
    )


def test_two_rejected_only_corrections_cannot_both_take_the_same_quantity(sessions):
    """The case only the PO-line lock can catch.

    A correction that touches accepted stock is caught twice over, because
    ``post_movement`` locks the lot as well. A correction against the
    *rejected* figure moves no stock and touches no lot — so if the line lock
    were removed, nothing else would stop two operators each writing off the
    same 300 kg of rejected goods and driving the figure negative.
    """
    setup = sessions()
    material = _material(setup)
    supplier = _supplier(setup)
    user = _user(setup)
    order = PurchaseOrder(
        number=f"PO-{uuid.uuid4().hex[:6].upper()}",
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.ACKNOWLEDGED,
        currency=Currency.INR,
        order_date=dt.date(2026, 6, 1),
        expected_date=dt.date(2026, 6, 20),
    )
    setup.add(order)
    setup.flush()
    line = PurchaseOrderLine(
        purchase_order_id=order.id,
        line_no=1,
        material_id=material.id,
        ordered_quantity=D("1000.000"),
        unit=UnitOfMeasure.KG,
        unit_price=D("285.00"),
    )
    setup.add(line)
    setup.flush()
    receipt = procurement.receive(
        setup,
        line,
        accepted_quantity=ZERO,
        rejected_quantity=D("500.000"),
        user_id=user.id,
    ).receipt
    setup.commit()
    assert receipt.inventory_lot_id is None, "precondition: no lot, so no lot lock"
    line_id, receipt_id, user_id = line.id, receipt.id, user.id

    def first(has_lock, other_trying):
        db = sessions()
        held = db.get(PurchaseOrderReceipt, receipt_id)
        procurement.correct_receipt(
            db, held, rejected_delta=D("300"), reason="Recount A.", user_id=user_id
        )
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        held = db.get(PurchaseOrderReceipt, receipt_id)
        assert held.corrections == [], "precondition: stale view of the receipt"
        other_trying.set()
        procurement.correct_receipt(
            db, held, rejected_delta=D("300"), reason="Recount B.", user_id=user_id
        )
        db.commit()

    errors = _interleave(first, second)
    assert errors[0] is None, f"the first correction should stand: {errors[0]!r}"
    assert isinstance(errors[1], ConflictError), (
        f"600 kg was written off a 500 kg rejection: {errors[1]!r}"
    )

    check = sessions()
    stored_line = check.get(PurchaseOrderLine, line_id)
    stored_receipt = check.get(PurchaseOrderReceipt, receipt_id)
    assert stored_line.rejected_quantity == D("200.000")
    assert stored_receipt.corrected_rejected_quantity == D("200.000")
    assert len(stored_receipt.corrections) == 1


# --- 5. Two dispatches against one order line ---------------------------------


def test_two_dispatches_cannot_between_them_over_ship_one_line(sessions):
    """Two lorries loaded at once against a 1,000 m order, 600 m each.

    Both plans were legitimate when made. Both read "600 shipped so far, 400
    to go" — and between them they send 1,200 m against a 1,000 m order. The
    customer is invoiced twice for cloth that only exists once.
    """
    setup = sessions()
    fabric, customer = _fabric_and_customer(setup)
    lot = inventory.create_lot(
        setup,
        lot_code=f"LOT-FG-{uuid.uuid4().hex[:8].upper()}",
        unit=UnitOfMeasure.METRE,
        quantity=D("5000.000"),
        fabric_spec_id=fabric.id,
    )
    order = SalesOrder(
        number=f"SO-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer.id,
        status=SalesOrderStatus.CONFIRMED,
        currency=Currency.INR,
        order_date=dt.date(2026, 6, 1),
        promised_date=dt.date(2026, 7, 1),
    )
    setup.add(order)
    setup.flush()
    line = SalesOrderLine(
        sales_order_id=order.id,
        line_no=1,
        fabric_spec_id=fabric.id,
        quantity=D("1000.000"),
        unit=UnitOfMeasure.METRE,
        unit_price=D("129.00"),
    )
    setup.add(line)
    setup.flush()

    first_shipment = shipments.create_shipment(
        setup,
        number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer.id,
        lines=[(line.id, D("600.000"), UnitOfMeasure.METRE)],
    )
    second_shipment = shipments.create_shipment(
        setup,
        number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
        customer_id=customer.id,
        lines=[(line.id, D("400.000"), UnitOfMeasure.METRE)],
    )
    setup.commit()
    line_id = line.id
    first_id, second_id = first_shipment.id, second_shipment.id
    assert lot is not None

    def dispatch_first(has_lock, other_trying):
        db = sessions()
        held = db.get(Shipment, first_id)
        shipments.dispatch(db, held)
        has_lock.set()
        other_trying.wait(timeout=LOCK_TIMEOUT)
        db.commit()

    def dispatch_second(has_lock, other_trying):
        db = sessions()
        has_lock.wait(timeout=LOCK_TIMEOUT)
        held_line = db.get(SalesOrderLine, line_id)
        assert held_line.shipped_quantity == ZERO, "precondition: stale view"
        other_trying.set()
        held = db.get(Shipment, second_id)
        shipments.dispatch(db, held)
        db.commit()

    errors = _interleave(dispatch_first, dispatch_second)
    assert errors == [None, None], f"a dispatch failed unexpectedly: {errors!r}"

    check = sessions()
    stored = check.get(SalesOrderLine, line_id)
    assert stored.shipped_quantity <= stored.quantity, (
        f"{stored.shipped_quantity} shipped against an order for {stored.quantity}"
    )
    assert stored.shipped_quantity == D("1000.000")


def test_two_dispatches_of_the_same_cloth_do_not_deadlock(sessions):
    """Two orders drawing the same finished-goods lots, dispatched at once.

    Both take lot locks in receipt-then-id order, so they queue. Without a
    fixed order they could each hold what the other needs.
    """
    setup = sessions()
    fabric, customer = _fabric_and_customer(setup)
    for index in range(3):
        inventory.create_lot(
            setup,
            lot_code=f"LOT-FG-{uuid.uuid4().hex[:8].upper()}",
            unit=UnitOfMeasure.METRE,
            quantity=D("400.000"),
            fabric_spec_id=fabric.id,
            received_at=dt.datetime(2026, 6, 1 + index, tzinfo=dt.UTC),
        )
    orders = []
    for _ in range(2):
        order = SalesOrder(
            number=f"SO-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            status=SalesOrderStatus.CONFIRMED,
            currency=Currency.INR,
            order_date=dt.date(2026, 6, 1),
            promised_date=dt.date(2026, 7, 1),
        )
        setup.add(order)
        setup.flush()
        line = SalesOrderLine(
            sales_order_id=order.id,
            line_no=1,
            fabric_spec_id=fabric.id,
            quantity=D("500.000"),
            unit=UnitOfMeasure.METRE,
            unit_price=D("129.00"),
        )
        setup.add(line)
        setup.flush()
        shipment = shipments.create_shipment(
            setup,
            number=f"SHP-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            lines=[(line.id, D("500.000"), UnitOfMeasure.METRE)],
        )
        orders.append((line.id, shipment.id))
    setup.commit()

    def go(index):
        def run(has_lock, other_trying):
            db = sessions()
            if index == 0:
                held = db.get(Shipment, orders[0][1])
                shipments.dispatch(db, held)
                has_lock.set()
                other_trying.wait(timeout=LOCK_TIMEOUT)
            else:
                has_lock.wait(timeout=LOCK_TIMEOUT)
                other_trying.set()
                held = db.get(Shipment, orders[1][1])
                shipments.dispatch(db, held)
            db.commit()

        return run

    errors = _interleave(go(0), go(1))
    assert all(
        not isinstance(e, Exception) or "deadlock" not in str(e).lower()
        for e in errors
    ), f"deadlock: {errors!r}"

    check = sessions()
    total = ZERO
    for line_id, _ in orders:
        stored = check.get(SalesOrderLine, line_id)
        assert stored.shipped_quantity <= stored.quantity
        total += stored.shipped_quantity
    physical = check.scalar(
        select(func.coalesce(func.sum(InventoryLot.quantity_on_hand), ZERO)).where(
            InventoryLot.fabric_spec_id == fabric.id
        )
    )
    assert quantize(total + physical) == D("1200.000"), (
        "cloth shipped plus cloth remaining must equal what was made"
    )
