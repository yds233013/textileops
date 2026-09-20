"""Database engine/session management.

PostgreSQL is the single source of truth for operational state. Sessions are
request-scoped; services receive a session and never open their own.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, object_mapper, sessionmaker

from textileops.core.config import settings
from textileops.core.errors import ConflictError

_T = TypeVar("_T")

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts, workers and tests."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency. Commit is explicit in the route/service layer."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def lock_row(session: Session, instance: _T) -> _T:
    """Take a row-level write lock on ``instance`` and refresh it from disk.

    Several of our write paths are read-modify-write: read a balance, decide
    whether the change is legal, store the new absolute value. At PostgreSQL's
    default READ COMMITTED that is a lost update — two sessions read the same
    starting figure, both conclude the change is legal, and the second write
    silently erases the first. The stored value stays individually plausible,
    so no CHECK constraint can catch it; only holding the row across the
    read and the write makes the sequence well defined.

    ``Session.get(..., with_for_update=True)`` cannot be used for this: it
    emits the mapper's eager loads, and PostgreSQL refuses ``FOR UPDATE`` on
    the nullable side of an outer join. So we lock the row by primary key
    alone, then refresh the object through the ordinary loader.

    Callers that lock several rows in one transaction must do so in a
    consistent order, or two transactions can deadlock on each other.
    """
    mapper = object_mapper(instance)
    pk_column = mapper.primary_key[0]
    pk_value = mapper.primary_key_from_instance(instance)[0]
    if pk_value is None or instance in session.new:
        session.flush()
        pk_value = mapper.primary_key_from_instance(instance)[0]

    locked = session.execute(
        select(pk_column).where(pk_column == pk_value).with_for_update()
    ).one_or_none()
    if locked is None:
        raise ConflictError(
            f"The {type(instance).__name__} being updated no longer exists.",
            details={"id": str(pk_value)},
        )
    session.refresh(instance)
    return instance


def advisory_xact_lock(session: Session, name: str) -> None:
    """Serialise a whole operation across connections until the transaction ends.

    Row locks are the right tool when there is a row to lock. A full recompute
    pass has no such row: it allocates sequential codes with ``count(*) + 1``
    and inserts against a unique dedupe key, so two passes running at once both
    pick the same next code and whichever loses the unique index takes its
    entire transaction down — every exception, evidence row and audit event it
    would have written is rolled back, and the operator is simply never told
    about the conditions it found.

    The lock is held until commit or rollback, so it cannot leak.
    """
    key = int.from_bytes(hashlib.blake2b(name.encode(), digest_size=8).digest(), "big")
    # Postgres advisory keys are signed 64-bit.
    signed = key - (1 << 64) if key >= (1 << 63) else key
    session.execute(select(func.pg_advisory_xact_lock(signed)))
