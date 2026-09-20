"""Document ingestion, messages and the reconciliation queue."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from textileops.api.deps import ApproverUser, CurrentUser, DbSession
from textileops.core.config import settings
from textileops.core.errors import NotFoundError, ValidationError
from textileops.ingestion import pipeline
from textileops.models.enums import (
    DocumentStatus,
    ReconciliationStatus,
    SourceChannel,
)
from textileops.models.intake import (
    ExtractedFact,
    Message,
    ReconciliationItem,
    SourceDocument,
)
from textileops.workers.queue import enqueue

router = APIRouter(tags=["ingestion"])


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    byte_size: int
    channel: str
    kind: str
    status: str
    classification_confidence: float | None
    received_at: dt.datetime
    processed_at: dt.datetime | None
    page_count: int | None
    error: str | None
    is_duplicate: bool
    warnings: list[str]
    fact_count: int


class FactOut(BaseModel):
    id: uuid.UUID
    fact_type: str
    field_path: str | None
    raw_value: str | None
    normalized_value: dict[str, Any] | None
    unit: str | None
    confidence: float | None
    status: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    model: str | None
    applied_at: dt.datetime | None
    review_reason: str | None


class DocumentDetailOut(DocumentOut):
    extracted_text_excerpt: str | None
    facts: list[FactOut]
    reconciliation_items: list[ReconciliationOut]


def _document_out(session: DbSession, document: SourceDocument) -> DocumentOut:
    fact_count = len(
        session.scalars(
            select(ExtractedFact.id).where(ExtractedFact.source_document_id == document.id)
        ).all()
    )
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        channel=document.channel.value,
        kind=document.kind.value,
        status=document.status.value,
        classification_confidence=(
            float(document.classification_confidence)
            if document.classification_confidence is not None
            else None
        ),
        received_at=document.received_at,
        processed_at=document.processed_at,
        page_count=document.page_count,
        error=document.error,
        is_duplicate=document.duplicate_of_id is not None,
        warnings=list((document.doc_metadata or {}).get("warnings", [])),
        fact_count=fact_count,
    )


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    session: DbSession,
    _user: CurrentUser,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[DocumentOut]:
    stmt = select(SourceDocument).order_by(SourceDocument.received_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(SourceDocument.status == DocumentStatus(status))
    return [_document_out(session, doc) for doc in session.scalars(stmt).all()]


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> DocumentDetailOut:
    document = session.get(SourceDocument, document_id)
    if document is None:
        raise NotFoundError(f"Document {document_id} not found.")
    facts = session.scalars(
        select(ExtractedFact)
        .where(ExtractedFact.source_document_id == document.id)
        .order_by(ExtractedFact.created_at)
    ).all()
    items = session.scalars(
        select(ReconciliationItem).where(ReconciliationItem.source_document_id == document.id)
    ).all()
    return DocumentDetailOut(
        **_document_out(session, document).model_dump(),
        extracted_text_excerpt=(document.extracted_text or "")[:5000] or None,
        facts=[_fact_out(fact) for fact in facts],
        reconciliation_items=[_reconciliation_out(item) for item in items],
    )


def _fact_out(fact: ExtractedFact) -> FactOut:
    return FactOut(
        id=fact.id,
        fact_type=fact.fact_type,
        field_path=fact.field_path,
        raw_value=fact.raw_value,
        normalized_value=fact.normalized_value,
        unit=fact.unit,
        confidence=float(fact.confidence) if fact.confidence is not None else None,
        status=fact.status.value,
        entity_type=fact.entity_type.value if fact.entity_type else None,
        entity_id=fact.entity_id,
        model=fact.model,
        applied_at=fact.applied_at,
        review_reason=fact.review_reason,
    )


class UploadResponse(BaseModel):
    document: DocumentOut
    queued: bool
    message: str


@router.post("/documents", response_model=UploadResponse)
async def upload_document(
    session: DbSession,
    user: ApproverUser,
    file: UploadFile = File(...),
    channel: str = Form("upload"),
    process_now: bool = Form(True),
) -> UploadResponse:
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise ValidationError(
            f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB limit."
        )
    document = pipeline.receive_document(
        session,
        content=content,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        channel=SourceChannel(channel),
        uploaded_by_user_id=user.id,
    )
    session.commit()

    if process_now:
        # Processed inline so the operator sees the result immediately; the same
        # code path runs in the worker.
        pipeline.process_document(session, document)
        session.commit()
        message = "Uploaded and processed."
    else:
        enqueue(
            session,
            "process_document",
            {"document_id": str(document.id)},
            idempotency_key=f"process_document:{document.id}",
        )
        session.commit()
        message = "Uploaded and queued for processing."

    return UploadResponse(
        document=_document_out(session, document),
        queued=not process_now,
        message=message,
    )


@router.post("/documents/{document_id}/reprocess", response_model=DocumentOut)
def reprocess_document(
    document_id: uuid.UUID, session: DbSession, _user: ApproverUser
) -> DocumentOut:
    document = session.get(SourceDocument, document_id)
    if document is None:
        raise NotFoundError(f"Document {document_id} not found.")
    pipeline.process_document(session, document)
    session.commit()
    return _document_out(session, document)


# --- Messages -----------------------------------------------------------------


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    sender: str = Field(min_length=1, max_length=255)
    subject: str | None = None
    channel: str = "manual"
    supplier_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    received_at: dt.datetime | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    channel: str
    direction: str
    sender: str
    subject: str | None
    body: str
    received_at: dt.datetime
    processed_at: dt.datetime | None
    intent: str
    intent_confidence: float | None
    supplier_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    is_duplicate: bool


class MessageIngestResponse(BaseModel):
    message: MessageOut
    facts_created: int
    facts_applied: int
    reconciliation_items: int
    notes: list[str]
    warnings: list[str]


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        channel=message.channel.value,
        direction=message.direction.value,
        sender=message.sender,
        subject=message.subject,
        body=message.body,
        received_at=message.received_at,
        processed_at=message.processed_at,
        intent=message.intent.value,
        intent_confidence=(
            float(message.intent_confidence) if message.intent_confidence is not None else None
        ),
        supplier_id=message.supplier_id,
        customer_id=message.customer_id,
        is_duplicate=message.duplicate_of_id is not None,
    )


@router.get("/messages", response_model=list[MessageOut])
def list_messages(
    session: DbSession,
    _user: CurrentUser,
    supplier_id: uuid.UUID | None = None,
    intent: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[MessageOut]:
    stmt = select(Message).order_by(Message.received_at.desc()).limit(limit)
    if supplier_id:
        stmt = stmt.where(Message.supplier_id == supplier_id)
    if intent:
        stmt = stmt.where(Message.intent == intent)
    return [_message_out(message) for message in session.scalars(stmt).all()]


@router.post("/messages", response_model=MessageIngestResponse)
def ingest_message(
    payload: MessageIn, session: DbSession, user: ApproverUser
) -> MessageIngestResponse:
    message = pipeline.receive_message(
        session,
        body=payload.body,
        sender=payload.sender,
        subject=payload.subject,
        channel=SourceChannel(payload.channel),
        supplier_id=payload.supplier_id,
        customer_id=payload.customer_id,
        received_at=payload.received_at,
    )
    session.commit()
    outcome = pipeline.process_message(session, message)
    session.commit()
    return MessageIngestResponse(
        message=_message_out(message),
        facts_created=outcome.facts_created,
        facts_applied=outcome.facts_applied,
        reconciliation_items=outcome.reconciliation_items,
        notes=outcome.notes,
        warnings=outcome.warnings,
    )


# --- Reconciliation -----------------------------------------------------------


class ReconciliationOut(BaseModel):
    id: uuid.UUID
    kind: str
    question: str
    candidates: list[dict[str, Any]] | None
    status: str
    created_at: dt.datetime
    resolved_at: dt.datetime | None
    resolution: dict[str, Any] | None
    source_document_id: uuid.UUID | None
    message_id: uuid.UUID | None
    extracted_fact_id: uuid.UUID | None
    fact_raw_value: str | None


def _reconciliation_out(item: ReconciliationItem) -> ReconciliationOut:
    return ReconciliationOut(
        id=item.id,
        kind=item.kind,
        question=item.question,
        candidates=item.candidates,
        status=item.status.value,
        created_at=item.created_at,
        resolved_at=item.resolved_at,
        resolution=item.resolution,
        source_document_id=item.source_document_id,
        message_id=item.message_id,
        extracted_fact_id=item.extracted_fact_id,
        fact_raw_value=(
            item.fact.raw_value[:500] if item.fact and item.fact.raw_value else None
        ),
    )


@router.get("/reconciliation", response_model=list[ReconciliationOut])
def list_reconciliation(
    session: DbSession,
    _user: CurrentUser,
    status: str = "open",
    limit: int = Query(200, ge=1, le=500),
) -> list[ReconciliationOut]:
    stmt = (
        select(ReconciliationItem)
        .where(ReconciliationItem.status == ReconciliationStatus(status))
        .order_by(ReconciliationItem.created_at)
        .limit(limit)
    )
    return [_reconciliation_out(item) for item in session.scalars(stmt).all()]


class ResolveReconciliationRequest(BaseModel):
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    value: str | None = None
    note: str | None = None
    dismiss: bool = False


@router.post("/reconciliation/{item_id}/resolve", response_model=ReconciliationOut)
def resolve_reconciliation(
    item_id: uuid.UUID,
    payload: ResolveReconciliationRequest,
    session: DbSession,
    user: ApproverUser,
) -> ReconciliationOut:
    item = session.get(ReconciliationItem, item_id)
    if item is None:
        raise NotFoundError(f"Reconciliation item {item_id} not found.")
    if item.status != ReconciliationStatus.OPEN:
        raise ValidationError("This item has already been resolved.")
    pipeline.resolve_reconciliation(
        session,
        item,
        resolution_payload={
            "entity_type": payload.entity_type,
            "entity_id": str(payload.entity_id) if payload.entity_id else None,
            "value": payload.value,
            "note": payload.note,
        },
        user_id=user.id,
        dismiss=payload.dismiss,
    )
    session.commit()
    return _reconciliation_out(item)
