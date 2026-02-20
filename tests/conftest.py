"""Shared test fixtures.

Tests use a real PostgreSQL/PostGIS database (via Docker Compose or local).
Set DATABASE_URL env var to override.  The test suite:
1. Applies all Alembic migrations.
2. Seeds with a small reproducible dataset.
3. Tears down after the session.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.db.engine import get_engine, get_session
from app.db.models import Base


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://milcon:milcon@localhost:5432/milcon",
    )


@pytest.fixture(scope="session")
def db_engine():
    engine = get_engine(_db_url())
    return engine


@pytest.fixture(scope="session")
def db_session(db_engine):
    """Session-scoped DB session.  Applies migrations and seeds once."""
    # Apply migrations via Alembic
    from alembic.config import Config
    from alembic import command

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", _db_url())
    command.upgrade(alembic_cfg, "head")

    session = get_session(_db_url())

    # Seed with small dataset
    from app.data.seed import seed_database

    # Check if data already exists
    count = session.execute(text("SELECT COUNT(*) FROM installations")).scalar()
    if count == 0:
        seed_database(session, total_rows=200, rng_seed=42)

    yield session
    session.close()
