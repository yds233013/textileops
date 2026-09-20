"""Schema-constrained contracts for every AI output.

Nothing a model returns enters the system without passing through one of these
Pydantic models first. A model that cannot produce a valid instance has
produced nothing — that is a validation failure, not a partial success.

Note what is deliberately *absent*: none of these schemas carry a database id,
a balance, or a computed total. Models identify things by the text that
appeared in the source (a PO number, a material name); resolving that text to a
row is the entity-resolution step, and arithmetic is the deterministic
services' job.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from textileops.models.enums import DocumentKind, MessageIntent

Confidence = float


class ExtractionProvenance(BaseModel):
    """How a single field was arrived at."""

    raw_text: str = Field(description="The exact substring of the source this came from.")
    confidence: Confidence = Field(ge=0.0, le=1.0)
    note: str | None = None


class QuantityClaim(BaseModel):
    """A quantity as stated in a document, with its unit kept verbatim.

    ``unit_text`` is never normalised by the model — 'mtr', 'yds' and 'kg' are
    resolved by :mod:`textileops.core.units`, which refuses to guess.
    """

    value: Decimal = Field(gt=0)
    unit_text: str = Field(min_length=1, max_length=16)
    raw_text: str

    @field_validator("value", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> object:
        if isinstance(v, str):
            return v.replace(",", "").strip()
        return v


class DocumentClassification(BaseModel):
    kind: DocumentKind
    confidence: Confidence = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=500)
    #: Counterparty names as written in the document; resolved separately.
    supplier_name_text: str | None = None
    customer_name_text: str | None = None
    document_reference: str | None = Field(
        default=None, description="Invoice/PO/challan number printed on the document."
    )
    document_date_text: str | None = None


class SupplierMessageExtraction(BaseModel):
    """What a supplier message claims. Claims, not facts."""

    intent: MessageIntent
    confidence: Confidence = Field(ge=0.0, le=1.0)
    supplier_name_text: str | None = None
    purchase_order_reference: str | None = Field(
        default=None, description="PO number exactly as written, e.g. 'PO-00042'."
    )
    material_text: str | None = Field(
        default=None, description="Material as described, e.g. '40s combed cotton'."
    )
    delay_days: int | None = Field(default=None, ge=0, le=365)
    new_expected_date_text: str | None = Field(
        default=None, description="Any date given, copied verbatim; not parsed."
    )
    quantity: QuantityClaim | None = None
    reason_text: str | None = Field(default=None, max_length=500)
    requires_human_review: bool = Field(
        default=False,
        description="Set when the message is ambiguous, contradictory or incomplete.",
    )
    review_reason: str | None = None
    summary: str = Field(max_length=400)


class LineItemExtraction(BaseModel):
    description_text: str
    material_or_fabric_text: str | None = None
    quantity: QuantityClaim | None = None
    unit_price_text: str | None = None
    line_reference: str | None = None


class DocumentExtraction(BaseModel):
    """Structured content of a commercial document."""

    document_reference: str | None = None
    counterparty_name_text: str | None = None
    document_date_text: str | None = None
    lines: list[LineItemExtraction] = Field(default_factory=list, max_length=200)
    total_text: str | None = None
    currency_text: str | None = None
    notes: str | None = Field(default=None, max_length=1000)
    requires_human_review: bool = False
    review_reason: str | None = None


# --- Investigation ------------------------------------------------------------


class EvidenceRef(BaseModel):
    label: str = Field(max_length=200)
    detail: str = Field(max_length=1000)
    #: Which read-only tool call this came from, so a human can re-check it.
    source: str = Field(max_length=120)


class RootCause(BaseModel):
    statement: str = Field(max_length=600)
    #: 'established' means every supporting fact came from a tool result;
    #: 'hypothesis' means the investigator is inferring.
    kind: Literal["established", "hypothesis"]
    supporting_evidence: list[str] = Field(default_factory=list, max_length=10)


class OptionItem(BaseModel):
    title: str = Field(max_length=200)
    description: str = Field(max_length=800)
    trade_off: str = Field(max_length=400)


class ProposedAction(BaseModel):
    """A *proposal*, which a human must still approve before anything happens."""

    action_type: str = Field(
        description="One of the ActionType values supported by the application."
    )
    title: str = Field(max_length=200)
    rationale: str = Field(max_length=1000)
    draft_subject: str | None = Field(default=None, max_length=200)
    draft_body: str | None = Field(default=None, max_length=4000)


class InvestigationFindings(BaseModel):
    what_happened: str = Field(max_length=1500)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=20)
    root_cause: RootCause
    operational_impact: str = Field(max_length=1200)
    #: Must restate only figures produced by the deterministic impact engine.
    financial_impact: str = Field(max_length=800)
    options: list[OptionItem] = Field(default_factory=list, max_length=5)
    recommended_action: ProposedAction | None = None
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    confidence: Confidence = Field(ge=0.0, le=1.0)


class CommunicationDraft(BaseModel):
    subject: str = Field(max_length=200)
    body: str = Field(max_length=4000)
    tone_note: str | None = Field(default=None, max_length=200)
