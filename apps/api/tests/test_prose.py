"""Prose formatting: readable, and never lossy."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from textileops.core.units import UnitOfMeasure
from textileops.services import clock, prose


def test_trailing_zeros_go_but_nothing_is_rounded():
    assert prose.num(Decimal("1942.500")) == "1,942.5"
    assert prose.num(Decimal("3000.000")) == "3,000"
    assert prose.num(Decimal("0.001")) == "0.001"
    assert prose.num(Decimal("5377.263")) == "5,377.263"
    assert prose.num(Decimal("0.000")) == "0"


def test_a_quantity_always_carries_its_unit():
    assert prose.qty(Decimal("1942.500"), UnitOfMeasure.KG) == "1,942.5 kg"
    assert prose.qty(Decimal("10000"), "yd") == "10,000 yd"


def test_dates_read_day_first_and_carry_the_year_only_when_it_differs():
    with clock.frozen(dt.datetime(2026, 9, 21, 9, tzinfo=dt.UTC)):
        assert prose.when(dt.date(2026, 9, 20)) == "20 Sep"
        assert prose.when(dt.date(2025, 12, 3)) == "3 Dec 2025"
        assert prose.when(None) == "—"


def test_counts_agree_with_their_nouns():
    assert prose.plural(1, "day") == "1 day"
    assert prose.plural(12, "day") == "12 days"
    assert prose.plural(3, "batch", "batches") == "3 batches"
