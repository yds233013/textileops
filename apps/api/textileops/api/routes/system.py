"""Health, configuration visibility and job queue status."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, text

from textileops.api.deps import CurrentUser, DbSession
from textileops.core.config import settings
from textileops.models.actions import ActionProposal
from textileops.models.enums import (
    ACTIVE_EXCEPTION_STATUSES,
    ProposalStatus,
    ReconciliationStatus,
    Severity,
)
from textileops.models.exceptions import OperationalException
from textileops.models.intake import ReconciliationItem
from textileops.models.platform import Job
from textileops.workers.queue import registered_tasks

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str
    ai_provider: str
    ai_model: str | None
    version: str
    #: The data is fictional. The interface says so on every page.
    demo_mode: bool = False


@router.get("/health", response_model=HealthResponse)
def health(session: DbSession) -> HealthResponse:
    try:
        session.execute(text("select 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    from textileops import __version__

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        environment=settings.environment,
        database=database,
        ai_provider="anthropic" if settings.ai_enabled else "stub",
        ai_model=settings.ai_model if settings.ai_enabled else "deterministic-rules-v1",
        version=__version__,
        demo_mode=settings.demo_mode,
    )


class IntegrationStatus(BaseModel):
    key: str
    name: str
    configured: bool
    status: str
    detail: str


class SettingsResponse(BaseModel):
    environment: str
    #: True while TextileOps is deliberately not changing anything by itself.
    pilot_mode: bool
    pilot_mode_note: str
    simulation_enabled: bool
    ai_enabled: bool
    ai_model: str | None
    order_at_risk_buffer_days: int
    supplier_delay_warn_days: int
    shipment_delay_grace_days: int
    max_upload_mb: int
    allowed_upload_extensions: list[str]
    integrations: list[IntegrationStatus]
    worker_tasks: list[str]


@router.get("/settings", response_model=SettingsResponse)
def read_settings(_user: CurrentUser) -> SettingsResponse:
    """What is actually configured. Integrations that do not exist say so."""
    return SettingsResponse(
        environment=settings.environment,
        pilot_mode=settings.pilot_mode,
        pilot_mode_note=(
            "TextileOps is ingesting, reconciling, calculating and proposing, "
            "but will not change a delivery date, a purchase order or stock by "
            "itself. Every change waits for someone to confirm it."
            if settings.pilot_mode
            else "TextileOps applies confirmed supplier date changes automatically "
            "once they pass the deterministic checks. Consequential actions "
            "still require approval."
        ),
        simulation_enabled=settings.enable_simulation and not settings.is_production,
        ai_enabled=settings.ai_enabled,
        ai_model=settings.ai_model if settings.ai_enabled else "deterministic-rules-v1",
        order_at_risk_buffer_days=settings.order_at_risk_buffer_days,
        supplier_delay_warn_days=settings.supplier_delay_warn_days,
        shipment_delay_grace_days=settings.shipment_delay_grace_days,
        max_upload_mb=settings.max_upload_bytes // (1024 * 1024),
        allowed_upload_extensions=settings.allowed_upload_extensions,
        worker_tasks=registered_tasks(),
        integrations=[
            IntegrationStatus(
                key="anthropic",
                name="Anthropic (AI extraction & investigation)",
                configured=settings.ai_enabled,
                status="connected" if settings.ai_enabled else "not_configured",
                detail=(
                    f"Using {settings.ai_model}."
                    if settings.ai_enabled
                    else "No API key configured. TextileOps is running its deterministic "
                    "rule engine instead; every AI-derived item is labelled as such."
                ),
            ),
            IntegrationStatus(
                key="email",
                name="Email ingestion",
                configured=False,
                status="not_implemented",
                detail=(
                    "No mailbox connector is implemented. Messages can be entered manually "
                    "or uploaded as .eml files. Approved emails are produced as drafts for "
                    "a person to send — TextileOps never claims to have sent one."
                ),
            ),
            IntegrationStatus(
                key="whatsapp",
                name="WhatsApp ingestion",
                configured=False,
                status="not_implemented",
                detail=(
                    "No WhatsApp Business API connector is implemented. Paste message text "
                    "into the manual message form to ingest it through the same pipeline."
                ),
            ),
            IntegrationStatus(
                key="carrier",
                name="Carrier tracking",
                configured=False,
                status="not_implemented",
                detail=(
                    "Shipment tracking references are recorded manually; no carrier API "
                    "is connected."
                ),
            ),
        ],
    )


class QueueStatus(BaseModel):
    queued: int
    running: int
    succeeded: int
    failed: int
    dead: int


@router.get("/system/queue", response_model=QueueStatus)
def queue_status(session: DbSession, _user: CurrentUser) -> QueueStatus:
    counts = {
        status.value: count
        for status, count in session.execute(
            select(Job.status, func.count(Job.id)).group_by(Job.status)
        ).all()
    }
    return QueueStatus(
        queued=counts.get("queued", 0),
        running=counts.get("running", 0),
        succeeded=counts.get("succeeded", 0),
        failed=counts.get("failed", 0),
        dead=counts.get("dead", 0),
    )


class AttentionCounts(BaseModel):
    """What the navigation badges say. Four COUNT queries, nothing else."""

    exceptions: int
    critical: int
    approvals: int
    reconciliation: int


@router.get("/system/counts", response_model=AttentionCounts)
def attention_counts(session: DbSession, _user: CurrentUser) -> AttentionCounts:
    active = OperationalException.status.in_(ACTIVE_EXCEPTION_STATUSES)
    return AttentionCounts(
        exceptions=session.scalar(select(func.count(OperationalException.id)).where(active)) or 0,
        critical=session.scalar(
            select(func.count(OperationalException.id)).where(
                active, OperationalException.severity == Severity.CRITICAL
            )
        )
        or 0,
        approvals=session.scalar(
            select(func.count(ActionProposal.id)).where(
                ActionProposal.status == ProposalStatus.PENDING_APPROVAL
            )
        )
        or 0,
        reconciliation=session.scalar(
            select(func.count(ReconciliationItem.id)).where(
                ReconciliationItem.status == ReconciliationStatus.OPEN
            )
        )
        or 0,
    )
