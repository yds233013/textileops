"""The ingestion pipeline.

    raw source → parse → AI extraction → schema validation → entity resolution
    → deterministic application logic → state update

Two invariants hold throughout:

* **Extraction never mutates business state.** It produces
  :class:`ExtractedFact` rows. Applying a fact is a separate, deterministic
  step with its own rules, its own audit event and its own provenance.
* **Source material is never destroyed.** Superseding a fact links the old one
  to the new; documents and messages are immutable once received.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.ai.prompts import (
    PROMPT_VERSION,
    classification_system_prompt,
    document_extraction_system_prompt,
    supplier_message_system_prompt,
    wrap_untrusted,
)
from textileops.ai.provider import get_provider
from textileops.ai.schemas import (
    DocumentClassification,
    DocumentExtraction,
    SupplierMessageExtraction,
)
from textileops.ai.telemetry import record_call
from textileops.core.errors import ValidationError
from textileops.core.logging import get_logger
from textileops.core.units import parse_unit
from textileops.ingestion import parsers, resolution, storage, tabular
from textileops.models.enums import (
    BusinessEventType,
    DocumentKind,
    DocumentStatus,
    EntityType,
    FactStatus,
    MessageDirection,
    MessageIntent,
    ReconciliationStatus,
    SourceChannel,
)
from textileops.models.intake import (
    ExtractedFact,
    Message,
    ReconciliationItem,
    SourceDocument,
)
from textileops.models.procurement import PurchaseOrder
from textileops.services import clock, procurement
from textileops.services.audit import record_audit, record_metric

logger = get_logger(__name__)

EXTRACTOR_VERSION = "v1"
#: Below this confidence a fact is never applied without a human.
APPLY_CONFIDENCE_FLOOR = 0.5


@dataclass
class IngestionOutcome:
    document_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    kind: DocumentKind | None = None
    facts_created: int = 0
    facts_applied: int = 0
    reconciliation_items: int = 0
    duplicate_of: uuid.UUID | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --- Documents ----------------------------------------------------------------


def receive_document(
    session: Session,
    *,
    content: bytes,
    filename: str,
    content_type: str,
    channel: SourceChannel = SourceChannel.UPLOAD,
    uploaded_by_user_id: uuid.UUID | None = None,
) -> SourceDocument:
    """Persist an upload. Processing happens later, in a worker."""
    stored = storage.store(content, filename=filename)
    duplicate = session.scalar(
        select(SourceDocument).where(SourceDocument.sha256 == stored.sha256).limit(1)
    )
    document = SourceDocument(
        filename=stored.display_name,
        stored_path=stored.stored_path,
        content_type=content_type[:120],
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        channel=channel,
        kind=DocumentKind.UNKNOWN,
        status=DocumentStatus.QUEUED,
        received_at=clock.now(),
        uploaded_by_user_id=uploaded_by_user_id,
        duplicate_of_id=duplicate.id if duplicate else None,
    )
    session.add(document)
    session.flush()

    record_audit(
        session,
        action="document.received",
        entity_type=EntityType.SOURCE_DOCUMENT,
        entity_id=document.id,
        summary=f"Received {document.filename} via {channel.value}."
        + (" Duplicate of an earlier upload." if duplicate else ""),
        actor_type="user" if uploaded_by_user_id else "system",
        actor_user_id=uploaded_by_user_id,
        source_document_id=document.id,
    )
    record_metric(
        session,
        event_type=BusinessEventType.DOCUMENT_RECEIVED,
        entity_type=EntityType.SOURCE_DOCUMENT,
        entity_id=document.id,
        user_id=uploaded_by_user_id,
        payload={"channel": channel.value, "duplicate": bool(duplicate)},
    )
    return document


def process_document(session: Session, document: SourceDocument) -> IngestionOutcome:
    """Parse, classify and extract. Idempotent: re-running replaces the facts
    derived from this document rather than adding a second set."""
    outcome = IngestionOutcome(document_id=document.id)
    started = clock.now()
    document.status = DocumentStatus.PROCESSING
    session.flush()

    try:
        raw = storage.read(document.stored_path) if document.stored_path else b""
        parsed = parsers.parse(
            raw, filename=document.filename, content_type=document.content_type
        )
    except ValidationError as exc:
        document.status = DocumentStatus.FAILED
        document.error = exc.message
        document.processed_at = clock.now()
        outcome.warnings.append(exc.message)
        return outcome

    document.extracted_text = parsed.text
    document.page_count = parsed.page_count
    document.doc_metadata = {"warnings": parsed.warnings, "row_count": len(parsed.rows)}
    outcome.warnings.extend(parsed.warnings)

    provider = get_provider()
    classification = provider.structured(
        workflow="classify_document",
        system=classification_system_prompt(),
        user_content=wrap_untrusted(parsed.text[:20000], label=document.filename),
        schema=DocumentClassification,
        context={"filename": document.filename},
    )
    record_call(
        session,
        workflow="classify_document",
        result=classification,
        entity_type=EntityType.SOURCE_DOCUMENT,
        entity_id=document.id,
        prompt_version=PROMPT_VERSION,
    )
    if classification.value:
        document.kind = classification.value.kind
        document.classification_confidence = Decimal(str(classification.value.confidence))
        outcome.kind = classification.value.kind

    # Clear facts from a previous run of *this* document, so reprocessing is safe.
    for stale in session.scalars(
        select(ExtractedFact).where(ExtractedFact.source_document_id == document.id)
    ).all():
        session.delete(stale)
    session.flush()

    # A spreadsheet already has columns. Reading them by rule is faster, cheaper
    # and more reliable than asking a model to re-derive structure it can see.
    if parsed.rows:
        needs_review = _facts_from_rows(session, document, parsed.rows, outcome)
        document.status = (
            DocumentStatus.NEEDS_REVIEW if needs_review else DocumentStatus.EXTRACTED
        )
        document.processed_at = clock.now()
        record_metric(
            session,
            event_type=BusinessEventType.DOCUMENT_PROCESSED,
            entity_type=EntityType.SOURCE_DOCUMENT,
            entity_id=document.id,
            duration_ms=clock.elapsed_ms(started),
            payload={
                "kind": document.kind.value,
                "facts": outcome.facts_created,
                "status": document.status.value,
                "extractor": "tabular",
            },
        )
        session.flush()
        return outcome

    extraction = provider.structured(
        workflow="extract_document",
        system=document_extraction_system_prompt(),
        user_content=wrap_untrusted(parsed.text[:40000], label=document.filename),
        schema=DocumentExtraction,
        context={"filename": document.filename},
    )
    record_call(
        session,
        workflow="extract_document",
        result=extraction,
        entity_type=EntityType.SOURCE_DOCUMENT,
        entity_id=document.id,
        prompt_version=PROMPT_VERSION,
    )

    needs_review = False
    if extraction.value:
        payload = extraction.value
        needs_review = payload.requires_human_review
        counterparty = _resolve_counterparty(session, document, payload.counterparty_name_text)
        for index, line in enumerate(payload.lines):
            fact = ExtractedFact(
                source_document_id=document.id,
                fact_type="document.line_item",
                field_path=f"lines[{index}]",
                raw_value=line.description_text[:2000],
                normalized_value=_line_to_json(line),
                unit=line.quantity.unit_text if line.quantity else None,
                confidence=Decimal("0.6") if not extraction.stubbed else Decimal("0.4"),
                status=FactStatus.PROPOSED,
                model=extraction.model,
                ai_request_id=extraction.request_id,
                extractor_version=EXTRACTOR_VERSION,
            )
            session.add(fact)
            outcome.facts_created += 1
            _flag_unresolved_material(session, document, fact, line.material_or_fabric_text)

        if payload.document_reference:
            session.add(
                ExtractedFact(
                    source_document_id=document.id,
                    fact_type="document.reference",
                    raw_value=payload.document_reference,
                    normalized_value={
                        "reference": resolution.normalise_reference(payload.document_reference)
                    },
                    confidence=Decimal("0.8"),
                    status=FactStatus.PROPOSED,
                    model=extraction.model,
                    ai_request_id=extraction.request_id,
                    extractor_version=EXTRACTOR_VERSION,
                )
            )
            outcome.facts_created += 1
        if counterparty is not None and counterparty.needs_review:
            _open_reconciliation(
                session,
                document=document,
                kind="entity_resolution",
                question=(
                    f"Which trading partner is “{payload.counterparty_name_text}” in "
                    f"{document.filename}?"
                ),
                candidates=[
                    {"id": cid, "label": label, "score": score}
                    for cid, label, score in counterparty.candidates
                ],
            )
            outcome.reconciliation_items += 1
            needs_review = True
    else:
        needs_review = True
        outcome.warnings.append(
            extraction.validation_error or "Extraction produced no structured result."
        )

    document.status = (
        DocumentStatus.NEEDS_REVIEW
        if needs_review or outcome.reconciliation_items
        else DocumentStatus.EXTRACTED
    )
    document.processed_at = clock.now()

    record_metric(
        session,
        event_type=BusinessEventType.DOCUMENT_PROCESSED,
        entity_type=EntityType.SOURCE_DOCUMENT,
        entity_id=document.id,
        duration_ms=clock.elapsed_ms(started),
        payload={
            "kind": document.kind.value,
            "facts": outcome.facts_created,
            "status": document.status.value,
        },
    )
    session.flush()
    return outcome


def _line_to_json(line: Any) -> dict[str, Any]:
    quantity = line.quantity
    normalised_unit = None
    if quantity:
        try:
            normalised_unit = parse_unit(quantity.unit_text).value
        except ValidationError:
            normalised_unit = None
    return {
        "description": line.description_text,
        "material_text": line.material_or_fabric_text,
        "quantity": str(quantity.value) if quantity else None,
        "unit_raw": quantity.unit_text if quantity else None,
        "unit_normalised": normalised_unit,
        "line_reference": line.line_reference,
    }


def _facts_from_rows(
    session: Session,
    document: SourceDocument,
    rows: list[dict[str, Any]],
    outcome: IngestionOutcome,
) -> bool:
    """Create facts from a parsed spreadsheet. Returns whether review is needed."""
    lines = tabular.extract_rows(rows)
    if not lines:
        outcome.warnings.append(
            "No rows with a recognisable description were found in this file."
        )
        return True

    needs_review = False
    for index, line in enumerate(lines):
        fact = ExtractedFact(
            source_document_id=document.id,
            fact_type="document.line_item",
            field_path=f"rows[{index}]",
            raw_value=line.description[:2000],
            normalized_value=line.to_json(),
            unit=line.unit_raw,
            # Read directly from labelled columns, so the reading itself is
            # certain; whether it maps to the right record is a separate question.
            confidence=Decimal("0.95"),
            status=FactStatus.NEEDS_REVIEW if line.issue else FactStatus.PROPOSED,
            extractor_version=f"{EXTRACTOR_VERSION}-tabular",
            review_reason=line.issue,
        )
        session.add(fact)
        session.flush()
        outcome.facts_created += 1
        if line.issue:
            needs_review = True
            outcome.warnings.append(f"Row {index + 1}: {line.issue}")
        _flag_unresolved_material(session, document, fact, line.material_text)
        if fact.status == FactStatus.NEEDS_REVIEW:
            needs_review = True
    return needs_review


def _resolve_counterparty(
    session: Session, document: SourceDocument, name: str | None
) -> resolution.Resolution | None:
    if not name:
        return None
    if document.kind in (DocumentKind.SALES_ORDER, DocumentKind.CUSTOMER_MESSAGE):
        return resolution.resolve_customer(session, name)
    return resolution.resolve_supplier(session, name)


def _flag_unresolved_material(
    session: Session, document: SourceDocument, fact: ExtractedFact, text: str | None
) -> None:
    if not text:
        return
    match = resolution.resolve_material(session, text)
    if match.resolved:
        session.flush()
        fact.entity_type = EntityType.MATERIAL
        fact.entity_id = match.entity.id  # type: ignore[union-attr]
        return
    if match.needs_review:
        session.flush()
        fact.status = FactStatus.NEEDS_REVIEW
        fact.review_reason = f"Material “{text}” could not be matched with confidence."
        _open_reconciliation(
            session,
            document=document,
            fact=fact,
            kind="entity_resolution",
            question=f"Which material is “{text}”?",
            candidates=[
                {"id": cid, "label": label, "score": score}
                for cid, label, score in match.candidates
            ],
        )


def _open_reconciliation(
    session: Session,
    *,
    kind: str,
    question: str,
    candidates: list[dict[str, Any]],
    document: SourceDocument | None = None,
    message: Message | None = None,
    fact: ExtractedFact | None = None,
) -> ReconciliationItem:
    item = ReconciliationItem(
        extracted_fact_id=fact.id if fact else None,
        source_document_id=document.id if document else None,
        message_id=message.id if message else None,
        kind=kind,
        question=question,
        candidates=candidates,
        status=ReconciliationStatus.OPEN,
    )
    session.add(item)
    record_metric(
        session,
        event_type=BusinessEventType.RECONCILIATION_REQUIRED,
        entity_type=EntityType.SOURCE_DOCUMENT if document else EntityType.MESSAGE,
        entity_id=document.id if document else (message.id if message else None),
        payload={"kind": kind},
    )
    return item


# --- Messages -----------------------------------------------------------------


def receive_message(
    session: Session,
    *,
    body: str,
    sender: str,
    channel: SourceChannel = SourceChannel.MANUAL,
    subject: str | None = None,
    recipient: str | None = None,
    received_at: dt.datetime | None = None,
    supplier_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    external_ref: str | None = None,
    thread_ref: str | None = None,
    source_document_id: uuid.UUID | None = None,
) -> Message:
    """Store an inbound message. Duplicate forwards are linked, never dropped."""
    if not body.strip():
        raise ValidationError("A message must have a body.")
    digest = storage.content_hash(body)
    duplicate = session.scalar(
        select(Message).where(Message.content_hash == digest).order_by(Message.received_at).limit(1)
    )
    message = Message(
        channel=channel,
        direction=MessageDirection.INBOUND,
        sender=sender[:255],
        recipient=recipient,
        subject=subject,
        body=body,
        received_at=received_at or clock.now(),
        external_ref=external_ref,
        thread_ref=thread_ref,
        content_hash=digest,
        supplier_id=supplier_id,
        customer_id=customer_id,
        source_document_id=source_document_id,
        duplicate_of_id=duplicate.id if duplicate else None,
    )
    session.add(message)
    session.flush()
    record_audit(
        session,
        action="message.received",
        entity_type=EntityType.MESSAGE,
        entity_id=message.id,
        summary=f"Message from {message.sender} via {channel.value}."
        + (" Duplicate of an earlier message." if duplicate else ""),
        actor_type="system",
    )
    return message


def process_message(session: Session, message: Message) -> IngestionOutcome:
    """Extract structured claims from a message and, where safe, apply them."""
    outcome = IngestionOutcome(message_id=message.id)
    started = clock.now()

    # A duplicate is only a no-op if the original actually landed. The same
    # text arriving from an authorised sender after an earlier copy was
    # rejected on authority is a different event, and refusing to look at it
    # would leave the real claim permanently unheard.
    if message.duplicate_of_id is not None and _original_was_applied(
        session, message.duplicate_of_id
    ):
        message.processed_at = clock.now()
        outcome.notes.append(
            "This message repeats one that has already been applied; nothing changed."
        )
        return outcome

    provider = get_provider()
    result = provider.structured(
        workflow="extract_supplier_message",
        system=supplier_message_system_prompt(),
        user_content=wrap_untrusted(message.body, label=f"message from {message.sender}"),
        schema=SupplierMessageExtraction,
    )
    record_call(
        session,
        workflow="extract_supplier_message",
        result=result,
        entity_type=EntityType.MESSAGE,
        entity_id=message.id,
        prompt_version=PROMPT_VERSION,
    )

    if result.value is None:
        message.processed_at = clock.now()
        outcome.warnings.append(result.validation_error or "Extraction failed.")
        return outcome

    claim = result.value
    message.intent = claim.intent
    message.intent_confidence = Decimal(str(claim.confidence))

    fact = ExtractedFact(
        message_id=message.id,
        fact_type=f"message.{claim.intent.value}",
        raw_value=message.body[:4000],
        normalized_value=json.loads(claim.model_dump_json()),
        unit=claim.quantity.unit_text if claim.quantity else None,
        confidence=Decimal(str(claim.confidence)),
        status=FactStatus.NEEDS_REVIEW if claim.requires_human_review else FactStatus.PROPOSED,
        model=result.model,
        ai_request_id=result.request_id,
        extractor_version=EXTRACTOR_VERSION,
        review_reason=claim.review_reason,
    )
    session.add(fact)
    session.flush()
    outcome.facts_created = 1

    if claim.supplier_name_text and message.supplier_id is None:
        supplier_match = resolution.resolve_supplier(session, claim.supplier_name_text)
        if supplier_match.resolved:
            message.supplier_id = supplier_match.entity.id  # type: ignore[union-attr]
        elif supplier_match.needs_review:
            _open_reconciliation(
                session,
                message=message,
                fact=fact,
                kind="entity_resolution",
                question=f"Which supplier is “{claim.supplier_name_text}”?",
                candidates=[
                    {"id": cid, "label": label, "score": score}
                    for cid, label, score in supplier_match.candidates
                ],
            )
            outcome.reconciliation_items += 1

    applied = _apply_message_claim(session, message, fact, claim, outcome)
    outcome.facts_applied = 1 if applied else 0

    message.processed_at = clock.now()
    record_metric(
        session,
        event_type=BusinessEventType.EXTRACTION_COMPLETED,
        entity_type=EntityType.MESSAGE,
        entity_id=message.id,
        duration_ms=clock.elapsed_ms(started),
        payload={
            "intent": claim.intent.value,
            "applied": outcome.facts_applied,
            "needs_review": claim.requires_human_review,
        },
    )
    session.flush()
    return outcome


def _original_was_applied(session: Session, message_id: uuid.UUID) -> bool:
    """Did the earlier copy of this message actually change anything?"""
    return (
        session.scalar(
            select(ExtractedFact.id).where(
                ExtractedFact.message_id == message_id,
                ExtractedFact.status == FactStatus.ACCEPTED,
            )
        )
        is not None
    )


def _apply_message_claim(
    session: Session,
    message: Message,
    fact: ExtractedFact,
    claim: SupplierMessageExtraction,
    outcome: IngestionOutcome,
) -> bool:
    """Deterministically apply a supplier-delay claim to a purchase order.

    Everything that could go wrong is a reason *not* to apply and to ask a
    person instead: no PO, an ambiguous PO, an unparseable date, low confidence,
    or a date that would move the ETA *earlier* than currently believed.
    """
    if claim.intent != MessageIntent.SUPPLIER_DELAY:
        outcome.notes.append(
            f"Message classified as {claim.intent.value}; no automatic state change applies."
        )
        return False

    # A model's own signals may only *raise* the bar. `requires_human_review`
    # and a low confidence send the claim to a person; the converse grants
    # nothing. What actually authorises this change is deterministic: the
    # purchase order resolves, the sender is that order's supplier, a usable
    # date can be derived, and it moves the date later.
    if claim.requires_human_review or (claim.confidence or 0) < APPLY_CONFIDENCE_FLOOR:
        fact.status = FactStatus.NEEDS_REVIEW
        _open_reconciliation(
            session,
            message=message,
            fact=fact,
            kind="ambiguous_value",
            question=(
                "This message looks like a supplier delay, but it is not clear enough to "
                "apply automatically. Which purchase order and new date does it mean?"
            ),
            candidates=[],
        )
        outcome.reconciliation_items += 1
        return False

    po_match = resolution.resolve_purchase_order(session, claim.purchase_order_reference)
    if not po_match.resolved:
        fact.status = FactStatus.NEEDS_REVIEW
        fact.review_reason = "The purchase order referenced could not be identified."
        _open_reconciliation(
            session,
            message=message,
            fact=fact,
            kind="entity_resolution",
            question=(
                f"Which purchase order does “{claim.purchase_order_reference or 'this message'}” "
                "refer to?"
            ),
            candidates=[
                {"id": cid, "label": label, "score": score}
                for cid, label, score in po_match.candidates
            ],
        )
        outcome.reconciliation_items += 1
        return False

    po = po_match.entity
    assert po is not None

    # Authority check: only the supplier who owns this order can move its date.
    # Without this, any message naming a PO number could reschedule it — and a
    # PO number is not a secret.
    if not _sender_speaks_for_supplier(session, message, po):
        fact.status = FactStatus.NEEDS_REVIEW
        fact.review_reason = (
            "The sender could not be confirmed as this purchase order's supplier."
        )
        _open_reconciliation(
            session,
            message=message,
            fact=fact,
            kind="sender_not_verified",
            question=(
                f"This message asks to move {po.number}, but {message.sender} could not "
                f"be matched to {po.supplier.name}. Is it from them?"
            ),
            candidates=[],
        )
        outcome.reconciliation_items += 1
        return False

    new_date = _resolve_new_date(claim, po.expected_date, po.current_expected_date)
    if new_date is None:
        fact.status = FactStatus.NEEDS_REVIEW
        fact.review_reason = "No usable new date could be derived from the message."
        _open_reconciliation(
            session,
            message=message,
            fact=fact,
            kind="ambiguous_date",
            question=(
                f"{po.number}: the message mentions a delay but no date could be read. "
                "What is the new expected date?"
            ),
            candidates=[],
        )
        outcome.reconciliation_items += 1
        return False

    if new_date <= po.current_expected_date:
        outcome.notes.append(
            f"The date in this message ({new_date.isoformat()}) is not later than the date "
            f"already recorded for {po.number}; nothing was changed."
        )
        fact.status = FactStatus.REJECTED
        fact.review_reason = "The claimed date does not move the ETA later."
        return False

    # Supersede any earlier ETA fact for this PO so history stays linear.
    for previous in session.scalars(
        select(ExtractedFact).where(
            ExtractedFact.entity_type == EntityType.PURCHASE_ORDER,
            ExtractedFact.entity_id == po.id,
            ExtractedFact.fact_type.like("message.supplier_delay"),
            ExtractedFact.status == FactStatus.ACCEPTED,
        )
    ).all():
        previous.status = FactStatus.SUPERSEDED
        previous.superseded_by_id = fact.id

    procurement.revise_eta(
        session,
        po,
        new_date=new_date,
        reason=claim.reason_text or claim.summary,
        message_id=message.id,
        actor_type="system",
    )
    fact.status = FactStatus.ACCEPTED
    fact.entity_type = EntityType.PURCHASE_ORDER
    fact.entity_id = po.id
    fact.applied_at = clock.now()
    message.supplier_id = message.supplier_id or po.supplier_id
    outcome.notes.append(
        f"{po.number} now expected {new_date.isoformat()} on the strength of this message."
    )
    return True


def _sender_speaks_for_supplier(
    session: Session, message: Message, po: PurchaseOrder
) -> bool:
    """Is this message actually from the supplier whose order it names?"""
    if message.supplier_id is not None:
        return message.supplier_id == po.supplier_id

    sender = (message.sender or "").strip().lower()
    if not sender:
        return False
    contact = (po.supplier.contact_email or "").strip().lower()
    if contact and sender == contact:
        return True
    # Same mail domain as the supplier's recorded contact is good enough to act
    # on; anything else is a question for a person.
    if contact and "@" in contact and "@" in sender:
        return sender.rsplit("@", 1)[1] == contact.rsplit("@", 1)[1]
    return False


def _resolve_new_date(
    claim: SupplierMessageExtraction,
    baseline: dt.date,
    current: dt.date,
) -> dt.date | None:
    """Work out the new arrival date this message implies.

    An explicit date wins. A relative delay ("delayed by four days") is measured
    from the **originally agreed** date, not from whatever we currently believe:
    a supplier who says "we are four days late" twice means four days, not
    eight, and measuring from the current belief would compound the slip every
    time the message was re-read.

    A parsed date far in the past is treated as unusable — a misread year is
    worse than no date at all.
    """
    if claim.new_expected_date_text:
        try:
            parsed = date_parser.parse(
                claim.new_expected_date_text, dayfirst=True, fuzzy=True
            ).date()
        except (ValueError, OverflowError, TypeError):
            parsed = None
        if parsed and current - dt.timedelta(days=365) <= parsed <= current + dt.timedelta(
            days=365 * 2
        ):
            return parsed
    if claim.delay_days:
        return baseline + dt.timedelta(days=claim.delay_days)
    return None


# --- Reconciliation resolution ------------------------------------------------


def resolve_reconciliation(
    session: Session,
    item: ReconciliationItem,
    *,
    resolution_payload: dict[str, Any],
    user_id: uuid.UUID,
    dismiss: bool = False,
) -> ReconciliationItem:
    """Record a human decision.

    Source documents and messages are never deleted here; the fact is updated
    and the decision is stored alongside it.
    """
    item.status = (
        ReconciliationStatus.DISMISSED if dismiss else ReconciliationStatus.RESOLVED
    )
    item.resolved_by_user_id = user_id
    item.resolved_at = clock.now()
    item.resolution = resolution_payload

    fact = item.fact
    if fact is not None and not dismiss:
        chosen_id = resolution.resolve_uuid(resolution_payload.get("entity_id"))
        entity_type = resolution_payload.get("entity_type")
        if chosen_id and entity_type:
            fact.entity_type = EntityType(entity_type)
            fact.entity_id = chosen_id
        fact.status = FactStatus.ACCEPTED
        fact.review_reason = (
            (fact.review_reason or "") + " Resolved by an operator."
        ).strip()

    record_audit(
        session,
        action="reconciliation.resolved" if not dismiss else "reconciliation.dismissed",
        entity_type=EntityType.SOURCE_DOCUMENT
        if item.source_document_id
        else EntityType.MESSAGE,
        entity_id=item.source_document_id or item.message_id or item.id,
        summary=f"Reconciliation “{item.question[:120]}” "
        f"{'dismissed' if dismiss else 'resolved'}.",
        actor_type="user",
        actor_user_id=user_id,
        after=resolution_payload,
    )
    record_metric(
        session,
        event_type=BusinessEventType.RECONCILIATION_RESOLVED,
        entity_type=EntityType.SOURCE_DOCUMENT if item.source_document_id else EntityType.MESSAGE,
        entity_id=item.source_document_id or item.message_id,
        user_id=user_id,
        duration_ms=clock.elapsed_ms(item.created_at),
        payload={"kind": item.kind, "dismissed": dismiss},
    )
    return item
