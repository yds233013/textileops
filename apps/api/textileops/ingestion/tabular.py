"""Deterministic extraction from tabular documents.

A CSV or spreadsheet already *has* structure. Asking a language model to
re-derive columns it can read directly would be slower, more expensive and less
reliable — so tabular sources are parsed by rule, and the model is reserved for
the genuinely unstructured material (emails, scanned-looking PDFs, free text).

Header matching is deliberately generous about spelling, because these files are
written by whoever happened to be at the keyboard: "Qty", "QUANTITY", "qty."
and "quantity_kg" all mean the same thing. It is *not* generous about units: a
missing or unrecognised unit is reported, never assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from textileops.core.errors import ValidationError
from textileops.core.units import parse_unit

#: Column meanings, in priority order. First match wins.
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "quantity": ("quantity", "qty", "qnty", "nos", "count", "pieces", "meters", "metres", "mtrs"),
    "unit": ("unit", "uom", "units", "measure"),
    "material": ("material", "item", "description", "product", "particulars", "fabric", "yarn"),
    "reference": ("reference", "ref", "po", "po_no", "po_number", "order", "order_no", "invoice"),
    "lot": ("lot", "lot_no", "batch", "batch_no", "roll", "roll_no"),
    "price": ("price", "rate", "unit_price", "amount", "value"),
    "date": ("date", "dispatch_date", "delivery_date", "received"),
}

_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")
#: "1,200 kgs" in one cell — a common way people write quantities.
_QTY_WITH_UNIT = re.compile(r"^\s*(\d[\d,]*\.?\d*)\s*([A-Za-z]+)\s*$")


@dataclass
class TabularLine:
    description: str
    material_text: str | None
    quantity: Decimal | None
    unit_raw: str | None
    unit_normalised: str | None
    reference: str | None
    lot: str | None
    price_text: str | None
    #: Why this row could not be fully understood, if it could not.
    issue: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "material_text": self.material_text,
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "unit_raw": self.unit_raw,
            "unit_normalised": self.unit_normalised,
            "reference": self.reference,
            "lot": self.lot,
            "price_text": self.price_text,
            "issue": self.issue,
        }


def _normalise_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def map_headers(headers: list[str]) -> dict[str, str]:
    """Map each recognised meaning to the column that carries it."""
    mapping: dict[str, str] = {}
    normalised = {header: _normalise_header(header) for header in headers}
    for meaning, synonyms in HEADER_SYNONYMS.items():
        for header, key in normalised.items():
            if key in synonyms or any(key.startswith(f"{s}_") for s in synonyms):
                mapping[meaning] = header
                break
    return mapping


def _to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = _NUMBER.search(value)
    if not match:
        return None
    try:
        parsed = Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    return parsed if parsed > 0 else None


def extract_rows(rows: list[dict[str, Any]]) -> list[TabularLine]:
    """Turn parsed spreadsheet rows into structured lines."""
    if not rows:
        return []
    headers = [key for key in rows[0] if key != "_sheet"]
    mapping = map_headers(headers)
    lines: list[TabularLine] = []

    for row in rows:
        raw_quantity = str(row.get(mapping.get("quantity", ""), "") or "")
        raw_unit = str(row.get(mapping.get("unit", ""), "") or "")

        # "1,200 kgs" in the quantity cell: split it rather than lose the unit.
        combined = _QTY_WITH_UNIT.match(raw_quantity)
        if combined and not raw_unit:
            raw_quantity, raw_unit = combined.group(1), combined.group(2)

        quantity = _to_decimal(raw_quantity)
        unit_normalised: str | None = None
        issue: str | None = None
        if quantity is not None:
            if raw_unit:
                try:
                    unit_normalised = parse_unit(raw_unit).value
                except ValidationError:
                    issue = f"Unit {raw_unit!r} was not recognised."
            else:
                issue = "A quantity was given with no unit; TextileOps will not assume one."

        material = row.get(mapping.get("material", ""))
        description = str(material or "").strip()
        if not description:
            description = " ".join(
                str(value).strip() for value in row.values() if value and value != "_sheet"
            )[:300]
        if not description:
            continue

        lines.append(
            TabularLine(
                description=description[:300],
                material_text=str(material).strip() if material else None,
                quantity=quantity,
                unit_raw=raw_unit or None,
                unit_normalised=unit_normalised,
                reference=(str(row.get(mapping.get("reference", ""), "")) or None),
                lot=(str(row.get(mapping.get("lot", ""), "")) or None),
                price_text=(str(row.get(mapping.get("price", ""), "")) or None),
                issue=issue,
            )
        )
    return lines
