"""Units are business concepts, not decoration. These are the confusions that
cost a textile business money, so each one has a test."""

from __future__ import annotations

from decimal import Decimal

import pytest

from textileops.core.errors import UnitMismatchError, ValidationError
from textileops.core.units import (
    UnitOfMeasure,
    add,
    compare,
    convert,
    fabric_length_m,
    fabric_mass_kg,
    parse_unit,
    parse_yarn_count,
    units_compatible,
)

D = Decimal


def test_metres_and_yards_are_different_numbers():
    assert convert(D("10000"), UnitOfMeasure.YARD, UnitOfMeasure.METRE) == D("9144.000")
    assert convert(D("10000"), UnitOfMeasure.METRE, UnitOfMeasure.YARD) == D("10936.133")


def test_ten_thousand_yards_is_not_ten_thousand_metres():
    yards = convert(D("10000"), UnitOfMeasure.YARD, UnitOfMeasure.METRE)
    assert yards != D("10000")
    assert compare(D("10000"), UnitOfMeasure.METRE, D("10000"), UnitOfMeasure.YARD) == 1


def test_mass_never_becomes_length():
    with pytest.raises(UnitMismatchError):
        convert(D("180"), UnitOfMeasure.KG, UnitOfMeasure.METRE)
    assert not units_compatible(UnitOfMeasure.KG, UnitOfMeasure.METRE)


def test_gsm_is_not_a_unit_of_quantity():
    """180 GSM is an areal density. It must not be parseable as a quantity."""
    with pytest.raises(ValidationError):
        parse_unit("gsm")


def test_yarn_count_is_not_a_mass():
    assert parse_yarn_count("40s") == D("40")
    assert parse_yarn_count("40 Ne") == D("40")
    # A weight is not a count.
    assert parse_yarn_count("40 kg") is None
    assert parse_yarn_count("180 gsm") is None


def test_counting_units_do_not_interconvert():
    """A roll is not a piece; how many metres are on a roll is lot-specific."""
    assert not units_compatible(UnitOfMeasure.ROLL, UnitOfMeasure.PIECE)
    with pytest.raises(UnitMismatchError):
        convert(D("3"), UnitOfMeasure.ROLL, UnitOfMeasure.PIECE)


def test_unknown_unit_raises_rather_than_guessing():
    with pytest.raises(ValidationError):
        parse_unit("boxes-ish")
    with pytest.raises(ValidationError):
        parse_unit(None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kgs", UnitOfMeasure.KG),
        ("Mtrs", UnitOfMeasure.METRE),
        ("yds", UnitOfMeasure.YARD),
        ("PCS", UnitOfMeasure.PIECE),
        ("ltr", UnitOfMeasure.LITRE),
        ("than", UnitOfMeasure.ROLL),
    ],
)
def test_common_trade_spellings_normalise(text, expected):
    assert parse_unit(text) == expected


def test_fabric_mass_uses_gsm_and_width():
    # 1000 m of 180 GSM at 165 cm = 1000 × 1.65 × 180 / 1000 = 297 kg
    assert fabric_mass_kg(D("1000"), D("180"), D("165")) == D("297.000")
    assert fabric_length_m(D("297"), D("180"), D("165")) == D("1000.000")


def test_fabric_mass_requires_positive_gsm_and_width():
    with pytest.raises(ValidationError):
        fabric_mass_kg(D("100"), D("0"), D("165"))


def test_addition_returns_the_first_operand_unit():
    total = add(D("100"), UnitOfMeasure.METRE, D("100"), UnitOfMeasure.YARD)
    assert total == D("191.440")
