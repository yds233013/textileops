"""Entity resolution: turning text into a row, or admitting we cannot.

Extraction gives us strings — "PO 42", "40s combed cotton", "Sri Balaji". This
module maps them to records using exact, then normalised, then fuzzy matching,
and reports *how* it matched so the caller can decide whether to act
automatically or ask a person.

The rule that matters: a low-confidence match is never applied silently. It
becomes a :class:`ReconciliationItem` with candidates, and a human chooses.
"""

from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.models.catalog import Material
from textileops.models.org import Customer, Supplier
from textileops.models.procurement import PurchaseOrder

T = TypeVar("T")

#: At or above this similarity we accept a fuzzy name match automatically.
AUTO_ACCEPT_SCORE = 0.88
#: Below this we do not even offer it as a candidate.
CANDIDATE_FLOOR = 0.55


@dataclass
class Resolution(Generic[T]):
    entity: T | None
    #: "exact_reference" | "exact_name" | "fuzzy" | "ambiguous" | "none"
    method: str
    score: float
    candidates: list[tuple[str, str, float]]  # (id, label, score)

    @property
    def resolved(self) -> bool:
        return self.entity is not None

    @property
    def needs_review(self) -> bool:
        return self.entity is None and bool(self.candidates)


def normalise_reference(text: str | None) -> str | None:
    """``"po 42"`` → ``"PO-42"``. Reference formats vary by who typed them."""
    if not text:
        return None
    cleaned = re.sub(r"[\s_\-]+", "", text.strip().upper())
    match = re.match(r"^([A-Z]+)(\d+)$", cleaned)
    if match:
        prefix, digits = match.groups()
        return f"{prefix}-{digits}"
    return re.sub(r"[\s_]+", "-", text.strip().upper())


def _normalise_name(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"\b(pvt|private|ltd|limited|llp|inc|co|company|mills|textiles?)\b", " ",
                     lowered)
    return re.sub(r"[^a-z0-9 ]+", " ", lowered).strip()


def _score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalise_name(a), _normalise_name(b)).ratio()


def resolve_purchase_order(session: Session, reference: str | None) -> Resolution[PurchaseOrder]:
    if not reference:
        return Resolution(None, "none", 0.0, [])
    normalised = normalise_reference(reference)
    po = session.scalar(select(PurchaseOrder).where(PurchaseOrder.number == normalised))
    if po:
        return Resolution(po, "exact_reference", 1.0, [])

    # Fall back to matching just the numeric part, which is how people quote them.
    digits = re.sub(r"\D", "", reference or "")
    if digits:
        candidates = [
            candidate
            for candidate in session.scalars(select(PurchaseOrder)).all()
            if re.sub(r"\D", "", candidate.number).lstrip("0") == digits.lstrip("0")
        ]
        if len(candidates) == 1:
            return Resolution(candidates[0], "exact_reference", 0.95, [])
        if len(candidates) > 1:
            return Resolution(
                None,
                "ambiguous",
                0.0,
                [(str(c.id), c.number, 0.9) for c in candidates],
            )
    return Resolution(None, "none", 0.0, [])


#: Every entity this module resolves by name has both a ``name`` and a ``code``.
NamedEntity = Customer | Material | Supplier


def _resolve_by_name(
    session: Session,
    model: type[NamedEntity],
    text: str | None,
    *,
    label_attr: str = "name",
) -> Resolution:
    if not text:
        return Resolution(None, "none", 0.0, [])
    stripped = text.strip()
    exact = session.scalar(select(model).where(model.name.ilike(stripped)))
    if exact:
        return Resolution(exact, "exact_name", 1.0, [])
    by_code = session.scalar(select(model).where(model.code.ilike(stripped)))
    if by_code:
        return Resolution(by_code, "exact_reference", 1.0, [])

    scored: list[tuple[NamedEntity, float]] = []
    for row in session.scalars(select(model)).all():
        candidate = cast(NamedEntity, row)
        score = _score(stripped, getattr(candidate, label_attr))
        if score >= CANDIDATE_FLOOR:
            scored.append((candidate, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    if not scored:
        return Resolution(None, "none", 0.0, [])

    best, best_score = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else 0.0
    # A clear winner is accepted; a near-tie is a question for a person.
    if best_score >= AUTO_ACCEPT_SCORE and best_score - runner_up >= 0.08:
        return Resolution(best, "fuzzy", best_score, [])
    return Resolution(
        None,
        "ambiguous",
        best_score,
        [(str(c.id), getattr(c, label_attr), round(s, 3)) for c, s in scored[:5]],
    )


def resolve_supplier(session: Session, name: str | None) -> Resolution[Supplier]:
    return _resolve_by_name(session, Supplier, name)


def resolve_customer(session: Session, name: str | None) -> Resolution[Customer]:
    return _resolve_by_name(session, Customer, name)


def resolve_material(session: Session, text: str | None) -> Resolution[Material]:
    """Materials are described loosely ("40s combed cotton"), so try the
    distinguishing tokens — yarn count and fibre — before generic similarity."""
    if not text:
        return Resolution(None, "none", 0.0, [])
    direct = _resolve_by_name(session, Material, text)
    if direct.resolved:
        return direct

    tokens = set(_normalise_name(text).split())
    scored: list[tuple[Material, float]] = []
    for material in session.scalars(select(Material)).all():
        material_tokens = set(_normalise_name(f"{material.name} {material.yarn_count_text or ''}")
                              .split())
        if not material_tokens:
            continue
        overlap = len(tokens & material_tokens) / max(1, len(material_tokens))
        score = max(overlap, _score(text, material.name))
        if score >= CANDIDATE_FLOOR:
            scored.append((material, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    if not scored:
        return direct
    best, best_score = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else 0.0
    if best_score >= AUTO_ACCEPT_SCORE and best_score - runner_up >= 0.08:
        return Resolution(best, "fuzzy", best_score, [])
    return Resolution(
        None,
        "ambiguous",
        best_score,
        [(str(m.id), m.name, round(s, 3)) for m, s in scored[:5]],
    )


def resolve_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None
