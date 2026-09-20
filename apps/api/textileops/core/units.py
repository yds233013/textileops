"""Units of measure as first-class business concepts.

The rules encoded here exist because confusing them is how textile businesses
lose money:

* Quantities only combine or compare within the same **dimension**. Kilograms
  never silently become metres; attempting it raises :class:`UnitMismatchError`.
* **GSM is not a quantity.** It is an areal-density *attribute* of a fabric
  spec, so it is deliberately absent from :class:`UnitOfMeasure`.
* **Yarn count (e.g. "40s") is not a mass.** 40s cotton yarn describes fineness;
  40 kg is a weight. Yarn count lives on the material record as text plus a
  parsed numeric value, never as a quantity.
* Metres and yards are both lengths and *do* convert, but the conversion is
  explicit and lossless-to-3dp; we never assume one when the other was written.

All arithmetic uses :class:`decimal.Decimal`. Floats are not permitted for
quantities anywhere in this codebase.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from textileops.core.errors import UnitMismatchError, ValidationError

QUANTITY_EXP = Decimal("0.001")
MONEY_EXP = Decimal("0.01")


class Dimension(str, Enum):
    MASS = "mass"
    LENGTH = "length"
    COUNT = "count"
    AREA = "area"
    VOLUME = "volume"


class UnitOfMeasure(str, Enum):
    """Units in which a *quantity* of something can be expressed."""

    KG = "kg"
    GRAM = "g"
    TONNE = "t"
    LB = "lb"

    METRE = "m"
    YARD = "yd"
    CM = "cm"
    INCH = "in"

    PIECE = "pcs"
    ROLL = "roll"
    CONE = "cone"
    BAG = "bag"
    CARTON = "carton"

    SQM = "sqm"
    LITRE = "l"


UNIT_DIMENSION: dict[UnitOfMeasure, Dimension] = {
    UnitOfMeasure.KG: Dimension.MASS,
    UnitOfMeasure.GRAM: Dimension.MASS,
    UnitOfMeasure.TONNE: Dimension.MASS,
    UnitOfMeasure.LB: Dimension.MASS,
    UnitOfMeasure.METRE: Dimension.LENGTH,
    UnitOfMeasure.YARD: Dimension.LENGTH,
    UnitOfMeasure.CM: Dimension.LENGTH,
    UnitOfMeasure.INCH: Dimension.LENGTH,
    UnitOfMeasure.PIECE: Dimension.COUNT,
    UnitOfMeasure.ROLL: Dimension.COUNT,
    UnitOfMeasure.CONE: Dimension.COUNT,
    UnitOfMeasure.BAG: Dimension.COUNT,
    UnitOfMeasure.CARTON: Dimension.COUNT,
    UnitOfMeasure.SQM: Dimension.AREA,
    UnitOfMeasure.LITRE: Dimension.VOLUME,
}

# Factor to the canonical unit of each dimension (kg, m, piece, sqm, litre).
_TO_BASE: dict[UnitOfMeasure, Decimal] = {
    UnitOfMeasure.KG: Decimal("1"),
    UnitOfMeasure.GRAM: Decimal("0.001"),
    UnitOfMeasure.TONNE: Decimal("1000"),
    UnitOfMeasure.LB: Decimal("0.45359237"),
    UnitOfMeasure.METRE: Decimal("1"),
    UnitOfMeasure.YARD: Decimal("0.9144"),
    UnitOfMeasure.CM: Decimal("0.01"),
    UnitOfMeasure.INCH: Decimal("0.0254"),
    UnitOfMeasure.PIECE: Decimal("1"),
    UnitOfMeasure.SQM: Decimal("1"),
    UnitOfMeasure.LITRE: Decimal("1"),
}

# Counting units are *not* interchangeable: a roll is not a piece, and how many
# metres are on a roll is lot-specific. They convert only to themselves.
_SELF_ONLY = {UnitOfMeasure.ROLL, UnitOfMeasure.CONE, UnitOfMeasure.BAG, UnitOfMeasure.CARTON}

_ALIASES: dict[str, UnitOfMeasure] = {
    "kg": UnitOfMeasure.KG,
    "kgs": UnitOfMeasure.KG,
    "kilogram": UnitOfMeasure.KG,
    "kilograms": UnitOfMeasure.KG,
    "kilo": UnitOfMeasure.KG,
    "g": UnitOfMeasure.GRAM,
    "gram": UnitOfMeasure.GRAM,
    "grams": UnitOfMeasure.GRAM,
    "gm": UnitOfMeasure.GRAM,
    "t": UnitOfMeasure.TONNE,
    "ton": UnitOfMeasure.TONNE,
    "tonne": UnitOfMeasure.TONNE,
    "mt": UnitOfMeasure.TONNE,
    "lb": UnitOfMeasure.LB,
    "lbs": UnitOfMeasure.LB,
    "pound": UnitOfMeasure.LB,
    "m": UnitOfMeasure.METRE,
    "mtr": UnitOfMeasure.METRE,
    "mtrs": UnitOfMeasure.METRE,
    "mts": UnitOfMeasure.METRE,
    "meter": UnitOfMeasure.METRE,
    "meters": UnitOfMeasure.METRE,
    "metre": UnitOfMeasure.METRE,
    "metres": UnitOfMeasure.METRE,
    "yd": UnitOfMeasure.YARD,
    "yds": UnitOfMeasure.YARD,
    "yard": UnitOfMeasure.YARD,
    "yards": UnitOfMeasure.YARD,
    "cm": UnitOfMeasure.CM,
    "in": UnitOfMeasure.INCH,
    "inch": UnitOfMeasure.INCH,
    "inches": UnitOfMeasure.INCH,
    "pc": UnitOfMeasure.PIECE,
    "pcs": UnitOfMeasure.PIECE,
    "piece": UnitOfMeasure.PIECE,
    "pieces": UnitOfMeasure.PIECE,
    "unit": UnitOfMeasure.PIECE,
    "units": UnitOfMeasure.PIECE,
    "nos": UnitOfMeasure.PIECE,
    "roll": UnitOfMeasure.ROLL,
    "rolls": UnitOfMeasure.ROLL,
    "than": UnitOfMeasure.ROLL,
    "cone": UnitOfMeasure.CONE,
    "cones": UnitOfMeasure.CONE,
    "bag": UnitOfMeasure.BAG,
    "bags": UnitOfMeasure.BAG,
    "carton": UnitOfMeasure.CARTON,
    "cartons": UnitOfMeasure.CARTON,
    "box": UnitOfMeasure.CARTON,
    "sqm": UnitOfMeasure.SQM,
    "sq m": UnitOfMeasure.SQM,
    "m2": UnitOfMeasure.SQM,
    "l": UnitOfMeasure.LITRE,
    "ltr": UnitOfMeasure.LITRE,
    "litre": UnitOfMeasure.LITRE,
    "liter": UnitOfMeasure.LITRE,
    "litres": UnitOfMeasure.LITRE,
}


def parse_unit(raw: str | UnitOfMeasure | None) -> UnitOfMeasure:
    """Normalise a free-text unit. Raises rather than guessing."""
    if isinstance(raw, UnitOfMeasure):
        return raw
    if raw is None:
        raise ValidationError("A unit of measure is required; none was supplied.")
    key = str(raw).strip().lower().rstrip(".")
    if key in _ALIASES:
        return _ALIASES[key]
    try:
        return UnitOfMeasure(key)
    except ValueError:
        raise ValidationError(
            f"Unrecognised unit of measure: {raw!r}. "
            "Units must be explicit — TextileOps will not guess between metres and yards."
        )


def dimension_of(unit: UnitOfMeasure) -> Dimension:
    return UNIT_DIMENSION[unit]


def units_compatible(a: UnitOfMeasure, b: UnitOfMeasure) -> bool:
    if a == b:
        return True
    if a in _SELF_ONLY or b in _SELF_ONLY:
        return False
    return dimension_of(a) == dimension_of(b)


def quantize(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(QUANTITY_EXP, rounding=ROUND_HALF_UP)


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


def convert(value: Decimal, frm: UnitOfMeasure, to: UnitOfMeasure) -> Decimal:
    """Convert a quantity between units of the same dimension."""
    if frm == to:
        return quantize(value)
    if not units_compatible(frm, to):
        raise UnitMismatchError(
            f"Cannot convert {frm.value} to {to.value}: "
            f"{dimension_of(frm).value} and {dimension_of(to).value} are different concepts.",
            details={"from": frm.value, "to": to.value},
        )
    base = Decimal(str(value)) * _TO_BASE[frm]
    return quantize(base / _TO_BASE[to])


def add(a: Decimal, a_unit: UnitOfMeasure, b: Decimal, b_unit: UnitOfMeasure) -> Decimal:
    """Add two quantities, returning the result in ``a_unit``."""
    return quantize(Decimal(str(a)) + convert(Decimal(str(b)), b_unit, a_unit))


def compare(a: Decimal, a_unit: UnitOfMeasure, b: Decimal, b_unit: UnitOfMeasure) -> int:
    """-1 / 0 / 1 comparison of two quantities expressed in compatible units."""
    lhs = quantize(a)
    rhs = convert(Decimal(str(b)), b_unit, a_unit)
    return (lhs > rhs) - (lhs < rhs)


# --- Textile-specific helpers -------------------------------------------------

_YARN_COUNT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:s|'s|ne|nm)?\s*$", re.IGNORECASE)


def parse_yarn_count(raw: str) -> Decimal | None:
    """Parse ``"40s"`` / ``"40 Ne"`` into ``Decimal("40")``.

    Returns ``None`` when the text is not a yarn count. A yarn count is never a
    mass: the caller must not treat the result as kilograms.
    """
    if not raw:
        return None
    match = _YARN_COUNT_RE.match(raw)
    if not match:
        return None
    return Decimal(match.group(1))


def fabric_mass_kg(length_m: Decimal, gsm: Decimal, width_cm: Decimal) -> Decimal:
    """Mass of a length of fabric.

    ``kg = metres × (width_cm / 100) × gsm / 1000``. GSM is grams per square
    metre — an attribute, never a quantity — and is only meaningful alongside a
    width.
    """
    if gsm <= 0 or width_cm <= 0:
        raise ValidationError("GSM and width must be positive to compute fabric mass.")
    area_sqm = Decimal(str(length_m)) * (Decimal(str(width_cm)) / Decimal("100"))
    return quantize(area_sqm * Decimal(str(gsm)) / Decimal("1000"))


def fabric_length_m(mass_kg: Decimal, gsm: Decimal, width_cm: Decimal) -> Decimal:
    """Inverse of :func:`fabric_mass_kg`."""
    if gsm <= 0 or width_cm <= 0:
        raise ValidationError("GSM and width must be positive to compute fabric length.")
    grams = Decimal(str(mass_kg)) * Decimal("1000")
    width_m = Decimal(str(width_cm)) / Decimal("100")
    return quantize(grams / (Decimal(str(gsm)) * width_m))


def format_quantity(value: Decimal, unit: UnitOfMeasure) -> str:
    return f"{quantize(value):,.3f} {unit.value}".replace(".000 ", " ")
