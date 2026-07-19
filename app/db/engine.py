"""SQLAlchemy engine and session factory.

Engines are cached per database URL, so a caller passing an explicit URL
(e.g. a test suite) gets its own engine without repointing other callers'
default engine.
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url

_engines: dict[str, Engine] = {}


def get_engine(url: str | None = None) -> Engine:
    resolved = url or get_database_url()
    if resolved not in _engines:
        _engines[resolved] = create_engine(resolved, echo=False, pool_pre_ping=True)
    return _engines[resolved]


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


def get_session(url: str | None = None) -> Session:
    return get_session_factory(url)()


def ensure_postgis(session: Session) -> None:
    """Ensure the PostGIS extension is available."""
    session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    session.commit()
