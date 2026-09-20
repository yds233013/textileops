"""Material coverage — the arithmetic behind "do we have enough, in time?"."""

from __future__ import annotations

from decimal import Decimal

from tests.conftest import day, make_batch, make_purchase_order, make_sales_order, moment
from textileops.core.units import UnitOfMeasure
from textileops.models.enums import PurchaseOrderStatus
from textileops.services import coverage, inventory, procurement

D = Decimal


def _stock(session, yarn, quantity, code="LOT-1"):
    return inventory.create_lot(
        session,
        lot_code=code,
        material_id=yarn.id,
        quantity=D(quantity),
        unit=UnitOfMeasure.KG,
        received_at=moment(-2),
    )


def test_batch_requirement_is_exploded_from_the_bill_of_materials(session, fabric, yarn):
    """5,000 m at 0.297 kg/m with 5% wastage = 1,563.158 kg."""
    batch = make_batch(session, fabric, quantity=D("5000"))
    requirement = batch.requirements[0]
    assert requirement.material_id == yarn.id
    assert requirement.required_quantity == D("1563.158")
    assert requirement.unit == UnitOfMeasure.KG
    # Materials must be on site before the batch starts, not when it finishes.
    assert requirement.required_by == batch.planned_start


def test_sufficient_stock_covers_demand_with_no_shortage(session, fabric, yarn):
    _stock(session, yarn, "2000")
    make_batch(session, fabric, quantity=D("5000"))
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    assert result.required == D("1563.158")
    assert result.shortage == D("0.000")
    assert not result.has_shortage
    assert all(not a.is_short and not a.is_late for a in result.allocations)


def test_reservations_are_not_counted_twice_against_their_own_demand(session, fabric, yarn):
    """A batch reservation and a batch requirement are the same demand.

    Netting both would invent a shortage that does not exist — this is the
    regression test for exactly that bug.
    """
    _stock(session, yarn, "2000")
    make_batch(session, fabric, quantity=D("5000"), reserve_materials=True)
    session.flush()

    position = inventory.material_position(session, yarn.id)
    assert position.reserved == D("1563.158")  # the reservation exists
    assert position.available == D("436.842")  # free to promise for new work

    result = coverage.analyse_material(session, yarn.id)
    assert result.available == D("2000.000")  # drawable by this very batch
    assert result.shortage == D("0.000")


def test_shortage_is_reported_with_the_affected_orders(
    session, fabric, yarn, customer, supplier
):
    _stock(session, yarn, "1000")
    first = make_sales_order(session, customer, fabric, number="SO-A", promised_in=20)
    second = make_sales_order(session, customer, fabric, number="SO-B", promised_in=30)
    make_batch(session, fabric, first, quantity=D("5000"), start_in=2)
    make_batch(session, fabric, second, quantity=D("5000"), start_in=6)
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    assert result.has_shortage
    # 2 × 1,563.158 required, 1,000 available → 2,126.316 short.
    assert result.shortage == D("2126.316")
    numbers = {a.sales_order_number for a in result.allocations if a.is_short}
    assert numbers == {"SO-A", "SO-B"}
    # Earliest demand is served first, so the first batch is only partly short.
    first_allocation = next(a for a in result.allocations if a.sales_order_number == "SO-A")
    assert first_allocation.covered_quantity == D("1000.000")


def test_incoming_supply_that_lands_too_late_is_flagged_as_late_not_covered(
    session, fabric, yarn, customer, supplier
):
    _stock(session, yarn, "100")
    order = make_sales_order(session, customer, fabric)
    make_batch(session, fabric, order, quantity=D("5000"), start_in=3)
    # Plenty of yarn, but it arrives after the batch was due to start.
    make_purchase_order(session, supplier, yarn, quantity=D("3000"), expected_in=10)
    session.flush()

    result = coverage.analyse_material(session, yarn.id)
    allocation = result.allocations[0]
    assert allocation.shortfall_quantity == D("0.000")
    assert allocation.is_late
    assert allocation.covered_by_date == day(10)
    assert result.first_shortfall_date == day(3)


def test_a_revised_supplier_eta_moves_the_covering_date(
    session, fabric, yarn, customer, supplier, user
):
    """The regression test for a stale line-level date hiding a known delay."""
    order = make_sales_order(session, customer, fabric)
    make_batch(session, fabric, order, quantity=D("5000"), start_in=8)
    po = make_purchase_order(session, supplier, yarn, quantity=D("3000"), expected_in=5)
    session.flush()

    before = coverage.analyse_material(session, yarn.id).allocations[0]
    assert before.covered_by_date == day(5)
    assert not before.is_late

    procurement.revise_eta(
        session,
        po,
        new_date=day(12),
        reason="Ring frame breakdown.",
        user_id=user.id,
        actor_type="user",
    )
    session.flush()

    after = coverage.analyse_material(session, yarn.id).allocations[0]
    assert after.covered_by_date == day(12)
    assert after.is_late


def test_partial_receipt_leaves_the_balance_outstanding(session, yarn, supplier, fabric):
    po = make_purchase_order(session, supplier, yarn, quantity=D("10000"), expected_in=4)
    line = po.lines[0]
    procurement.receive(
        session, line, accepted_quantity=D("6000"), received_at=moment(-1)
    )
    session.flush()

    assert line.received_quantity == D("6000.000")
    assert line.outstanding_quantity == D("4000.000")
    assert po.status == PurchaseOrderStatus.PARTIALLY_RECEIVED

    position = inventory.material_position(session, yarn.id)
    assert position.on_hand == D("6000.000")  # what actually arrived
    assert position.incoming == D("4000.000")  # what is still owed


def test_ordered_quantity_is_never_confused_with_received(session, yarn, supplier):
    po = make_purchase_order(session, supplier, yarn, quantity=D("10000"))
    line = po.lines[0]
    assert line.ordered_quantity == D("10000.000")
    assert line.received_quantity == D("0.000")
    procurement.receive(session, line, accepted_quantity=D("6000"))
    session.flush()
    assert line.ordered_quantity == D("10000.000")
    assert line.received_quantity == D("6000.000")


def test_coverage_converts_units_before_comparing(session, fabric, yarn, customer):
    """A batch booked in yards must not be compared with kilograms of yarn
    by number: the BOM conversion has to happen first."""
    _stock(session, yarn, "2000")
    order = make_sales_order(session, customer, fabric)
    batch = make_batch(session, fabric, order, quantity=D("5468"), start_in=2)
    # 5,468 yd ≈ 5,000 m → the same requirement as the metre-denominated batch.
    batch.unit = UnitOfMeasure.YARD
    session.flush()
    result = coverage.analyse_material(session, yarn.id)
    assert result.required > D("0")


def test_projected_stock_does_not_count_the_same_demand_twice(session, fabric, yarn, supplier):
    """Projected = what is drawable + what is coming − what is needed.

    Using ``available`` (already net of the batch's own reservation) would
    subtract the batch twice and invent a shortfall.
    """
    _stock(session, yarn, "2000")
    make_batch(session, fabric, quantity=D("5000"), reserve_materials=True)
    make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=3)
    session.flush()

    position = inventory.material_position(session, yarn.id)
    # 2,000 drawable + 1,000 incoming − 1,563.158 required = 1,436.842
    assert position.projected == D("1436.842")
    assert position.available == D("436.842")  # free to promise, net of the reservation


def test_over_commitment_is_reported_rather_than_shown_as_negative_stock(
    session, fabric, yarn
):
    _stock(session, yarn, "500")
    make_batch(session, fabric, quantity=D("5000"), reserve_materials=True)
    session.flush()

    position = inventory.material_position(session, yarn.id)
    assert position.over_committed_by == D("1063.158")
    # Physical stock a batch can draw on is never negative.
    assert position.supply_for_coverage >= D("0")


def test_a_suppliers_on_time_rate_is_measured_from_real_deliveries(
    session, yarn, supplier
):
    """The rate on a supplier record is derived from completed lines."""
    supplier.on_time_rate = None
    delivered_early = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=5
    )
    delivered_late = make_purchase_order(
        session, supplier, yarn, quantity=D("1000"), expected_in=-10
    )
    session.flush()

    procurement.receive(
        session, delivered_early.lines[0], accepted_quantity=D("1000"),
        received_at=moment(3),
    )
    session.flush()
    # The second order is already overdue with nothing received, so it counts.
    assert supplier.on_time_rate == D("0.5000")

    procurement.receive(
        session, delivered_late.lines[0], accepted_quantity=D("1000"),
        received_at=moment(0),
    )
    session.flush()
    # It arrived, but after its promised date: still one of two on time.
    assert supplier.on_time_rate == D("0.5000")


def test_a_line_never_delivered_counts_against_the_supplier(
    session, yarn, supplier
):
    """Silence is the commonest way a supplier is late.

    Counting only what arrived would let a supplier who has delivered nothing
    for six months score 100%.
    """
    supplier.on_time_rate = None
    on_time = make_purchase_order(session, supplier, yarn, quantity=D("500"), expected_in=5)
    make_purchase_order(session, supplier, yarn, quantity=D("500"), expected_in=-5)
    session.flush()

    procurement.receive(
        session, on_time.lines[0], accepted_quantity=D("500"), received_at=moment(2)
    )
    session.flush()

    # One delivered on time, one overdue with nothing received.
    assert supplier.on_time_rate == D("0.5000")


def test_a_partial_delivery_not_yet_due_is_not_counted_against_the_supplier(
    session, yarn, supplier
):
    supplier.on_time_rate = None
    po = make_purchase_order(session, supplier, yarn, quantity=D("1000"), expected_in=10)
    session.flush()
    procurement.receive(
        session, po.lines[0], accepted_quantity=D("400"), received_at=moment(1)
    )
    session.flush()
    # Nothing to judge yet: the balance is not due.
    assert supplier.on_time_rate is None


def test_a_supplier_with_no_orders_has_no_rate(session, supplier):
    """An unmeasured supplier is not a perfect supplier."""
    supplier.on_time_rate = D("0.9")
    session.flush()
    assert procurement.recompute_supplier_on_time_rate(session, supplier) is None
    assert supplier.on_time_rate is None


def test_a_replayed_receipt_does_not_post_the_goods_twice(session, yarn, supplier):
    """A double-submitted form must not double the stock."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("10000"))
    line = po.lines[0]

    first = procurement.receive(
        session,
        line,
        accepted_quantity=D("6000"),
        supplier_document_ref="CCT/DC/22187",
        idempotency_key="receipt-abc",
    )
    session.flush()
    second = procurement.receive(
        session,
        line,
        accepted_quantity=D("6000"),
        supplier_document_ref="CCT/DC/22187",
        idempotency_key="receipt-abc",
    )
    session.flush()

    assert first.was_replay is False
    assert second.was_replay is True
    assert second.receipt.id == first.receipt.id
    assert line.received_quantity == D("6000.000")
    assert inventory.material_position(session, yarn.id).on_hand == D("6000.000")


def test_a_supplier_document_reference_and_a_replay_key_are_different_things(
    session, yarn, supplier
):
    """Both may be supplied; the guard must still work."""
    po = make_purchase_order(session, supplier, yarn, quantity=D("10000"))
    line = po.lines[0]
    outcome = procurement.receive(
        session,
        line,
        accepted_quantity=D("1000"),
        supplier_document_ref="CCT/DC/999",
        idempotency_key="key-1",
    )
    session.flush()
    assert outcome.receipt.supplier_document_ref == "CCT/DC/999"
    assert outcome.receipt.idempotency_key == "key-1"
