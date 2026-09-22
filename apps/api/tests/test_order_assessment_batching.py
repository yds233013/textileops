"""Assessing many orders at once must give the same answers as one at a time.

The order list assessed each order on its own, and each assessment worked out
every material's coverage again: several hundred queries for ten orders, and a
Command Centre that took seconds to fill on a half-CPU host. The list now uses
the batched path. Batching is only acceptable if it changes nothing but speed.
"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import event, select

from textileops.models.enums import OPEN_SALES_ORDER_STATUSES
from textileops.models.sales import SalesOrder
from textileops.seed.demo import seed_demo_business
from textileops.services import orders as order_service


def _count_queries(session, fn):
    count = 0

    def before(*_args, **_kwargs):
        nonlocal count
        count += 1

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return result, count


def test_batched_assessment_matches_one_at_a_time_with_far_fewer_queries(session):
    seed_demo_business(session)
    session.flush()
    orders = list(
        session.scalars(
            select(SalesOrder)
            .where(SalesOrder.status.in_(OPEN_SALES_ORDER_STATUSES))
            .order_by(SalesOrder.promised_date)
        ).all()
    )
    assert len(orders) >= 5

    one_by_one, separate_queries = _count_queries(
        session, lambda: [order_service.assess_order(session, o) for o in orders]
    )
    batched, batched_queries = _count_queries(
        session, lambda: order_service.assess_orders(session, orders)
    )

    diffs = [_diff(asdict(a), asdict(b)) for a, b in zip(batched, one_by_one, strict=True)]
    assert not any(diffs), [d for d in diffs if d]
    assert batched_queries < separate_queries / 2, (batched_queries, separate_queries)


def _diff(a, b):
    out = {}
    for key in a:
        if key == "lines":
            for la, lb in zip(a[key], b[key], strict=True):
                out.update({f"line {la['line_no']} {k}": (la[k], lb[k]) for k in la if la[k] != lb[k]})
        elif a[key] != b[key]:
            out[key] = (a[key], b[key])
    return out
