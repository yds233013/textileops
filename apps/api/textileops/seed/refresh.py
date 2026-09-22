"""Keeping a hosted demo current.

The demo is written relative to "today": promised dates in ten days, a supplier
delay from yesterday. Left alone for a week it ages into a business where
everything is late. So a demo deployment reloads itself once a day.

It is also shared. One visitor who approves every proposal and closes every
exception leaves the next visitor a finished story. So once visitors have
changed anything and then left it alone for ``IDLE_RESET_MINUTES``, it reloads
— never underneath someone who is still clicking.

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

import datetime as dt
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

#: How long the demo must be left alone after a visitor changed it before it
#: reloads. Long enough not to reset under a person reading a page.
IDLE_RESET_MINUTES = 30

logger = get_logger(__name__)


@dataclass
class RefreshResult:
    refreshed: bool
    reason: str


def refresh_demo_if_stale(
    session: Session, *, force: bool = False, just_started: bool = False
) -> RefreshResult:
    """Reload the demo if it is from an earlier day, or visitors changed it and left.

    ``just_started`` is for the moment the container boots. On a host that
    puts idle services to sleep (Render's free plan sleeps after 15 minutes
    without a request), waking up *is* the evidence that everyone left, and a
    worker thread that sleeps with the service would never see 30 idle minutes
    go by. So at boot any visitor change is reason enough.
    """
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
    reason = _why_reload(session, last, force=force, just_started=just_started)
    if reason is None:
        return RefreshResult(False, "already refreshed today, and no visitor has changed it since")

    seed_demo_business(session, reset=True)
    logger.info("demo_refreshed", reason=reason)
    return RefreshResult(True, f"reloaded the demo: {reason}")


def _why_reload(
    session: Session, last: dt.datetime | None, *, force: bool, just_started: bool
) -> str | None:
    if force:
        return "forced"
    if last is None:
        return "first load"
    seeded_at = clock.ensure_utc(last)
    if seeded_at.date() < clock.today():
        return "a new day"
    # A person's change after the seed wrote its marker (which it writes last).
    visitor_last = session.scalar(
        select(func.max(AuditEvent.occurred_at)).where(
            AuditEvent.actor_type == "user", AuditEvent.occurred_at > seeded_at
        )
    )
    if visitor_last is None:
        return None
    if just_started:
        return "visitors changed it, and the service has just started"
    idle = clock.now() - clock.ensure_utc(visitor_last)
    if idle >= dt.timedelta(minutes=IDLE_RESET_MINUTES):
        return f"visitors changed it and it has been idle for {IDLE_RESET_MINUTES} minutes"
    return None
