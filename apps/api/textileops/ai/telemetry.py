"""AI call telemetry.

Records model, latency, tokens, request id, validation status and retries for
every call — including stubbed ones, so the mix of real vs deterministic output
is visible rather than assumed. Prompts and untrusted content are never stored
here.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from textileops.ai.base import AgentResult, AIResult
from textileops.core.logging import get_logger
from textileops.models.enums import AICallStatus, EntityType
from textileops.models.platform import AICallLog
from textileops.services import clock

logger = get_logger(__name__)


def record_call(
    session: Session,
    *,
    workflow: str,
    result: AIResult | AgentResult,
    entity_type: EntityType | None = None,
    entity_id: uuid.UUID | None = None,
    prompt_version: str | None = None,
) -> AICallLog:
    log = AICallLog(
        created_at=clock.now(),
        workflow=workflow,
        provider=result.provider,
        model=result.model,
        status=result.status,
        latency_ms=result.latency_ms,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        request_id=result.request_id,
        attempt=getattr(result, "attempts", 1),
        prompt_version=prompt_version,
        validation_error=result.validation_error,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    session.add(log)
    logger.info(
        "ai_call",
        workflow=workflow,
        provider=result.provider,
        model=result.model,
        status=result.status.value,
        latency_ms=result.latency_ms,
        stubbed=result.stubbed,
    )
    return log


def status_for(ok: bool, stubbed: bool) -> AICallStatus:
    if stubbed:
        return AICallStatus.STUBBED
    return AICallStatus.SUCCESS if ok else AICallStatus.VALIDATION_FAILED
