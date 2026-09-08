"""Engine / session factory.

The only network dependency ``backend/core`` is permitted
is the database, and only via this module. Tests call ``configure`` with an
in-memory SQLite URL so CI needs no live Postgres.

There is exactly one engine per process; ``create_all`` and every session share
it (important for SQLite ``:memory:``, where each connection is its own DB).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db.models import Base

DEFAULT_URL = "postgresql+psycopg://german:german@localhost:5432/german"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def resolve_url(url: str | None = None) -> str:
    """The DB URL to use: explicit arg, else $DATABASE_URL, else DEFAULT_URL."""
    return url or os.environ.get("DATABASE_URL") or DEFAULT_URL


def _build_engine(url: str) -> Engine:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            # Keep one connection alive so the in-memory DB persists.
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def configure(url: str | None = None, *, force: bool = False) -> Engine:
    """(Re)initialise the process engine. Idempotent unless ``force``."""
    global _engine, _SessionLocal
    if _engine is not None and not force:
        return _engine
    if _engine is not None:
        _engine.dispose()
    _engine = _build_engine(resolve_url(url))
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    return _engine or configure()


def create_all(url: str | None = None) -> None:
    """Create tables. Convenience for tests and local bootstrap; real schema
    changes go through ``backend/db/migrations``."""
    engine = configure(url, force=url is not None)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
