"""Audit trail and product instrumentation.

Two distinct streams, deliberately not merged:

* :func:`record_audit` — *what changed and who changed it*. Legally/operationally
  meaningful; every consequential state change writes one.
* :func:`record_metric` — *how the product is being used*. Counts and durations
  only; never derived claims such as "hours saved".
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.orm import Session

from textileops.core.logging import business_logger, get_logger
from textileops.models.enums import BusinessEventType, EntityType
from textileops.models.platform import AuditEvent, BusinessMetricEvent
from textileops.services import clock

logger = get_logger(__name__)

ActorType = str  # "user" | "system" | "ai"


def record_audit(
    session: Session,
    *,
    action: str,
    entity_type: EntityType,
    entity_id: uuid.UUID,
    summary: str,
    actor_type: ActorType = "system",
    actor_user_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
    exception_id: uuid.UUID | None = None,
    action_proposal_id: uuid.UUID | None = None,
    source_document_id: uuid.UUID | None = None,
    occurred_at: dt.datetime | None = None,
) -> AuditEvent:
    event = AuditEvent(
        occurred_at=occurred_at or clock.now(),
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_label=actor_label,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        before=_jsonable(before),
        after=_jsonable(after),
        request_id=request_id,
        exception_id=exception_id,
        action_proposal_id=action_proposal_id,
        source_document_id=source_document_id,
    )
    session.add(event)
    logger.info(
        "audit",
        action=action,
        entity_type=entity_type.value,
        entity_id=str(entity_id),
        actor_type=actor_type,
    )
    return event


def record_metric(
    session: Session,
    *,
    event_type: BusinessEventType,
    entity_type: EntityType | None = None,
    entity_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    duration_ms: int | None = None,
    payload: dict[str, Any] | None = None,
    occurred_at: dt.datetime | None = None,
) -> BusinessMetricEvent:
    event = BusinessMetricEvent(
        event_type=event_type,
        occurred_at=occurred_at or clock.now(),
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        duration_ms=duration_ms,
        payload=_jsonable(payload),
    )
    session.add(event)
    business_logger.info(
        "business_event",
        event_type=event_type.value,
        entity_type=entity_type.value if entity_type else None,
        entity_id=str(entity_id) if entity_id else None,
        duration_ms=duration_ms,
    )
    return event


def _jsonable(value: Any) -> Any:
    """Make Decimals/dates/UUIDs storable in JSONB without losing precision."""
    import datetime as _dt
    from decimal import Decimal

    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value") and hasattr(value, "name"):  # enum
        return value.value
    return value
