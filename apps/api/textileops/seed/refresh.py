"""Keeping a hosted demo current.

The demo is written relative to "today": promised dates in ten days, a supplier
delay from yesterday. Left alone for a week it ages into a business where
everything is late. So a demo deployment reloads itself once a day.

Reloading truncates every table, which makes this the most destructive thing
TextileOps can do on its own. It therefore needs all of:

* DEMO_MODE on — the deployment has declared its data fictional;
* PILOT_MODE off — enforced by ``settings.assert_consistent``;
* evidence that this database was made by the demo seed: a ``demo.seeded``
  audit event, or no customer orders at all.

A real business's database that someone accidentally starts in demo mode has
orders and no ``demo.seeded`` marker, and is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from textileops.core.config import settings
from textileops.core.db import advisory_xact_lock
from textileops.core.logging import get_logger
from textileops.models.platform import AuditEvent
from textileops.models.sales import SalesOrder
from textileops.seed.demo import DEMO_SEEDED_ACTION, seed_demo_business
from textileops.services import clock

logger = get_logger(__name__)


@dataclass
class RefreshResult:
    refreshed: bool
    reason: str


def refresh_demo_if_stale(session: Session, *, force: bool = False) -> RefreshResult:
    if not settings.demo_mode:
        return RefreshResult(False, "demo mode is off")
    settings.assert_consistent()

    # One refresher at a time, across every worker and every cron run.
    advisory_xact_lock(session, "textileops:demo-refresh")

    last = session.scalar(
        select(func.max(AuditEvent.occurred_at)).where(AuditEvent.action == DEMO_SEEDED_ACTION)
    )
    has_orders = session.scalar(select(SalesOrder.id).limit(1)) is not None
    if last is None and has_orders:
        logger.warning("demo_refresh_refused", reason="database was not created by the demo seed")
        return RefreshResult(
            False,
            "this database has orders and was not created by the demo seed; refusing to reset it",
        )
    if not force and last is not None and clock.ensure_utc(last).date() >= clock.today():
        return RefreshResult(False, "already refreshed today")

    seed_demo_business(session, reset=True)
    logger.info("demo_refreshed")
    return RefreshResult(True, "reloaded the demo for today")
