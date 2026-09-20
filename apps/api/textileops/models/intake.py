"""Ingested source material and the facts extracted from it.

Everything in this module is **untrusted input**. Nothing here mutates
operational state directly; facts are proposed, validated, resolved to
entities and only then applied by deterministic services.

Source documents and messages are never deleted — reconciliation supersedes,
it does not erase.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textileops.models.base import TS, Base, Rate, TimestampMixin, enum_column, pk_column
from textileops.models.enums import (
    DocumentKind,
    DocumentStatus,
    EntityType,
    FactStatus,
    MessageDirection,
    MessageIntent,
    ReconciliationStatus,
    SourceChannel,
)


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = pk_column()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Path relative to the configured upload root. Never a user-supplied path.
    stored_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Content hash — the basis for duplicate detection of re-forwarded files.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[SourceChannel] = mapped_column(
        enum_column(SourceChannel, "source_channel"), nullable=False
    )
    kind: Mapped[DocumentKind] = mapped_column(
        enum_column(DocumentKind, "document_kind"), nullable=False, default=DocumentKind.UNKNOWN
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_column(DocumentStatus, "document_status"),
        nullable=False,
        default=DocumentStatus.RECEIVED,
    )
    classification_confidence: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    received_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    processed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        # RESTRICT, not SET NULL: this records what a person did, and
        # deleting their account must not rewrite that into "somebody".
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Plain-text rendering used for extraction. Treated as untrusted content.
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_metadata: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="byte_size_non_negative"),
        Index("ix_source_documents_status_received", "status", "received_at"),
        Index("ix_source_documents_sha256", "sha256"),
    )


class Message(Base, TimestampMixin):
    """A supplier/customer communication (email, WhatsApp, manual note)."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = pk_column()
    channel: Mapped[SourceChannel] = mapped_column(
        enum_column(SourceChannel, "source_channel"), nullable=False
    )
    direction: Mapped[MessageDirection] = mapped_column(
        enum_column(MessageDirection, "message_direction"),
        nullable=False,
        default=MessageDirection.INBOUND,
    )
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: Untrusted content. Never interpolated into a prompt as instructions.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[dt.datetime] = mapped_column(TS, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    thread_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Normalised-body hash: catches the same message forwarded twice.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    #: *How* this message came to be linked to that supplier. The distinction
    #: is the whole of invariant 7 on this path: "caller" is a signed-in
    #: operator saying so and "sender_address" is transport metadata, but
    #: "extracted_text" is a name the model copied out of the message body —
    #: which is to say, out of whatever the sender chose to write. A link made
    #: that way is fine for showing the message next to a supplier and must
    #: never authorise a change to that supplier's orders.
    supplier_attribution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    intent: Mapped[MessageIntent] = mapped_column(
        enum_column(MessageIntent, "message_intent"), nullable=False, default=MessageIntent.UNKNOWN
    )
    intent_confidence: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_messages_received", "received_at"),
        Index("ix_messages_supplier_received", "supplier_id", "received_at"),
        Index("ix_messages_content_hash", "content_hash"),
        Index("ix_messages_intent", "intent"),
    )


class ExtractedFact(Base, TimestampMixin):
    """One structured claim derived from untrusted source material."""

    __tablename__ = "extracted_facts"

    id: Mapped[uuid.UUID] = pk_column()
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    #: e.g. "purchase_order.revised_eta", "receipt.quantity"
    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Exactly as it appeared in the source. Preserved forever.
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Validated, normalised representation (typed JSON).
    normalized_value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    status: Mapped[FactStatus] = mapped_column(
        enum_column(FactStatus, "fact_status"), nullable=False, default=FactStatus.PROPOSED
    )
    #: Resolved target entity, when entity resolution succeeded.
    entity_type: Mapped[EntityType | None] = mapped_column(
        enum_column(EntityType, "entity_type"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    applied_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extracted_facts.id", ondelete="SET NULL"), nullable=True
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(source_document_id is not null) or (message_id is not null)",
            name="fact_has_a_source",
        ),
        CheckConstraint(
            "confidence is null or (confidence >= 0 and confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_extracted_facts_status_type", "status", "fact_type"),
        Index("ix_extracted_facts_entity", "entity_type", "entity_id"),
        # "What did we extract from this document?" runs on every ingested
        # document and again per message. Both were sequential scans of the
        # whole table: 12.7 ms to find 10 rows among 200,000, against 0.15 ms
        # indexed. It only gets worse as the mill's correspondence accumulates.
        Index("ix_extracted_facts_document", "source_document_id"),
        Index("ix_extracted_facts_message", "message_id"),
    )


class ReconciliationItem(Base, TimestampMixin):
    """A question TextileOps cannot answer on its own; a human must decide."""

    __tablename__ = "reconciliation_items"

    id: Mapped[uuid.UUID] = pk_column()
    extracted_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extracted_facts.id", ondelete="CASCADE"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    #: e.g. "entity_resolution", "ambiguous_unit", "ambiguous_date", "no_match"
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(nullable=True)
    status: Mapped[ReconciliationStatus] = mapped_column(
        enum_column(ReconciliationStatus, "reconciliation_status"),
        nullable=False,
        default=ReconciliationStatus.OPEN,
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        # RESTRICT, not SET NULL: this records what a person did, and
        # deleting their account must not rewrite that into "somebody".
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)

    fact: Mapped[ExtractedFact | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_reconciliation_status_created", "status", "created_at"),
    )
