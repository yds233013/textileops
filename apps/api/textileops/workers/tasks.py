"""Background task handlers.

Every handler here is safe to run twice. Recomputation tasks are naturally
idempotent; anything that posts stock or executes an action is guarded by an
idempotency key in the service it calls.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from textileops.core.logging import get_logger
from textileops.ingestion import pipeline
from textileops.models.exceptions import OperationalException
from textileops.models.intake import Message, SourceDocument
from textileops.services import (
    actions,
    exception_engine,
    investigation,
    procurement,
    production,
)
from textileops.workers.queue import enqueue, enqueue_debounced, handler

logger = get_logger(__name__)


@handler("process_document")
def process_document(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    document = session.get(SourceDocument, uuid.UUID(payload["document_id"]))
    if document is None:
        return {"skipped": "document not found"}
    outcome = pipeline.process_document(session, document)
    enqueue_debounced(
        session, "recompute_exceptions", {"reason": "document_processed"}
    )
    return {
        "kind": document.kind.value,
        "status": document.status.value,
        "facts_created": outcome.facts_created,
        "reconciliation_items": outcome.reconciliation_items,
    }


@handler("process_message")
def process_message(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    message = session.get(Message, uuid.UUID(payload["message_id"]))
    if message is None:
        return {"skipped": "message not found"}
    outcome = pipeline.process_message(session, message)
    enqueue_debounced(
        session, "recompute_exceptions", {"reason": "message_processed"}
    )
    return {
        "intent": message.intent.value,
        "facts_applied": outcome.facts_applied,
        "reconciliation_items": outcome.reconciliation_items,
        "notes": outcome.notes,
    }


@handler("recompute_exceptions")
def recompute_exceptions(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh schedule estimates, then re-derive every exception."""
    production.refresh_all_estimates(session)
    actions.expire_stale_proposals(session)
    # Supplier scores have to move on the passage of time, not only on
    # delivery: a supplier who sends nothing is the commonest kind of late.
    rates_changed = procurement.recompute_all_supplier_rates(session)
    result = exception_engine.run(session)
    return {**result.summary(), "supplier_rates_changed": rates_changed}


@handler("investigate_exception")
def investigate_exception(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    exception = session.get(OperationalException, uuid.UUID(payload["exception_id"]))
    if exception is None:
        return {"skipped": "exception not found"}
    record = investigation.investigate_exception(
        session,
        exception,
        user_id=uuid.UUID(payload["user_id"]) if payload.get("user_id") else None,
    )
    return {
        "investigation_id": str(record.id),
        "ok": record.findings is not None,
        "tool_calls": len(record.tool_calls or []),
    }


@handler("investigate_critical_exceptions")
def investigate_critical_exceptions(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Queue investigations for anything critical that has none yet."""
    from textileops.models.enums import ACTIVE_EXCEPTION_STATUSES, Severity

    pending = session.scalars(
        select(OperationalException).where(
            OperationalException.severity == Severity.CRITICAL,
            OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES),
            OperationalException.investigated_at.is_(None),
        )
    ).all()
    queued = 0
    for exception in pending:
        job = enqueue(
            session,
            "investigate_exception",
            {"exception_id": str(exception.id)},
            idempotency_key=f"investigate:{exception.id}",
        )
        if job is not None:
            queued += 1
    return {"queued": queued, "candidates": len(pending)}
