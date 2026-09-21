"""How numbers, dates and counts read in sentences a person sees.

Exception titles, summaries and evidence are prose. They used to interpolate
raw values — "1942.500 kg short for 3 batch(es) from 2026-09-20" — which is
exact but reads like a log line, and in a demo reads like a bug. These helpers
render the same values the way an operations manager writes them:
"1,942.5 kg short for 3 batches from 20 Sep".

Only prose. Anything machine-readable (``detection_metrics``, evidence
``data``, API fields) stays ISO and full precision; nothing here rounds a
quantity, it only drops trailing zeros that carry no information.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import Enum

from textileops.services import clock


def num(value: Decimal | int | float | None) -> str:
    """1942.500 → "1,942.5"; 3000.000 → "3,000". Never rounds."""
    if value is None:
        return "—"
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    text = format(decimal.normalize(), ",f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def qty(value: Decimal | int | float | None, unit: Enum | str | None) -> str:
    unit_text = unit.value if isinstance(unit, Enum) else (unit or "")
    return f"{num(value)} {unit_text}".strip()


def when(value: dt.date | dt.datetime | None) -> str:
    """A calendar date as people write it: "20 Sep", or "20 Sep 2025" when the
    year is not the current one. Day before month — unambiguous in India, the
    UK and the US alike, which "09/10" is not."""
    if value is None:
        return "—"
    day = value.date() if isinstance(value, dt.datetime) else value
    text = f"{day.day} {day.strftime('%b')}"
    return text if day.year == clock.today().year else f"{text} {day.year}"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"
