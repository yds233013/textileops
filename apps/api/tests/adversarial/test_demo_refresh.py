"""The daily demo reload: the most destructive thing TextileOps does by itself.

It truncates every table. So each condition it relies on is tested, and the
one that matters most is tested first: a real business's database that is
accidentally started in demo mode must be left alone.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy import func, select

from tests.conftest import make_sales_order
from textileops.core.config import settings
from textileops.models.platform import AuditEvent
from textileops.models.sales import SalesOrder
from textileops.seed.demo import DEMO_SEEDED_ACTION
from textileops.seed.refresh import refresh_demo_if_stale
from textileops.services import clock


@contextlib.contextmanager
def demo(on: bool = True, pilot: bool = False) -> Iterator[None]:
    previous = (settings.demo_mode, settings.pilot_mode)
    settings.demo_mode, settings.pilot_mode = on, pilot
    try:
        yield
    finally:
        settings.demo_mode, settings.pilot_mode = previous


def _orders(session) -> int:
    return session.scalar(select(func.count(SalesOrder.id))) or 0


def test_a_real_database_in_demo_mode_is_never_reset(session, customer, fabric):
    """Orders, and no marker from the demo seed: somebody's real data."""
    make_sales_order(session, customer, fabric)
    session.flush()
    before = _orders(session)
    with demo():
        result = refresh_demo_if_stale(session, force=True)
    assert result.refreshed is False
    assert "not created by the demo seed" in result.reason
    assert _orders(session) == before


def test_nothing_happens_outside_demo_mode(session):
    with demo(on=False):
        result = refresh_demo_if_stale(session, force=True)
    assert result.refreshed is False
    assert result.reason == "demo mode is off"


def test_demo_and_pilot_mode_together_refuse_before_touching_anything(session):
    with demo(on=True, pilot=True), pytest.raises(RuntimeError, match="PILOT_MODE"):
        refresh_demo_if_stale(session, force=True)


def test_an_empty_database_is_seeded_and_marked(session):
    """First boot of a demo deployment: nothing there, so load it."""
    with demo():
        result = refresh_demo_if_stale(session)
    assert result.refreshed is True
    assert _orders(session) > 0
    marker = session.scalar(select(AuditEvent).where(AuditEvent.action == DEMO_SEEDED_ACTION))
    assert marker is not None


def test_a_fresh_demo_is_left_alone_and_a_stale_one_is_reloaded(session):
    with demo():
        refresh_demo_if_stale(session)
        again = refresh_demo_if_stale(session)
        assert again.refreshed is False and again.reason == "already refreshed today"

        # A day later the same demo is stale.
        tomorrow = clock.now() + dt.timedelta(days=1)
        with clock.frozen(tomorrow):
            later = refresh_demo_if_stale(session)
    assert later.refreshed is True
