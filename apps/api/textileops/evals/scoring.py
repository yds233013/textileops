"""One definition of what an evaluation case means.

There used to be two. :mod:`textileops.evals.runner` projected a validated
extraction into a flat set of comparable values (``quantity_value``,
``quantity_unit``, ``has_date`` …) and compared the case against that.
:mod:`textileops.evals.live` re-implemented the comparison with a bare
``getattr`` on the Pydantic model — and none of those names are attributes of
the model, so every lookup returned ``None``.

The consequence was not "some cases mis-scored". It was worse in both
directions at once: a *correct* extraction failed every expectation, and the
``must_not`` traps — the ones that exist to catch 10,000 yards read as metres,
or a yarn count read as a mass — were guarded by ``actual is not None`` and so
could never fire. ``traps_tripped`` was structurally zero, and the live suite
exited 0 whatever the model did.

So the projection lives here, once, and both runners use it.

The second lesson is in :func:`score`: an expectation naming a field the
projection does not produce raises. That is what made the original defect
invisible — an unknown field name degraded quietly to ``None`` instead of
saying "nobody knows how to check this". A misspelt or obsolete field name is
now a loud failure, not a silent pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from textileops.ai.schemas import DocumentExtraction, SupplierMessageExtraction


class UnknownExpectation(ValueError):
    """A case names a field no projection produces. Always a bug in the case."""


@dataclass
class CaseScore:
    passed: bool
    trap_tripped: bool
    notes: list[str] = field(default_factory=list)
    #: The projection actually compared, so a report can show what was seen.
    actuals: dict[str, Any] = field(default_factory=dict)


def plain(value: Decimal) -> str:
    """Render a quantity the way a person writes it, never as 1E+4."""
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def normalise(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


def message_actuals(value: SupplierMessageExtraction) -> dict[str, Any]:
    """Flatten a supplier-message extraction into comparable values.

    ``quantity_unit`` stays verbatim from the model (lower-cased only) because
    the whole point of the unit cases is that the model must *not* normalise
    'yds' to 'm'. Normalising here would hide exactly what we are testing.
    """
    return {
        "intent": value.intent.value,
        "confidence": float(value.confidence),
        "delay_days": value.delay_days,
        "purchase_order_reference": value.purchase_order_reference,
        "supplier_name_text": value.supplier_name_text,
        "material_text": value.material_text,
        "quantity_value": plain(value.quantity.value) if value.quantity else None,
        "quantity_unit": value.quantity.unit_text.lower() if value.quantity else None,
        "quantity_raw_text": value.quantity.raw_text if value.quantity else None,
        "new_expected_date_text": value.new_expected_date_text,
        "has_date": value.new_expected_date_text is not None,
        "requires_human_review": value.requires_human_review,
        "review_reason": value.review_reason,
        "summary": value.summary,
    }


def document_actuals(value: DocumentExtraction) -> dict[str, Any]:
    units = [
        line.quantity.unit_text.lower() for line in value.lines if line.quantity is not None
    ]
    return {
        "line_count": len(value.lines),
        "document_reference": value.document_reference,
        "counterparty_name_text": value.counterparty_name_text,
        "requires_human_review": value.requires_human_review,
        "units": units,
        "distinct_units": sorted(set(units)),
    }


#: Expectations that are not equality comparisons.
_COMPARATORS = {
    # "at least this many line items" — a document may legitimately carry more.
    "min_lines": lambda actuals, expected: actuals["line_count"] >= int(expected),
    # "these units must all appear, verbatim" — the mixed-unit document case.
    "units_include": lambda actuals, expected: all(
        normalise(u) in actuals["units"] for u in expected
    ),
}


def score(case: Any, actuals: dict[str, Any]) -> CaseScore:
    """Apply one case's expectations to a projection.

    ``expect`` must match. ``must_not`` is a trap: a specific wrong answer the
    case exists to catch, and tripping one is a correctness failure rather than
    a missing optional field. ``expect_review`` asserts the model asked for a
    human on a case where that is the only right answer.
    """
    notes: list[str] = []
    passed = True
    trap = False

    for field_name, expected in (getattr(case, "expect", None) or {}).items():
        comparator = _COMPARATORS.get(field_name)
        if comparator is not None:
            if not comparator(actuals, expected):
                passed = False
                notes.append(
                    f"expected {field_name}={expected!r}, got "
                    f"line_count={actuals.get('line_count')} units={actuals.get('units')}"
                )
            continue
        if field_name not in actuals:
            raise UnknownExpectation(
                f"Case {getattr(case, 'key', '?')!r} expects {field_name!r}, which no "
                "projection produces. Add it to the projection or fix the case — a "
                "field nobody knows how to read is a case that silently always passes."
            )
        actual = actuals[field_name]
        if normalise(actual) != normalise(expected):
            passed = False
            notes.append(f"expected {field_name}={expected!r}, got {actual!r}")

    for field_name, forbidden in (getattr(case, "must_not", None) or {}).items():
        if field_name not in actuals:
            raise UnknownExpectation(
                f"Case {getattr(case, 'key', '?')!r} forbids {field_name!r}, which no "
                "projection produces. A trap that cannot be read is a trap that never "
                "fires."
            )
        if normalise(actuals[field_name]) == normalise(forbidden):
            trap = True
            passed = False
            notes.append(
                f"TRAP: {field_name} must never be {forbidden!r} — that is the specific "
                "wrong answer this case exists to catch"
            )

    expect_review = getattr(case, "expect_review", None)
    if expect_review is not None:
        actual_review = actuals.get("requires_human_review")
        if actual_review != expect_review:
            passed = False
            notes.append(
                f"expected requires_human_review={expect_review}, got {actual_review!r}"
            )

    return CaseScore(passed=passed, trap_tripped=trap, notes=notes, actuals=actuals)
