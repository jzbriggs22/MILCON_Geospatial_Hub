"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url

_engine = None
_SessionLocal = None


def get_engine(url: str | None = None):
    global _engine
    if _engine is None or url is not None:
        _engine = create_engine(url or get_database_url(), echo=False, pool_pre_ping=True)
    return _engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None or url is not None:
        _SessionLocal = sessionmaker(bind=get_engine(url), expire_on_commit=False)
    return _SessionLocal


def get_session(url: str | None = None) -> Session:
    return get_session_factory(url)()


def ensure_postgis(session: Session) -> None:
    """Ensure the PostGIS extension is available."""
    session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    session.commit()
