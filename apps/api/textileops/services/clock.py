"""A single source of time.

Every service reads "now" from here so that tests, the exception engine and
the demo simulation all agree on what day it is. Nothing calls
``datetime.now()`` directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager

_frozen_at: dt.datetime | None = None


def now() -> dt.datetime:
    return _frozen_at or dt.datetime.now(dt.UTC)


def today() -> dt.date:
    return now().date()


@contextmanager
def frozen(at: dt.datetime) -> Iterator[dt.datetime]:
    """Freeze the clock. Test-only, but harmless in production code paths."""
    global _frozen_at
    previous = _frozen_at
    _frozen_at = at if at.tzinfo else at.replace(tzinfo=dt.UTC)
    try:
        yield _frozen_at
    finally:
        _frozen_at = previous


def ensure_utc(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


#: Longest duration we are willing to record, in milliseconds (~68 years, the
#: signed 32-bit ceiling the column stores).
_MAX_DURATION_MS = 2_147_483_647


def elapsed_ms(start: dt.datetime | None, end: dt.datetime | None = None) -> int | None:
    """Milliseconds between two moments, or ``None`` when that is not meaningful.

    A negative or absurd interval means the two timestamps did not come from the
    same clock (a server default versus application time, say). Recording that
    as a duration would quietly corrupt the instrumentation, so we record
    nothing instead.
    """
    if start is None:
        return None
    finish = end or now()
    delta = (ensure_utc(finish) - ensure_utc(start)).total_seconds() * 1000
    if delta < 0 or delta > _MAX_DURATION_MS:
        return None
    return int(delta)
