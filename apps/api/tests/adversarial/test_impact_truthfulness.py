"""The impact engine states figures an operator will act on.

Every defect here is the same shape: a number that is arithmetically right but
labelled in a way that makes it mean something else.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from textileops.services.impact import AffectedOrder, Impact

D = Decimal


def _order(value: str | None, currency: str, number: str) -> AffectedOrder:
    return AffectedOrder(
        sales_order_id=uuid.uuid4(),
        number=number,
        customer_id=uuid.uuid4(),
        customer_name="Meridian Apparel Ltd",
        promised_date=dt.date(2026, 7, 1),
        outstanding_value=D(value) if value is not None else None,
        currency=currency,
    )


def test_the_total_is_labelled_with_the_currency_it_was_actually_added_in():
    """The currency came from the first affected order, not the priced ones.

    An unpriced GBP order sorting first put a "GBP" label on a total composed
    entirely of rupees — a figure wrong by about two orders of magnitude, shown
    with no hint that anything was off.
    """
    impact = Impact(
        headline="Yarn shortage delays two orders",
        affected_orders=[
            _order(None, "GBP", "SO-1001"),  # no prices: contributes nothing
            _order("250000.00", "INR", "SO-1002"),
        ],
    )

    exposure, basis, note, currency = impact.revenue_exposure()

    assert exposure == D("250000.00")
    assert currency == "INR", "a rupee total was presented as pounds sterling"
    assert basis == "partial"
    assert note is not None and "no prices" in note

    assert impact.to_dict()["financial"]["currency"] == "INR"


def test_a_total_that_cannot_be_added_up_is_not_given_a_currency():
    """Mixed currencies produce no figure, so there is nothing to denominate."""
    impact = Impact(
        headline="Shortage spans two markets",
        affected_orders=[
            _order("1000.00", "GBP", "SO-1003"),
            _order("250000.00", "INR", "SO-1004"),
        ],
    )

    exposure, basis, note, currency = impact.revenue_exposure()

    assert exposure is None
    assert basis == "unavailable"
    assert currency is None, (
        "a currency label on a suppressed total invites the reader to assume "
        "a figure exists"
    )
    assert note is not None and "exchange rates" in note
    assert impact.to_dict()["financial"] == {
        "revenue_exposure": None,
        "currency": None,
        "basis": "unavailable",
        "note": note,
    }


def test_no_affected_orders_means_unavailable_not_zero():
    """Zero exposure and unknown exposure are different claims.

    Reporting £0 would tell the operator the problem costs nothing.
    """
    impact = Impact(headline="Nothing downstream")
    exposure, basis, note, currency = impact.revenue_exposure()
    assert exposure is None and basis == "unavailable" and currency is None
    assert note == "No customer orders are affected."
