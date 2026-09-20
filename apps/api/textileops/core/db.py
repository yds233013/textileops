"""Database engine/session management.

PostgreSQL is the single source of truth for operational state. Sessions are
request-scoped; services receive a session and never open their own.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from textileops.core.config import settings

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
