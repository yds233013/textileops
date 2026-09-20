"""Health, configuration visibility and job queue status."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select, text

from textileops.api.deps import CurrentUser, DbSession
from textileops.core.config import settings
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
    )


class IntegrationStatus(BaseModel):
    key: str
    name: str
    configured: bool
    status: str
    detail: str


class SettingsResponse(BaseModel):
    environment: str
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
