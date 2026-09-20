"""Property-based tests.

An example-based test proves the case you thought of. These state the rules
that must hold for *every* input, and let Hypothesis go looking for the case
nobody thought of — which is where the arithmetic in an operations system
tends to break: at zero, at the rounding boundary, and at the point where two
units of different magnitudes meet.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from textileops.core.errors import UnitMismatchError
from textileops.core.units import (
    Dimension,
    UnitOfMeasure,
    add,
    compare,
    convert,
    dimension_of,
    quantize,
    units_compatible,
)

D = Decimal

#: Quantities in the range a mill actually deals in, at the precision the
#: ledger stores. Three decimal places, because that is what the column holds.
quantities = st.decimals(
    min_value=D("0"),
    max_value=D("1000000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

convertible_units = st.sampled_from(
    [u for u in UnitOfMeasure if units_compatible(u, u) and u.value not in {"roll", "cone", "bag", "carton"}]
)

SETTINGS = settings(max_examples=250, deadline=None)


def _same_dimension(a: UnitOfMeasure, b: UnitOfMeasure) -> bool:
    return units_compatible(a, b)


@SETTINGS
@given(quantities, convertible_units, convertible_units)
def test_conversion_never_invents_or_destroys_magnitude(value, frm, to):
    """Converting cannot make a quantity cross zero or change sign."""
    assume(_same_dimension(frm, to))
    try:
        result = convert(value, frm, to)
    except UnitMismatchError:
        # Refusing is allowed — silently returning the wrong number is not.
        return
    assert result >= 0
    if value > 0:
        assert result > 0, "a positive quantity converted to nothing"


@SETTINGS
@given(quantities, convertible_units, convertible_units)
def test_conversion_is_order_preserving(value, frm, to):
    """If a > b in one unit, a > b in any compatible unit.

    A conversion that reorders quantities would make "is there enough?" answer
    differently depending on which unit the question was asked in.
    """
    assume(_same_dimension(frm, to))
    bigger = value + D("1.000")
    try:
        low = convert(value, frm, to)
        high = convert(bigger, frm, to)
    except UnitMismatchError:
        return
    assert high >= low


@SETTINGS
@given(quantities, convertible_units, convertible_units)
def test_round_tripping_returns_the_original_or_refuses(value, frm, to):
    """g -> t -> g must give back the gram, or say it cannot."""
    assume(_same_dimension(frm, to))
    try:
        there = convert(value, frm, to)
        back = convert(there, to, frm)
    except UnitMismatchError:
        return
    # The only loss permitted is the ledger's own 0.001 precision.
    assert abs(back - quantize(value)) <= D("0.001")


@SETTINGS
@given(quantities, quantities, convertible_units, convertible_units)
def test_addition_is_commutative_across_units(a, b, a_unit, b_unit):
    assume(_same_dimension(a_unit, b_unit))
    try:
        left = add(a, a_unit, b, b_unit)
        right = convert(add(b, b_unit, a, a_unit), b_unit, a_unit)
    except UnitMismatchError:
        return
    assert abs(left - right) <= D("0.002")


@SETTINGS
@given(quantities, quantities, convertible_units, convertible_units)
def test_comparison_agrees_with_conversion(a, b, a_unit, b_unit):
    assume(_same_dimension(a_unit, b_unit))
    try:
        b_in_a = convert(b, b_unit, a_unit)
        result = compare(a, a_unit, b, b_unit)
    except UnitMismatchError:
        return
    expected = (quantize(a) > b_in_a) - (quantize(a) < b_in_a)
    assert result == expected


@SETTINGS
@given(convertible_units, convertible_units)
def test_units_of_different_dimensions_are_never_compatible(a, b):
    """Mass is never length, whatever the numbers look like."""
    if dimension_of(a) != dimension_of(b):
        assert not units_compatible(a, b)


@SETTINGS
@given(st.sampled_from([u for u in UnitOfMeasure if u.value in {"roll", "cone", "bag", "carton"}]), convertible_units)
def test_a_packaging_unit_converts_only_to_itself(packaged, other):
    """How much is on a roll is lot-specific and is not recorded."""
    assume(packaged != other)
    assert not units_compatible(packaged, other)


@SETTINGS
@given(quantities)
def test_quantising_is_idempotent(value):
    once = quantize(value)
    assert quantize(once) == once
    assert once.as_tuple().exponent == -3


@SETTINGS
@given(quantities, quantities)
def test_quantised_addition_does_not_drift(a, b):
    """Rounding each step must not accumulate away from rounding once."""
    stepwise = quantize(quantize(a) + quantize(b))
    at_once = quantize(a + b)
    assert abs(stepwise - at_once) <= D("0.001")


@SETTINGS
@given(st.sampled_from(list(Dimension)))
def test_every_dimension_has_at_least_one_usable_unit(dimension):
    members = [u for u in UnitOfMeasure if dimension_of(u) == dimension]
    assert members, f"{dimension} has no units"
