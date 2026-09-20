"""What may each model-populated field establish? Decided here, in one place.

The supplier-authority bypass was not a coding slip. It was a field whose
influence nobody had written down: ``supplier_name_text`` existed to label a
message for display, was quietly used to set ``message.supplier_id``, and that
column was then read as proof of identity by the check that decides whether a
message may move a delivery date.

Nothing about that was visible at any single call site. So this module states,
for every field a model fills in, what it is allowed to reach — and fails when
a schema grows a field that nobody has classified.

The rule these enforce: **a model may say what a document appears to claim; it
may never establish who someone is, what they are permitted to do, what is in
stock, what is owed, or what state an order is in.**
"""

from __future__ import annotations

import pytest

from textileops.ai.schemas import (
    DocumentClassification,
    DocumentExtraction,
    InvestigationFindings,
    LineItemExtraction,
    SupplierMessageExtraction,
)
from textileops.ingestion import pipeline
from textileops.models.intake import Message, SourceDocument

#: How far each model-populated field is permitted to reach.
#:
#: provenance    recorded as an ExtractedFact and shown to a person; reaches no
#:               transactional column
#: resolution    used as *search text* to look a record up; a match still has to
#:               clear its own deterministic checks, and a failure asks a human
#:               rather than guessing
#: caution       may only ever send a claim to a person, never release one
#: label         a display/classification value on the source record itself,
#:               carrying no authority over any business entity
FIELD_REACH: dict[str, dict[str, str]] = {
    "SupplierMessageExtraction": {
        "intent": "label",
        "confidence": "caution",
        "supplier_name_text": "resolution",
        "purchase_order_reference": "resolution",
        "material_text": "resolution",
        "delay_days": "provenance",
        "new_expected_date_text": "provenance",
        "quantity": "provenance",
        "reason_text": "provenance",
        "requires_human_review": "caution",
        "review_reason": "provenance",
        "summary": "provenance",
    },
    "DocumentClassification": {
        "kind": "label",
        "confidence": "caution",
        "reasoning": "provenance",
        "supplier_name_text": "resolution",
        "customer_name_text": "resolution",
        "document_reference": "provenance",
        "document_date_text": "provenance",
    },
    "DocumentExtraction": {
        "document_reference": "provenance",
        "counterparty_name_text": "resolution",
        "document_date_text": "provenance",
        "lines": "provenance",
        "total_text": "provenance",
        "currency_text": "provenance",
        "notes": "provenance",
        "requires_human_review": "caution",
        "review_reason": "provenance",
    },
    "LineItemExtraction": {
        "description_text": "provenance",
        "material_or_fabric_text": "resolution",
        "quantity": "provenance",
        "unit_price_text": "provenance",
        "line_reference": "provenance",
    },
    "InvestigationFindings": {
        "what_happened": "provenance",
        "evidence": "provenance",
        "root_cause": "provenance",
        "operational_impact": "provenance",
        "financial_impact": "provenance",
        "options": "provenance",
        "recommended_action": "provenance",
        "missing_information": "provenance",
        "confidence": "caution",
    },
}

SCHEMAS = {
    "SupplierMessageExtraction": SupplierMessageExtraction,
    "DocumentClassification": DocumentClassification,
    "DocumentExtraction": DocumentExtraction,
    "LineItemExtraction": LineItemExtraction,
    "InvestigationFindings": InvestigationFindings,
}


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_model_populated_field_has_a_declared_reach(name):
    """A new field is a new way for a model to influence the business.

    Failing here is the point: it makes someone decide what the field may do
    before it ships, which is the step that was skipped once already.
    """
    declared = set(FIELD_REACH[name])
    actual = set(SCHEMAS[name].model_fields)
    assert actual == declared, (
        f"{name}: undeclared field(s) {sorted(actual - declared)}; "
        f"stale declaration(s) {sorted(declared - actual)}. Decide what the field "
        "may reach and record it in FIELD_REACH."
    )


def test_no_model_field_is_declared_as_establishing_authority():
    """There is deliberately no 'authority' reach. Identity is not extracted."""
    reaches = {r for schema in FIELD_REACH.values() for r in schema.values()}
    assert reaches <= {"provenance", "resolution", "caution", "label"}


def test_a_document_cannot_be_attributed_to_a_counterparty_at_all():
    """The message path's defect cannot exist here, structurally.

    `DocumentClassification` gives the model `supplier_name_text` and
    `customer_name_text`, which is the same shape that caused the bypass on
    messages. It is safe for a reason worth pinning down: `source_documents`
    has no counterparty column, so there is nowhere for the name to land. The
    resolution result only ever opens a reconciliation question.
    """
    columns = {c.name for c in SourceDocument.__table__.columns}
    assert not (columns & {"supplier_id", "customer_id"}), (
        "source_documents gained a counterparty column; a model-extracted name "
        "can now be written to it, which is exactly how the message bypass "
        "happened. Add an attribution column and gate it before doing this."
    )


def test_a_message_records_where_its_attribution_came_from():
    """Identity on a message is a claim with a source, not a bare id."""
    columns = {c.name for c in Message.__table__.columns}
    assert {"supplier_id", "supplier_attribution"} <= columns


def test_a_body_derived_attribution_is_never_authoritative():
    """The single line the whole bypass turned on."""
    assert (
        pipeline.SUPPLIER_ATTRIBUTION_EXTRACTED not in pipeline.AUTHORITATIVE_ATTRIBUTIONS
    )
    assert {
        pipeline.SUPPLIER_ATTRIBUTION_CALLER,
        pipeline.SUPPLIER_ATTRIBUTION_SENDER,
    } == pipeline.AUTHORITATIVE_ATTRIBUTIONS


def test_a_customer_is_never_attributed_from_extracted_text():
    """`Message.customer_id` has no attribution column, so it must never be
    set from anything a model read. Only a caller may set it."""
    source = (pipeline.__file__ or "").replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "message.customer_id =" not in text, (
        "something now assigns Message.customer_id after ingestion; if that is "
        "from extracted text it repeats the supplier bypass, and customer_id has "
        "no attribution column to gate it"
    )
