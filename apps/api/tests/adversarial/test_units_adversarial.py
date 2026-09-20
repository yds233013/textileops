"""Unit handling, attacked.

Units are where a textile system quietly loses money: the same yarn is bought
in tonnes, stocked in kilograms, consumed in grams per metre and sold by the
metre, and every one of those boundaries is a chance to drop a factor of a
thousand.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from textileops.core.errors import UnitMismatchError, ValidationError
from textileops.core.units import (
    UnitOfMeasure,
    add,
    compare,
    convert,
    parse_unit,
    parse_yarn_count,
)

D = Decimal


def test_a_quantity_too_small_for_the_target_unit_is_refused_not_rounded_away():
    """One gram in tonnes is 0.000001, and the ledger stores three decimals.

    Quantising returned 0.000 — so a real receipt of yarn could be recorded as
    nothing at all, with no movement, no error and no way to notice. Refusing
    is the only honest answer: the unit cannot carry the quantity.
    """
    with pytest.raises(UnitMismatchError) as exc:
        convert(D("1"), UnitOfMeasure.GRAM, UnitOfMeasure.TONNE)

    assert "losing 1.000 g" in str(exc.value), "the refusal must name what is lost"
    assert exc.value.details["value"] == "1"
    assert exc.value.details["lost"] == "1.000"


def test_a_quantity_that_would_be_rounded_UP_is_refused_too():
    """The case a hand-written test missed and a property test found.

    Half a kilogram in tonnes is 0.0005, which rounds *up* to 0.001 t at the
    stored precision — and reading that back gives a full kilogram. The stock
    had not changed; the unit it was written in doubled it. Guarding only
    against rounding down to zero left this wide open.
    """
    with pytest.raises(UnitMismatchError) as exc:
        convert(D("0.5"), UnitOfMeasure.KG, UnitOfMeasure.TONNE)
    assert exc.value.details["exact"].startswith("0.0005")
    assert exc.value.details["storable"] == "0.001"


def test_a_conversion_that_loses_real_quantity_is_refused():
    """29.703 kg in tonnes stores as 0.030 t, which reads back as 30 kg.

    297 grams of yarn disappear, with no movement to account for them.
    """
    with pytest.raises(UnitMismatchError) as exc:
        convert(D("29.703"), UnitOfMeasure.KG, UnitOfMeasure.TONNE)
    assert exc.value.details["lost"] == "0.297"


def test_a_conversion_whose_loss_is_below_the_source_precision_is_allowed():
    """A pound into kilograms loses less than the source could have recorded."""
    assert convert(D("1"), UnitOfMeasure.LB, UnitOfMeasure.KG) == D("0.454")
    assert convert(D("1"), UnitOfMeasure.YARD, UnitOfMeasure.METRE) == D("0.914")


def test_zero_still_converts_to_zero():
    """Nothing is a legitimate quantity; only losing *something* is the bug."""
    assert convert(D("0"), UnitOfMeasure.GRAM, UnitOfMeasure.TONNE) == D("0.000")


def test_a_quantity_the_target_unit_can_carry_still_converts():
    assert convert(D("1000"), UnitOfMeasure.GRAM, UnitOfMeasure.KG) == D("1.000")
    assert convert(D("2.5"), UnitOfMeasure.TONNE, UnitOfMeasure.KG) == D("2500.000")


def test_round_tripping_a_quantity_does_not_lose_it():
    """g -> kg -> g used to come back as 0 for anything under half a gram."""
    for grams in ("1", "5", "500", "1250"):
        kg = convert(D(grams), UnitOfMeasure.GRAM, UnitOfMeasure.KG)
        assert convert(kg, UnitOfMeasure.KG, UnitOfMeasure.GRAM) == D(grams).quantize(
            D("0.001")
        )


def test_a_roll_is_not_a_piece_and_the_refusal_says_why():
    """The old message was "count and count are different concepts".

    Both are counts, so that reads as a bug in the checker rather than a fact
    about rolls. The real reason is that how much is on a roll is lot-specific.
    """
    with pytest.raises(UnitMismatchError) as exc:
        convert(D("3"), UnitOfMeasure.ROLL, UnitOfMeasure.PIECE)

    message = str(exc.value)
    assert "count and count" not in message
    assert "specific to the lot" in message


def test_mass_and_length_stay_different_concepts():
    with pytest.raises(UnitMismatchError) as exc:
        convert(D("100"), UnitOfMeasure.KG, UnitOfMeasure.METRE)
    assert "different concepts" in str(exc.value)


def test_adding_across_units_uses_the_left_hand_unit():
    assert add(D("1"), UnitOfMeasure.KG, D("500"), UnitOfMeasure.GRAM) == D("1.500")


def test_comparison_is_by_magnitude_not_by_number():
    # 900 g is less than 1 kg however much larger the number looks.
    assert compare(D("1"), UnitOfMeasure.KG, D("900"), UnitOfMeasure.GRAM) == 1
    assert compare(D("1"), UnitOfMeasure.KG, D("1000"), UnitOfMeasure.GRAM) == 0


def test_gsm_is_not_a_unit_of_quantity():
    """GSM is a property of cloth, not an amount of it.

    Accepting "gsm" as a quantity unit is how 180 GSM becomes 180 of something.
    """
    with pytest.raises(ValidationError):
        parse_unit("gsm")


def test_a_yarn_count_is_never_a_mass():
    """40s is a fineness. Treating it as 40 kg is a factor nobody would catch."""
    assert parse_yarn_count("40s") == D("40")
    assert parse_yarn_count("40 Ne") == D("40")
    assert parse_yarn_count("kg") is None
    with pytest.raises(ValidationError):
        parse_unit("40s")
