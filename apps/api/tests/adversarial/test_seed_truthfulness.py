"""The demo business, audited against independently calculated values.

The seed is what anyone evaluating TextileOps looks at first, so a wrong
figure here is not a cosmetic problem: it is a demonstration that the system
is confidently reporting something false. Nothing in this file reads an
expected value out of the application — each one is recomputed from textile
first principles and compared.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from textileops.core.units import UnitOfMeasure, convert
from textileops.seed.catalogue import BOM, FABRIC_SPECS

D = Decimal

#: Index of the seeded fabric specs by code: (gsm, width_cm, sale_unit).
SPECS = {
    row[0]: {"gsm": row[4], "width_cm": row[5], "sale_unit": row[9]}
    for row in FABRIC_SPECS
}

#: Yarn materials only. Dye and chemical dosages are recipe figures, not
#: geometry, so they are checked separately.
YARN_BOM = [row for row in BOM if row[1].startswith("MAT-YRN")]


def _expected_yarn_per_sale_unit(code: str) -> Decimal | None:
    """kg of yarn in one sale unit of cloth, from GSM and width alone.

    Cloth sold by length has a calculable yarn content: a square metre of
    180 GSM cloth weighs 180 g, and a metre of it 165 cm wide is 1.65 m² —
    so 0.297 kg. This is the relationship the mill actually works to, and it
    is what makes a shortage figure believable.

    Cloth sold by weight has no such relationship: 1 kg of cloth needs rather
    more than 1 kg of yarn because of process loss, and that factor is a
    property of the machine, not the geometry. Those return ``None``.
    """
    spec = SPECS[code]
    if spec["sale_unit"] == UnitOfMeasure.KG:
        return None
    kg_per_metre = (spec["width_cm"] / D("100")) * spec["gsm"] / D("1000")
    if spec["sale_unit"] == UnitOfMeasure.METRE:
        return kg_per_metre
    if spec["sale_unit"] == UnitOfMeasure.YARD:
        # A yard is 0.9144 m. Treating one as the other is a 9% error in every
        # coverage figure for this customer.
        return kg_per_metre * D("0.9144")
    raise AssertionError(f"unhandled sale unit {spec['sale_unit']}")


@pytest.mark.parametrize(
    ("fabric_code", "material_code", "quantity", "unit", "wastage"),
    YARN_BOM,
    ids=[f"{row[0]}-{row[1]}" for row in YARN_BOM],
)
def test_yarn_consumption_matches_gsm_times_width(
    fabric_code, material_code, quantity, unit, wastage
):
    expected = _expected_yarn_per_sale_unit(fabric_code)
    if expected is None:
        # Sold by weight: assert the only thing that is knowable, which is that
        # making a kilogram of cloth cannot take less than a kilogram of yarn.
        assert quantity >= D("1"), (
            f"{fabric_code} claims to make 1 kg of cloth from {quantity} kg of yarn, "
            "which would be making cotton out of nothing"
        )
        assert quantity < D("1.3"), f"{fabric_code} implies implausible process loss"
        return

    assert unit == UnitOfMeasure.KG
    difference = abs(quantity - expected)
    assert difference <= D("0.002"), (
        f"{fabric_code} consumes {quantity} kg per "
        f"{SPECS[fabric_code]['sale_unit'].value}, but "
        f"{SPECS[fabric_code]['gsm']} GSM at "
        f"{SPECS[fabric_code]['width_cm']} cm works out at {expected}"
    )


def test_a_fabric_sold_in_yards_is_not_costed_as_if_it_were_metres():
    """The single most expensive unit mistake available in this domain.

    FS-INT200-RB is ordered in yards. If its consumption had been derived per
    metre, every coverage calculation for that customer would be 9.4% short.
    """
    yard_fabrics = [c for c, s in SPECS.items() if s["sale_unit"] == UnitOfMeasure.YARD]
    assert yard_fabrics, "the demo must exercise a non-metre sale unit"

    for code in yard_fabrics:
        bom = next(row for row in YARN_BOM if row[0] == code)
        per_metre = (SPECS[code]["width_cm"] / D("100")) * SPECS[code]["gsm"] / D("1000")
        assert bom[2] < per_metre, (
            f"{code} is sold by the yard but consumes a full metre's worth of yarn"
        )
        assert abs(bom[2] - per_metre * D("0.9144")) <= D("0.002")


@pytest.mark.parametrize("row", BOM, ids=[f"{r[0]}-{r[1]}" for r in BOM])
def test_no_bom_line_is_zero_negative_or_wastage_free_nonsense(row):
    _, _, quantity, unit, wastage = row
    assert quantity > 0, "a component consumed in zero quantity is not a component"
    assert D("0") <= wastage < D("0.5"), (
        f"a wastage allowance of {wastage} is not a real mill figure"
    )
    assert isinstance(quantity, Decimal) and isinstance(wastage, Decimal)
    # The unit must be one the converter actually understands.
    assert convert(D("1"), unit, unit) == D("1.000")


def test_every_bom_line_points_at_a_fabric_that_exists():
    codes = set(SPECS)
    for row in BOM:
        assert row[0] in codes, f"BOM references unknown fabric {row[0]}"


def test_every_fabric_can_actually_be_made():
    """A spec with no bill of materials silently produces cloth out of nothing."""
    with_bom = {row[0] for row in BOM}
    missing = sorted(set(SPECS) - with_bom)
    assert missing == [], f"these fabrics have no materials: {missing}"


def test_every_fabric_consumes_yarn():
    """Dye without yarn would make a shortage calculation structurally blind."""
    with_yarn = {row[0] for row in YARN_BOM}
    missing = sorted(set(SPECS) - with_yarn)
    assert missing == [], f"these fabrics consume no yarn at all: {missing}"


def test_gsm_and_width_are_plausible_for_knitted_fabric():
    """Guards against a decimal-point slip in the demo data itself."""
    for code, spec in SPECS.items():
        assert D("80") <= spec["gsm"] <= D("400"), f"{code}: {spec['gsm']} GSM"
        assert D("80") <= spec["width_cm"] <= D("220"), f"{code}: {spec['width_cm']} cm"
